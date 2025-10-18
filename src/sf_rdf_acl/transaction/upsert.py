"""RDF Upsert 请求建模与执行计划生成逻辑。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Literal, Optional

from pydantic import BaseModel

from common.config import ConfigManager
from common.config.settings import Settings
from sf_rdf_acl.query.dsl import GraphRef
from sf_rdf_acl.utils import resolve_graph_iri


class Triple(BaseModel):
    """描述一条 RDF 三元组，支持可选语言或数据类型标注。"""

    s: str
    p: str
    o: str
    lang: str | None = None
    dtype: str | None = None


class Provenance(BaseModel):
    """溯源附加信息，用于记录写入操作的上下文。"""

    evidence: str | None = None
    confidence: float | None = None
    source: str | None = None


class UpsertRequest(BaseModel):
    """承载业务层发起的 Upsert 写入请求。"""

    graph: GraphRef
    triples: list[Triple]
    upsert_key: Literal["s", "s+p", "custom"] = "s"
    custom_key_fields: list[str] | None = None
    merge_strategy: Literal["replace", "ignore", "append"] = "replace"
    provenance: Provenance | None = None


@dataclass(slots=True)
class UpsertStatement:
    """包装一条 SPARQL Update 语句及其元数据。"""

    sparql: str
    key: str
    strategy: Literal["replace", "ignore", "append"]
    triples: list[Triple]
    requires_snapshot: bool


@dataclass(slots=True)
class UpsertPlan:
    """Upsert 执行计划，包含语句集合与请求摘要。"""

    graph_iri: str
    statements: list[UpsertStatement]
    request_hash: str


class UpsertPlanner:
    """按照配置生成 Upsert 语句计划。"""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        """保存配置引用，默认读取 ConfigManager 当前实例。"""

        self._settings = settings or ConfigManager.current().settings

    def plan(self, request: UpsertRequest) -> UpsertPlan:
        """根据请求内容生成 UpsertPlan。"""

        if not request.triples:
            raise ValueError("UpsertRequest.triples 不能为空")

        graph_iri = resolve_graph_iri(request.graph, self._settings)
        if not graph_iri:
            raise ValueError("无法解析命名图 IRI")

        statements: list[UpsertStatement] = []
        for key, triples in self._group_triples(request):
            if request.merge_strategy == "replace":
                statements.append(self._build_replace_statement(graph_iri, key, triples))
            elif request.merge_strategy == "ignore":
                for triple in triples:
                    statements.append(self._build_ignore_statement(graph_iri, key, triple))
            else:
                statements.append(self._build_append_statement(graph_iri, key, triples))

        payload_json = request.model_dump_json(by_alias=True, exclude_none=True)
        request_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        return UpsertPlan(graph_iri=graph_iri, statements=statements, request_hash=request_hash)

    def _group_triples(self, request: UpsertRequest) -> Iterable[tuple[str, list[Triple]]]:
        """根据 upsert key 将三元组分桶，返回 (key, triples) 迭代器。"""

        buckets: dict[str, list[Triple]] = {}
        for triple in request.triples:
            key = self._compose_key(triple, request)
            buckets.setdefault(key, []).append(triple)
        return buckets.items()

    def _compose_key(self, triple: Triple, request: UpsertRequest) -> str:
        """生成分组键，支持 s、s+p 或自定义字段组合。"""

        if request.upsert_key == "s":
            return f"s::{triple.s}"
        if request.upsert_key == "s+p":
            return f"sp::{triple.s}::{triple.p}"
        fields = request.custom_key_fields or []
        if not fields:
            raise ValueError("custom 模式必须提供 custom_key_fields")
        allowed = {"s", "p", "o"}
        invalid = set(fields) - allowed
        if invalid:
            raise ValueError(f"custom_key_fields 存在非法字段: {', '.join(sorted(invalid))}")
        marker = ','.join(fields)
        parts = [f"{field}::{getattr(triple, field)}" for field in fields]
        return f"custom[{marker}]::" + "::".join(parts)

    def _build_replace_statement(self, graph_iri: str, key: str, triples: list[Triple]) -> UpsertStatement:
        """生成 replace 策略的 DELETE/INSERT 语句，保证目标值被完全替换。"""

        key_map = self._parse_key(key, triples[0])
        subject_expr = self._format_iri(key_map.get("s", triples[0].s))
        predicate_expr = self._format_iri(key_map.get("p", triples[0].p))
        object_expr = self._format_value_literal(triples[0]) if key_map.get("o") else None

        where_lines = [
            f"  VALUES (?__target_s ?__target_p) {{ ({subject_expr} {predicate_expr}) }}",
        ]
        if object_expr:
            delete_block = (
                f"  GRAPH <{graph_iri}> {{ ?__target_s ?__target_p ?__target_o . }}\n"
            )
            where_lines.append(f"  VALUES ?__target_o {{ {object_expr} }}")
            where_lines.append(
                f"  OPTIONAL {{ GRAPH <{graph_iri}> {{ ?__target_s ?__target_p ?__target_o . }} }}"
            )
        else:
            delete_block = (
                f"  GRAPH <{graph_iri}> {{ ?__target_s ?__target_p ?__existing_o . }}\n"
            )
            where_lines.append(
                f"  OPTIONAL {{ GRAPH <{graph_iri}> {{ ?__target_s ?__target_p ?__existing_o . }} }}"
            )

        insert_block = self._render_triple_block(graph_iri, triples)
        sparql = (
            "DELETE {\n"
            f"{delete_block}"
            "}\nINSERT {\n"
            f"{insert_block}"
            "}\nWHERE {\n"
            f"{'\n'.join(where_lines)}\n"
            "}\n"
        )
        return UpsertStatement(
            sparql=sparql,
            key=key,
            strategy="replace",
            triples=triples,
            requires_snapshot=True,
        )

    def _build_ignore_statement(self, graph_iri: str, key: str, triple: Triple) -> UpsertStatement:
        """生成 ignore 策略语句，借助 FILTER NOT EXISTS 防止重复插入。"""

        triple_fragment = self._render_triple(triple)
        insert_block = self._render_triple_block(graph_iri, [triple])
        sparql = (
            "INSERT {\n"
            f"{insert_block}"
            "}WHERE {\n"
            f"  FILTER NOT EXISTS {{ GRAPH <{graph_iri}> {{ {triple_fragment} }} }}\n"
            "}"
        )
        return UpsertStatement(
            sparql=sparql,
            key=key,
            strategy="ignore",
            triples=[triple],
            requires_snapshot=False,
        )

    def _build_append_statement(self, graph_iri: str, key: str, triples: list[Triple]) -> UpsertStatement:
        """生成 append 策略语句，直接向目标图追加所有三元组。"""

        insert_block = self._render_triple_block(graph_iri, triples)
        sparql = (
            "INSERT {\n"
            f"{insert_block}"
            "}WHERE { }"
        )
        return UpsertStatement(
            sparql=sparql,
            key=key,
            strategy="append",
            triples=triples,
            requires_snapshot=False,
        )

    def _render_triple_block(self, graph_iri: str, triples: Iterable[Triple]) -> str:
        """以 GRAPH 块形式渲染三元组集合。"""

        triple_lines = ["    " + self._render_triple(triple) for triple in triples]
        joined = "\n".join(triple_lines)
        return f"  GRAPH <{graph_iri}> {{\n{joined}\n  }}\n"

    def _render_triple(self, triple: Triple) -> str:
        """渲染单条三元组语句片段。"""

        return (
            f"{self._format_subject(triple.s)} "
            f"{self._format_predicate(triple.p)} "
            f"{self._format_object(triple)} ."
        )

    def _format_subject(self, value: str) -> str:
        """将主体值格式化为合法 IRI 或空白节点表示。"""

        return self._format_iri(value)

    def _format_predicate(self, value: str) -> str:
        """将谓词值格式化为合法 IRI。"""

        return self._format_iri(value)

    def _format_object(self, triple: Triple) -> str:
        """根据对象类型返回正确的 RDF 表达。"""

        if triple.dtype:
            literal = self._escape_literal(triple.o)
            return f'"{literal}"^^<{triple.dtype}>'
        if triple.lang:
            literal = self._escape_literal(triple.o)
            return f'"{literal}"@{triple.lang}'
        if self._is_iri(triple.o):
            return self._format_iri(triple.o)
        literal = self._escape_literal(triple.o)
        return f'"{literal}"'

    def _format_value_literal(self, triple: Triple) -> str:
        """生成 VALUES 用的 literal 表达，处理语言和数据类型。"""

        if triple.dtype or triple.lang:
            return self._format_object(triple)
        literal = self._escape_literal(triple.o)
        return f'"{literal}"'

    @staticmethod
    def _escape_literal(value: str) -> str:
        """转义 literal 中的反斜杠与双引号。"""

        return value.replace("\\", "\\\\").replace('"', '\"')

    @staticmethod
    def _is_iri(value: str) -> bool:
        """判断字符串是否可以视为 IRI 或前缀名。"""

        lowered = value.lower()
        return lowered.startswith(('http://', 'https://', 'urn:')) or value.startswith('_:') or ':' in value

    @staticmethod
    def _format_iri(value: str) -> str:
        """将输入规范为 SPARQL 可接受的 IRI 表达。"""

        if value.startswith('_:'):
            return value
        if value.startswith('<') and value.endswith('>'):
            return value
        lowered = value.lower()
        if lowered.startswith(('http://', 'https://', 'urn:')):
            return f"<{value}>"
        if ':' in value:
            return value
        return f"<{value}>"

    @staticmethod
    def _parse_key(key: str, fallback: Triple) -> dict[str, str]:
        """解析分组键，提取主体/谓词/对象字段。"""

        if key.startswith('s::'):
            return {'s': key.split('::', 1)[1]}
        if key.startswith('sp::'):
            _, s_val, p_val = key.split('::', 2)
            return {'s': s_val, 'p': p_val}
        if key.startswith('custom[') and ']::' in key:
            marker, rest = key.removeprefix('custom[').split(']::', 1)
            fields = marker.split(',')
            values = rest.split('::')
            mapping: dict[str, str] = {}
            for field, value in zip(fields, values[1::2], strict=False):
                mapping[field] = value
            mapping.setdefault('s', fallback.s)
            mapping.setdefault('p', fallback.p)
            if 'o' not in mapping and fallback.o:
                mapping['o'] = fallback.o
            return mapping
        return {'s': fallback.s}
