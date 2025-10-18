"""RDF* 溯源写入工具模块。

负责将业务生成的 RDF* 溯源三元组封装为 SPARQL Update 语句写入 Fuseki，并复用平台配置。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from common.config import ConfigManager
from common.config.settings import Settings
from common.logging import LoggerFactory

from ..connection.client import FusekiClient, RDFClient
from ..query.dsl import GraphRef
from ..transaction.upsert import Provenance, Triple
from ..utils import resolve_graph_iri


class ProvenanceService:
    """RDF* 溯源写入服务。

    职责：
    1. 基于平台 Settings 解析 GraphRef，定位目标命名图 IRI。
    2. 将 Triple 与 Provenance 数据转换为 RDF* 片段。
    3. 构造 INSERT DATA 语句并通过 Fuseki 执行。
    4. 支持附加业务元数据并自动生成 UTC 时间戳。
    """

    _PREFIXES = {
        "prov": "http://www.w3.org/ns/prov#",
        "sf": "http://semanticforge.ai/ontologies/core#",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
    }

    def __init__(
        self,
        *,
        client: Optional[RDFClient] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        """初始化服务。

        参数：
            client：可选的 RDFClient 实例，例如 ``FusekiClient(endpoint="http://localhost:3030", dataset="acl")``；缺省时依据配置自动创建。
            settings：可选的 Settings 快照，例如 ``ConfigManager.current().settings``；缺省时读取当前全局配置。
        """

        self._config_manager = ConfigManager.current()
        self._settings = settings or self._config_manager.settings
        self._client = client or self._create_client()
        self._logger = LoggerFactory.create_default_logger(__name__)

    async def annotate(
        self,
        graph: GraphRef,
        triples: list[Triple],
        provenance: Provenance,
        *,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """写入 RDF* 溯源信息并返回执行摘要。

        参数：
            graph：目标命名图引用，例如 ``GraphRef(model="demo", version="v1", env="dev")``。
            triples：需要写入的三元组列表，例如 ``[Triple(s=":s1", p="rdf:type", o=":c1")]``，不能为空。
            provenance：溯源元数据对象，例如 ``Provenance(evidence="手动导入", confidence=0.95)``。
            trace_id：可选链路追踪 ID，例如 ``"trace-provenance-0001"``。
            metadata：可选扩展字典，例如 ``{"operator": "alice", "batchId": "20251018"}``。

        返回：
            字典，包含 ``graph``（命名图 IRI）、``statements``（写入的 RDF* 片段列表）和 ``count``（片段数量）。

        异常：
            ValueError：当 ``triples`` 为空或无法解析 ``graph`` 时抛出。
        """

        # 校验输入，避免发送空的 INSERT 语句
        if not triples:
            raise ValueError("溯源写入至少需要一条三元组")

        graph_iri = resolve_graph_iri(graph, self._settings)
        if not graph_iri:
            raise ValueError("无法解析目标命名图 IRI")

        # 将业务三元组转换为 RDF* 片段列表，便于后续统一写入
        statements = list(self._build_statements(triples, provenance, metadata=metadata))
        # 拼接 INSERT DATA 语句并提交给 Fuseki 执行
        sparql = self._render_insert(graph_iri, statements)
        await self._client.update(sparql, trace_id=trace_id)

        return {
            "graph": graph_iri,
            "statements": statements,
            "count": len(statements),
        }

    # ---- 内部工具方法 -----------------------------------------------------

    def _create_client(self) -> FusekiClient:
        """根据当前配置构造默认的 FusekiClient。

        返回：
            配置完成的 ``FusekiClient`` 实例，可直接执行查询或更新。
        """

        rdf = self._settings.rdf
        security = self._settings.security
        auth_tuple: tuple[str, str] | None = None
        if rdf.auth.username and rdf.auth.password:
            auth_tuple = (rdf.auth.username, rdf.auth.password)
        retry_policy = {
            "max_attempts": rdf.retries.max_attempts,
            "backoff_seconds": rdf.retries.backoff_seconds,
            "backoff_multiplier": rdf.retries.backoff_multiplier,
            "jitter_seconds": rdf.retries.jitter_seconds or 0.0,
        }
        breaker_policy = rdf.circuit_breaker.model_dump(by_alias=True)
        return FusekiClient(
            endpoint=str(rdf.endpoint),
            dataset=rdf.dataset,
            auth=auth_tuple,
            trace_header=security.trace_header,
            default_timeout=rdf.timeout.default,
            max_timeout=rdf.timeout.max,
            retry_policy=retry_policy,
            circuit_breaker=breaker_policy,
        )

    def _build_statements(
        self,
        triples: Iterable[Triple],
        provenance: Provenance,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Iterable[str]:
        """生成 RDF* 溯源片段。

        参数：
            triples：三元组可迭代对象，例如 ``[Triple(s=":s1", p=":p1", o=":o1")]``。
            provenance：溯源配置，例如 ``Provenance(evidence="API 导入", confidence=0.8, source="http://example.org/source")``。
            metadata：可选扩展字典，例如 ``{"operator": "alice", "retry": False}``。

        返回：
            逐条产出的 RDF* 语句字符串迭代器。
        """

        # 统一使用 UTC 时间戳，确保不同环境间的一致性
        timestamp = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
        extra = metadata or {}

        # 遍历每条业务三元组，逐条生成对应的 RDF* 片段
        for triple in triples:
            fragment = self._format_fragment(triple)
            yield f'{fragment} prov:generatedAtTime "{timestamp}"^^xsd:dateTime .'
            # 根据溯源属性追加可选的证据、置信度与来源信息
            if provenance.evidence:
                evidence = self._escape_literal(provenance.evidence)
                yield f'{fragment} sf:evidence "{evidence}" .'
            if provenance.confidence is not None:
                confidence = f"{provenance.confidence:.6f}".rstrip("0").rstrip(".")
                yield f'{fragment} sf:confidence "{confidence}"^^xsd:decimal .'
            if provenance.source:
                source_term = self._format_possible_iri(provenance.source)
                yield f"{fragment} prov:wasDerivedFrom {source_term} ."
            # 追加调用方提供的扩展键值对，自动处理谓词与对象格式
            for key, value in extra.items():
                predicate = self._format_extra_predicate(key)
                object_term = (
                    self._format_possible_iri(value)
                    if isinstance(value, str)
                    else self._format_extra_literal(value)
                )
                yield f"{fragment} {predicate} {object_term} ."

    def _render_insert(self, graph_iri: str, statements: list[str]) -> str:
        """拼装 INSERT DATA 语句。

        参数：
            graph_iri：目标命名图 IRI，例如 ``"http://example.org/graph/demo"``。
            statements：RDF* 片段列表，例如 ``["<<...>> prov:generatedAtTime ..."]``。

        返回：
            可直接发送给 Fuseki 的 SPARQL Update 字符串。
        """

        # 声明常用前缀，保证生成的 SPARQL 语句易读且复用配置缩写
        prefix_block = "\n".join(f"PREFIX {prefix}: <{iri}>" for prefix, iri in sorted(self._PREFIXES.items()))
        body = "\n  ".join(statements)
        lines = [
            prefix_block,
            "INSERT DATA {",
            f"  GRAPH <{graph_iri}> {{",
            f"  {body}",
            "  }",
            "}",
        ]
        return "\n".join(lines)

    def _format_fragment(self, triple: Triple) -> str:
        """将三元组转换为 RDF* 片段 ``<<s p o>>``。

        参数：
            triple：单条三元组，例如 ``Triple(s=":s1", p=":p1", o=":o1")``。

        返回：
            RDF* 片段字符串。
        """

        subject = self._format_iri(triple.s)
        predicate = self._format_iri(triple.p)
        obj = self._format_object(triple)
        return f"<<{subject} {predicate} {obj}>>"

    def _format_iri(self, value: str) -> str:
        """规范化 IRI 或前缀形式的表示。

        参数：
            value：原始 IRI 字符串，例如 ``"http://example.org/id/1"`` 或 ``"rdf:type"``。

        返回：
            可直接出现在 SPARQL 中的 IRI 表达。
        """

        if value.startswith("_:"):
            return value
        if value.startswith("<") and value.endswith(">"):
            return value
        lowered = value.lower()
        if lowered.startswith(("http://", "https://", "urn:")):
            return f"<{value}>"
        if ':' in value:
            return value
        return f"<{value}>"

    def _format_possible_iri(self, value: str) -> str:
        """根据内容判断是否格式化为 IRI。

        参数：
            value：原始字符串，例如 ``"http://example.org/source"`` 或 ``"人工导入"``。

        返回：
            若为 IRI 则返回 IRI 表达，否则返回带引号的字面量。
        """

        if value.startswith(("http://", "https://", "urn:")) or ':' in value:
            return self._format_iri(value)
        literal = self._escape_literal(value)
        return f'"{literal}"'

    def _format_object(self, triple: Triple) -> str:
        """格式化三元组的对象部分。

        参数：
            triple：包含对象取值的三元组，例如 ``Triple(o="2025-10-18", dtype="http://www.w3.org/2001/XMLSchema#date")``。

        返回：
            可写入 SPARQL 的对象表达字符串。
        """

        # 优先处理显式数据类型，其次是语言标签与 IRI 判断
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

    def _format_extra_predicate(self, key: str) -> str:
        """将业务字段名转换为合法谓词。

        参数：
            key：扩展字段名，例如 ``"operator"`` 或 ``"sf:batchId"``。

        返回：
            可用于 SPARQL 的谓词字符串。
        """
        # 允许调用方直接传入带前缀的谓词，避免重复格式化
        if ':' in key:
            return key
        # 其余情况按字母数字保留，其它符号替换为下划线并挂载 sf: 命名空间
        safe_key = ''.join(ch if ch.isalnum() else '_' for ch in key)
        return f"sf:{safe_key}"

    def _format_extra_literal(self, value: Any) -> str:
        """将扩展字段值转换为字面量。

        参数：
            value：扩展字段值，例如 ``True``、``3.14`` 或 ``"2025-10-18"``。

        返回：
            对应的 SPARQL 字面量字符串。
        """

        # 按布尔、数值与通用字符串的优先级转换扩展字段
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        literal = self._escape_literal(str(value))
        return f'"{literal}"'

    @staticmethod
    def _escape_literal(value: str) -> str:
        """转义字面量中的反斜杠和引号。

        参数：
            value：待处理字符串，例如 ``He said "hello"``。

        返回：
            已转义的字符串。
        """

        return value.replace('\\', '\\\\').replace('"', '\\"')

    @staticmethod
    def _is_iri(value: str) -> bool:
        """判断字符串是否可视为 IRI 或前缀写法。

        参数：
            value：待检查的字符串，例如 ``"http://example.org/id/1"``。

        返回：
            ``True`` 表示可当作 IRI，否则为 ``False``。
        """

        lowered = value.lower()
        return lowered.startswith(("http://", "https://", "urn:")) or value.startswith("_:") or ':' in value
