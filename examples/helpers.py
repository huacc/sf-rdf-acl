"""示例脚本共享工具：加载配置/构造不同类型的 Fuseki 客户端。"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from common.config import ConfigManager
from sf_rdf_acl import FusekiClient


def load_demo_config() -> None:
    """加载 examples/config/demo.yaml，供示例脚本直接使用。"""

    config_path = Path(__file__).resolve().parent / "config" / "demo.yaml"
    ConfigManager.load(override_path=str(config_path))


@dataclass
class DemoResponse:
    """封装示例客户端返回值。"""

    vars: List[str]
    bindings: List[Dict[str, Any]]
    turtle: str = ""
    status: int = 200


class DemoFusekiClient:
    """满足 RDFClient 协议的简化实现，用于基础示例。"""

    def __init__(
        self,
        *,
        select: Optional[DemoResponse] = None,
        construct: Optional[str] = None,
        update_status: int = 200,
    ) -> None:
        self._select = select or DemoResponse(
            vars=["s", "p", "o"],
            bindings=[],
            turtle="",
            status=200,
        )
        self._construct = construct if construct is not None else ""
        self._update_status = update_status
        self.performed_updates: list[str] = []

    async def select(
        self,
        query: str,
        *,
        timeout: int | None = 30,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        print("[DemoFusekiClient] SELECT", query.replace("\n", " "))
        return {
            "vars": list(self._select.vars),
            "bindings": list(self._select.bindings),
            "stats": {"status": self._select.status, "durationMs": 1.0},
        }

    async def construct(
        self,
        query: str,
        *,
        timeout: int | None = 30,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        print("[DemoFusekiClient] CONSTRUCT", query.replace("\n", " "))
        return {
            "turtle": self._construct or "",
            "stats": {"status": 200, "durationMs": 1.0},
        }

    async def update(
        self,
        update: str,
        *,
        timeout: int | None = 30,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        print("[DemoFusekiClient] UPDATE", update.replace("\n", " "))
        self.performed_updates.append(update)
        return {"status": self._update_status, "durationMs": 1.0}

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "backend": "demo", "dataset": "sf_demo"}


def build_fuseki_client() -> FusekiClient:
    """Create a FusekiClient wired to the loaded configuration."""

    manager = ConfigManager.current()
    rdf_cfg = manager.rdf
    security_cfg = manager.security
    auth = None
    if getattr(rdf_cfg, "auth", None) and rdf_cfg.auth.username and rdf_cfg.auth.password:
        auth = (rdf_cfg.auth.username, rdf_cfg.auth.password)

    retry_policy = (
        rdf_cfg.retries.model_dump()
        if hasattr(rdf_cfg.retries, "model_dump")
        else dict(rdf_cfg.retries)
    )
    circuit_breaker = (
        rdf_cfg.circuit_breaker.model_dump(by_alias=True)
        if hasattr(rdf_cfg.circuit_breaker, "model_dump")
        else dict(rdf_cfg.circuit_breaker)
    )

    return FusekiClient(
        endpoint=str(rdf_cfg.endpoint),
        dataset=rdf_cfg.dataset,
        auth=auth,
        trace_header=security_cfg.trace_header,
        default_timeout=rdf_cfg.timeout.default,
        max_timeout=rdf_cfg.timeout.max,
        retry_policy=retry_policy,
        circuit_breaker=circuit_breaker,
    )


@dataclass(slots=True)
class TripleRecord:
    """内存图谱中的基础三元组描述。"""

    subject: str
    predicate: str
    obj_value: str
    obj_type: str  # uri | literal | bnode
    datatype: str | None = None
    lang: str | None = None

    def to_binding(self) -> dict[str, Any]:
        """转换为 SPARQL JSON 绑定格式。"""

        cell: dict[str, Any] = {
            "type": "bnode"
            if self.obj_type == "bnode"
            else ("uri" if self.obj_type == "uri" else "literal"),
            "value": self.obj_value,
        }
        if self.datatype:
            cell["datatype"] = self.datatype
        if self.lang:
            cell["xml:lang"] = self.lang
        return cell

    def render_object(self) -> str:
        """渲染为 SPARQL 对象表达，便于与 Upsert 生成结果对齐。"""

        if self.obj_type == "uri":
            if self.obj_value.startswith("_:"):
                return self.obj_value
            if self.obj_value.startswith("<") and self.obj_value.endswith(">"):
                return self.obj_value
            if self.obj_value.startswith(("http://", "https://", "urn:")):
                return f"<{self.obj_value}>"
            return self.obj_value
        if self.obj_type == "bnode":
            return self.obj_value
        literal = _escape_for_literal(self.obj_value)
        if self.datatype:
            return f'"{literal}"^^<{self.datatype}>'
        if self.lang:
            return f'"{literal}"@{self.lang}'
        return f'"{literal}"'


class InMemoryFusekiClient:
    """轻量内存实现，用于串联示例代码的端到端流程。"""

    _DEFAULT_PREFIXES = {
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
        "prov": "http://www.w3.org/ns/prov#",
        "sf": "http://semanticforge.ai/ontologies/core#",
    }

    def __init__(self) -> None:
        self._graphs: dict[str, list[TripleRecord]] = defaultdict(list)
        self._types: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self._provenance: dict[str, list[str]] = defaultdict(list)
        self.performed_updates: list[str] = []

    async def select(
        self,
        query: str,
        *,
        timeout: int | None = 30,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """根据查询类型返回计数或图结构结果。"""

        normalized = " ".join(part.strip() for part in query.splitlines() if part.strip())
        if "COUNT" in normalized.upper():
            return self._handle_count_query(normalized)
        return self._handle_projection_query(normalized)

    async def construct(
        self,
        query: str,
        *,
        timeout: int | None = 30,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """评估简化 CONSTRUCT，生成快照所需的 Turtle 数据。"""

        graph_iri = _extract_graph_iri(query)
        subject = _extract_bind_value(query, "?__target_s")
        predicate = _extract_bind_value(query, "?__target_p")
        obj = _extract_bind_value(query, "?__target_o")
        records = self._match_records(
            graph_iri,
            (
                _parse_term(subject),
                _parse_term(predicate),
                _parse_term(obj),
            ),
        )
        ttl = self._records_to_turtle(graph_iri, records)
        return {
            "turtle": ttl,
            "stats": {"status": 200, "durationMs": 0.1},
        }

    async def update(
        self,
        update: str,
        *,
        timeout: int | None = 30,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """解释常见更新语句并更新内存存储。"""

        statement = update.strip()
        self.performed_updates.append(statement)
        upper = statement.upper()

        if upper.startswith("CREATE GRAPH"):
            graph_iri = _extract_graph_iri(statement)
            self._ensure_graph(graph_iri)
            return {"status": 200, "durationMs": 0.1}

        if upper.startswith("CLEAR GRAPH"):
            graph_iri = _extract_graph_iri(statement)
            self._graphs[graph_iri].clear()
            self._types[graph_iri].clear()
            self._provenance[graph_iri].clear()
            return {"status": 200, "durationMs": 0.1}

        if upper.startswith("ADD GRAPH"):
            source, target = _extract_two_graphs(statement)
            self._ensure_graph(source)
            self._ensure_graph(target)
            for record in self._graphs[source]:
                self._insert_record(target, record)
            for entity, values in self._types[source].items():
                self._types[target][entity].update(values)
            self._provenance[target].extend(self._provenance[source])
            return {"status": 200, "durationMs": 0.1}

        if upper.startswith("COPY GRAPH"):
            source, target = _extract_two_graphs(statement)
            # dataclass(slots=True) 没有 __dict__，显式复制字段
            self._graphs[target] = [
                TripleRecord(
                    subject=record.subject,
                    predicate=record.predicate,
                    obj_value=record.obj_value,
                    obj_type=record.obj_type,
                    datatype=record.datatype,
                    lang=record.lang,
                )
                for record in self._graphs[source]
            ]
            self._types[target] = defaultdict(set)
            for entity, values in self._types[source].items():
                self._types[target][entity].update(values)
            self._provenance[target] = list(self._provenance[source])
            return {"status": 200, "durationMs": 0.1}

        if "DELETE" in upper and "INSERT" in upper:
            graph_iri = _extract_graph_iri(statement)
            inserts = self._extract_insert_records(statement)
            for record in inserts:
                self._remove_by_subject_predicate(graph_iri, record.subject, record.predicate)
            for record in inserts:
                self._insert_record(graph_iri, record)
            return {"status": 200, "durationMs": 0.1}

        if "INSERT" in upper:
            graph_iri = _extract_graph_iri(statement)
            inserts = self._extract_insert_records(statement)
            for record in inserts:
                self._insert_record(graph_iri, record)
            return {"status": 200, "durationMs": 0.1}

        if upper.startswith("DELETE WHERE"):
            graph_iri = _extract_graph_iri(statement)
            pattern = _extract_pattern(statement)
            terms = tuple(_parse_term(part) for part in pattern)
            matched = self._match_records(graph_iri, terms)
            self._graphs[graph_iri] = [r for r in self._graphs[graph_iri] if r not in matched]
            return {"status": 200, "durationMs": 0.1}

        if upper.startswith("DROP GRAPH"):
            graph_iri = _extract_graph_iri(statement)
            self._graphs.pop(graph_iri, None)
            self._types.pop(graph_iri, None)
            self._provenance.pop(graph_iri, None)
            return {"status": 200, "durationMs": 0.1}

        raise ValueError(f"未实现的更新语句: {statement}")

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "backend": "in-memory", "dataset": "sf_demo"}

    # ---- 场景辅助 -----------------------------------------------------

    def export_graph_as_turtle(self, graph_iri: str) -> str:
        records = self._graphs.get(graph_iri, [])
        return self._records_to_turtle(graph_iri, records)

    def _handle_count_query(self, query: str) -> dict[str, Any]:
        graph_iri = _extract_graph_iri(query)
        pattern_terms = tuple(_parse_term(part) for part in _extract_pattern(query))
        matched = self._match_records(graph_iri, pattern_terms)
        return {
            "vars": ["count"],
            "bindings": [
                {
                    "count": {
                        "type": "literal",
                        "datatype": "http://www.w3.org/2001/XMLSchema#integer",
                        "value": str(len(matched)),
                    }
                }
            ],
            "stats": {"status": 200, "durationMs": 0.1},
        }

    def _handle_projection_query(self, query: str) -> dict[str, Any]:
        graph_iri = _extract_graph_iri(query)
        predicate_filter = _extract_predicate_filter(query)
        include_literals = "FILTER(ISIRI(?O))" not in query.upper()

        records: list[TripleRecord] = []
        for record in self._graphs.get(graph_iri, []):
            expanded_pred = self._expand_if_needed(record.predicate)
            if predicate_filter and expanded_pred not in predicate_filter:
                continue
            if not include_literals and record.obj_type not in {"uri", "bnode"}:
                continue
            records.append(record)

        bindings: list[dict[str, Any]] = []
        for record in records:
            binding: dict[str, Any] = {
                "s": _iri_cell(record.subject),
                "p": _iri_cell(self._expand_if_needed(record.predicate)),
                "o": record.to_binding(),
            }
            types = self._types[graph_iri].get(record.subject)
            if types:
                binding["sourceType"] = _iri_cell(next(iter(sorted(types))))
            if record.obj_type == "uri":
                target_types = self._types[graph_iri].get(record.obj_value)
                if target_types:
                    binding["targetType"] = _iri_cell(next(iter(sorted(target_types))))
            bindings.append(binding)

        return {
            "vars": ["s", "p", "o", "sourceType", "targetType"],
            "bindings": bindings,
            "stats": {"status": 200, "durationMs": 0.2, "rows": len(bindings)},
        }

    def _extract_insert_records(self, statement: str) -> list[TripleRecord]:
        graph_blocks = re.findall(
            r"GRAPH\s*<([^>]+)>\s*\{(.*?)\}",
            statement,
            flags=re.IGNORECASE | re.DOTALL,
        )
        records: list[TripleRecord] = []
        for _, block in graph_blocks:
            for line in block.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                triple = _parse_triple_line(stripped)
                if triple is None:
                    continue
                subj, pred, obj = triple
                obj_term = _parse_term(obj)
                if obj_term[0] == "rdfstar":
                    graph = _extract_graph_iri(statement)
                    self._provenance[graph].append(stripped)
                    continue
                record = TripleRecord(
                    subject=_normalize_term(subj),
                    predicate=_normalize_term(pred),
                    obj_value=_term_value(obj_term),
                    obj_type=_term_kind(obj_term),
                    datatype=_term_datatype(obj_term),
                    lang=_term_lang(obj_term),
                )
                records.append(record)
        return records

    def _insert_record(self, graph_iri: str, record: TripleRecord) -> None:
        self._ensure_graph(graph_iri)
        self._graphs[graph_iri].append(record)
        rdf_type = self._expand_if_needed("rdf:type")
        if self._expand_if_needed(record.predicate) in {rdf_type, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"} and record.obj_type == "uri":
            self._types[graph_iri][record.subject].add(record.obj_value)

    def _remove_by_subject_predicate(self, graph_iri: str, subject: str, predicate: str) -> None:
        remaining: list[TripleRecord] = []
        to_remove: list[TripleRecord] = []
        expanded = self._expand_if_needed(predicate)
        for record in self._graphs.get(graph_iri, []):
            if record.subject == subject and self._expand_if_needed(record.predicate) == expanded:
                to_remove.append(record)
            else:
                remaining.append(record)
        self._graphs[graph_iri] = remaining
        if to_remove and expanded in {
            self._expand_if_needed("rdf:type"),
            "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        }:
            self._types[graph_iri][subject].clear()

    def _match_records(
        self,
        graph_iri: str,
        terms: Sequence[tuple[str, Optional[str], Optional[str], Optional[str]]],
    ) -> list[TripleRecord]:
        subject_term, predicate_term, object_term = terms
        matches: list[TripleRecord] = []
        for record in self._graphs.get(graph_iri, []):
            if not _term_matches(subject_term, record.subject):
                continue
            if not _term_matches(predicate_term, self._expand_if_needed(record.predicate)):
                continue
            if not _object_matches(object_term, record):
                continue
            matches.append(record)
        return matches

    def _records_to_turtle(self, graph_iri: str, records: Iterable[TripleRecord]) -> str:
        lines = [f"# Graph: {graph_iri}"]
        for record in records:
            subject = _format_iri(record.subject)
            predicate = _format_iri(self._expand_if_needed(record.predicate))
            obj = record.render_object()
            lines.append(f"{subject} {predicate} {obj} .")
        return "\n".join(lines)

    def _ensure_graph(self, graph_iri: str) -> None:
        self._graphs.setdefault(graph_iri, [])
        self._types.setdefault(graph_iri, defaultdict(set))
        self._provenance.setdefault(graph_iri, [])

    def _expand_if_needed(self, term: str) -> str:
        if term.startswith(("http://", "https://", "urn:", "<", "_:")):
            return term[1:-1] if term.startswith("<") and term.endswith(">") else term
        if ":" in term:
            prefix, local = term.split(":", 1)
            base = self._DEFAULT_PREFIXES.get(prefix)
            if base:
                return base + local
        return term


def _parse_triple_line(line: str) -> tuple[str, str, str] | None:
    match = re.match(r"(.+?)\s+(.+?)\s+(.+?)\s*\.\s*$", line)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)


def _extract_graph_iri(text: str) -> str:
    match = re.search(r"GRAPH\s*<([^>]+)>", text, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"语句中缺少 GRAPH IRI: {text}")
    return match.group(1)


def _extract_two_graphs(text: str) -> tuple[str, str]:
    matches = re.findall(r"GRAPH\s*<([^>]+)>", text, flags=re.IGNORECASE)
    if len(matches) < 2:
        raise ValueError(f"语句中缺少两个 GRAPH IRI: {text}")
    return matches[0], matches[1]


def _extract_pattern(text: str) -> tuple[str, str, str]:
    match = re.search(r"GRAPH\s*<[^>]+>\s*\{\s*(.+?)\s*\}", text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError(f"无法解析三元组模式: {text}")
    triple = _parse_triple_line(match.group(1).strip())
    if triple is None:
        raise ValueError(f"三元组模式格式错误: {text}")
    return triple


def _extract_predicate_filter(query: str) -> set[str]:
    match = re.search(r"VALUES\s+\?p\s*\{([^}]+)\}", query, flags=re.IGNORECASE)
    if not match:
        return set()
    items = match.group(1).strip().split()
    normalized = set()
    for item in items:
        if item.startswith("<") and item.endswith(">"):
            normalized.add(item[1:-1])
        elif item.startswith(("http://", "https://", "urn:")):
            normalized.add(item)
        elif ":" in item:
            prefix, local = item.split(":", 1)
            base = InMemoryFusekiClient._DEFAULT_PREFIXES.get(prefix, "")
            normalized.add(base + local)
    return normalized


def _parse_term(term: str | None) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    if term is None:
        return ("var", None, None, None)
    value = term.strip()
    if not value or value.startswith("?"):
        return ("var", None, None, None)
    if value.startswith("<<") and value.endswith(">"):
        return ("rdfstar", value, None, None)
    if value.startswith("_:"):
        return ("bnode", value, None, None)
    if value.startswith("<") and ">" in value:
        return ("iri", value[1:value.index(">")], None, None)
    if value.startswith(("http://", "https://", "urn:")):
        return ("iri", value, None, None)
    if value.startswith('"'):
        literal, dtype, lang = _parse_literal(value)
        return ("literal", literal, dtype, lang)
    if ":" in value:
        prefix, local = value.split(":", 1)
        base = InMemoryFusekiClient._DEFAULT_PREFIXES.get(prefix)
        return ("iri", base + local if base else value, None, None)
    return ("iri", value, None, None)


def _normalize_term(term: str) -> str:
    stripped = term.strip()
    if stripped.startswith("<") and stripped.endswith(">"):
        return stripped[1:-1]
    return stripped


def _term_matches(term: tuple[str, Optional[str], Optional[str], Optional[str]], value: str) -> bool:
    kind, expected, _, _ = term
    if kind == "var":
        return True
    if kind in {"iri", "bnode"}:
        return expected == value or _format_iri(expected or "") == value or expected == _format_iri(value)
    return False


def _object_matches(term: tuple[str, Optional[str], Optional[str], Optional[str]], record: TripleRecord) -> bool:
    kind, expected, dtype, lang = term
    if kind == "var":
        return True
    if kind == "iri":
        return record.obj_type == "uri" and expected == record.obj_value
    if kind == "bnode":
        return record.obj_type == "bnode" and expected == record.obj_value
    if kind == "literal":
        return (
            record.obj_type == "literal"
            and expected == record.obj_value
            and (dtype is None or dtype == record.datatype)
            and (lang is None or lang == record.lang)
        )
    return False


def _term_value(term: tuple[str, Optional[str], Optional[str], Optional[str]]) -> str:
    kind, value, _, _ = term
    if kind == "literal" and value is not None:
        return value
    if value is None:
        return ""
    return value


def _term_kind(term: tuple[str, Optional[str], Optional[str], Optional[str]]) -> str:
    kind = term[0]
    if kind == "literal":
        return "literal"
    if kind == "bnode":
        return "bnode"
    return "uri"


def _term_datatype(term: tuple[str, Optional[str], Optional[str], Optional[str]]) -> str | None:
    return term[2]


def _term_lang(term: tuple[str, Optional[str], Optional[str], Optional[str]]) -> str | None:
    return term[3]


def _iri_cell(value: str) -> dict[str, Any]:
    return {"type": "uri", "value": value}


def _format_iri(value: str) -> str:
    if value.startswith("<") and value.endswith(">"):
        return value
    if value.startswith("_:"):
        return value
    if value.startswith(("http://", "https://", "urn:")):
        return f"<{value}>"
    return value


def _escape_for_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _parse_literal(text: str) -> tuple[str, str | None, str | None]:
    buf: list[str] = []
    escaped = False
    literal_end = None
    for idx, ch in enumerate(text[1:], start=1):
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            literal_end = idx
            break
        else:
            buf.append(ch)
    if literal_end is None:
        raise ValueError(f"字面量缺少结束引号: {text}")
    literal = "".join(buf)
    rest = text[literal_end + 2 :].strip()
    dtype: str | None = None
    lang: str | None = None
    if rest.startswith("^^"):
        rest = rest[2:].strip()
        if rest.startswith("<") and ">" in rest:
            dtype = rest[1 : rest.index(">")]
            rest = rest[rest.index(">") + 1 :].strip()
    if rest.startswith("@"):
        lang = rest[1:].strip()
    literal = literal.replace('\"', '"').replace("\\\\", "\\")
    return literal, dtype, lang


def _extract_bind_value(query: str, var_name: str) -> str | None:
    pattern = rf"BIND\((.+?)\s+AS\s+{re.escape(var_name)}\)"
    match = re.search(pattern, query, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip()
