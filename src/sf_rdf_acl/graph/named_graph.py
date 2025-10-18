"""命名图管理工具。

封装创建、清空、合并、快照等常见操作，统一使用平台配置连接 Fuseki 服务。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from common.config import ConfigManager
from common.config.settings import Settings
from common.exceptions import ExternalServiceError
from common.logging import LoggerFactory

from sf_rdf_acl.connection.client import FusekiClient, RDFClient
from sf_rdf_acl.query.dsl import GraphRef
from sf_rdf_acl.utils import resolve_graph_iri


class NamedGraphManager:
    """命名图管理器。

主要职责：
1. 基于平台配置解析 :class:`GraphRef`，获得可直接访问的命名图 IRI。
2. 提供 create/clear/conditional_clear/merge/snapshot 等高频操作。
3. 统一透传 ``trace_id`` 以便日志排查与链路追踪。
"""

    def __init__(
        self,
        *,
        client: Optional[RDFClient] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        """初始化管理器。

参数：
    client：可选的 RDF 客户端实例，例如 ``FusekiClient(endpoint="http://localhost:3030", dataset="acl")``；缺省时自动根据配置创建。
    settings：可选的 ``Settings`` 配置快照，例如 ``ConfigManager.current().settings``；缺省时读取当前全局配置。
"""

        self._config_manager = ConfigManager.current()
        self._settings = settings or self._config_manager.settings
        self._client = client or self._create_client()
        self._logger = LoggerFactory.create_default_logger(__name__)

    async def create(self, graph: GraphRef, *, trace_id: str) -> dict[str, Any]:
        """创建命名图。

参数：
    graph：命名图引用，例如 ``GraphRef(model="demo", version="v1", env="dev")``。
    trace_id：链路追踪 ID，例如 ``"trace-20250101-0001"``。

返回：
    包含 ``graph``（命名图 IRI）和 ``status``（``"created"`` 或 ``"exists"``）的字典。
"""

        graph_iri = self._resolve_graph(graph)
        try:
            await self._client.update(f"CREATE GRAPH <{graph_iri}>", trace_id=trace_id)
            status = "created"
        except ExternalServiceError as exc:
            if "already" in str(exc).lower():
                status = "exists"
                self._logger.debug("命名图已存在: %s", graph_iri)
            else:
                raise
        return {"graph": graph_iri, "status": status}

    async def clear(self, graph: GraphRef, *, trace_id: str) -> dict[str, Any]:
        """清空命名图中的全部三元组。

参数：
    graph：命名图引用，例如 ``GraphRef(model="demo", version="v1", env="dev")``。
    trace_id：链路追踪 ID，例如 ``"trace-20250101-0002"``。

返回：
    包含 ``graph`` 字段的字典，用于指明被清空的命名图 IRI。
"""

        graph_iri = self._resolve_graph(graph)
        await self._client.update(f"CLEAR GRAPH <{graph_iri}>", trace_id=trace_id)
        return {"graph": graph_iri}

    async def conditional_clear(
        self,
        graph: GraphRef,
        *,
        filters: dict[str, Any] | None,
        dry_run: bool,
        trace_id: str,
    ) -> dict[str, Any]:
        """按条件删除命名图数据，可选择仅预览。

参数：
    graph：目标命名图引用，例如 ``GraphRef(model="demo", version="v1", env="sandbox")``。
    filters：三元组过滤条件字典，键支持 ``subject``/``predicate``/``object`` 或 ``s``/``p``/``o``；例如 ``{"subject": "http://example.org/user/1"}`` 或 ``{"object": {"type": "literal", "value": "active", "lang": "zh"}}``。
    dry_run：布尔值，``True`` 表示仅统计命中数量不执行删除，``False`` 表示真正删除。
    trace_id：链路追踪 ID，例如 ``"trace-2025-10-18"``。

返回：
    字典，包含 ``graph``（命名图 IRI）、``matched``（命中数量）、``executed``（是否执行删除）和 ``pattern``（生成的三元组模式）。
"""

        graph_iri = self._resolve_graph(graph)
        pattern = self._build_triple_pattern(filters or {})
        matched = await self._count_matching(graph_iri, pattern, trace_id)
        executed = False
        if not dry_run and matched > 0:
            # 基于匹配结果拼装 DELETE 更新语句，仅在命中数据时执行删除
            update = self._compose_delete_query(graph_iri, pattern)
            await self._client.update(update, trace_id=trace_id)
            executed = True
        return {
            "graph": graph_iri,
            "matched": matched,
            "executed": executed,
            "pattern": pattern,
        }

    async def merge(self, source: GraphRef, target: GraphRef, *, trace_id: str) -> dict[str, Any]:
        """将源命名图的数据追加到目标命名图。

参数：
    source：源图引用，例如 ``GraphRef(model="demo", version="v1", env="dev")``。
    target：目标图引用，例如 ``GraphRef(model="demo", version="v1", env="prod")``。
    trace_id：链路追踪 ID，例如 ``"trace-merge-0001"``。

返回：
    字典，包含 ``source`` 和 ``target`` 两个图的 IRI。
"""

        source_iri = self._resolve_graph(source)
        target_iri = self._resolve_graph(target)
        await self._client.update(f"ADD GRAPH <{source_iri}> TO GRAPH <{target_iri}>", trace_id=trace_id)
        return {"source": source_iri, "target": target_iri}

    async def snapshot(self, graph: GraphRef, *, trace_id: str) -> dict[str, Any]:
        """创建命名图快照。

参数：
    graph：需要快照的命名图引用，例如 ``GraphRef(model="demo", version="v1", env="dev", scenario_id="s01")``。
    trace_id：链路追踪 ID，例如 ``"trace-snapshot-20251018"``。

返回：
    字典，包含原始图 IRI（``graph``）、快照标识（``snapshotId``）以及快照图 IRI（``snapshotGraph``）。
"""

        graph_iri = self._resolve_graph(graph)
        snapshot_id, snapshot_iri = self._compose_snapshot(graph)
        await self._client.update(f"COPY GRAPH <{graph_iri}> TO GRAPH <{snapshot_iri}>", trace_id=trace_id)
        return {"graph": graph_iri, "snapshotId": snapshot_id, "snapshotGraph": snapshot_iri}

    # ---- 内部工具方法 -----------------------------------------------------

    async def _count_matching(self, graph_iri: str, pattern: str, trace_id: str) -> int:
        """统计命名图中与指定模式匹配的三元组数量。

参数：
    graph_iri：命名图 IRI 字符串，例如 ``"http://example.org/graph/demo"``。
    pattern：SPARQL 三元组模式字符串，例如 ``"?s ?p ?o ."``。
    trace_id：链路追踪 ID，例如 ``"trace-clear-0001"``。

返回：
    匹配的三元组数量，返回值为非负整数。
"""

        query = (
            "SELECT (COUNT(*) AS ?count) WHERE {\n"
            f"  GRAPH <{graph_iri}> {{ {pattern} }}\n"
            "}"
        )
        raw = await self._client.select(query, trace_id=trace_id)
        bindings = raw.get("bindings", [])
        if not bindings:
            return 0
        row = bindings[0]
        cell = row.get("count")
        if cell is None and row:
            # 兼容 Fuseki 可能返回非标准字段名的情况，回退读取首列值
            cell = next(iter(row.values()))
        try:
            return int((cell or {}).get("value", 0))
        except (TypeError, ValueError, AttributeError):
            return 0

    def _compose_delete_query(self, graph_iri: str, pattern: str) -> str:
        """拼接 ``WITH/DELETE/WHERE`` 语句，为条件清理生成最终 SPARQL 更新语句。

参数：
    graph_iri：命名图 IRI，例如 ``"http://example.org/graph/demo"``。
    pattern：三元组模式字符串，例如 ``"?s ?p ?o ."``。

返回：
    可直接执行的 SPARQL 更新语句字符串。
"""

        return (
            f"WITH <{graph_iri}>\n"
            "DELETE {\n"
            f"  {pattern}\n"
            "}\n"
            "WHERE {\n"
            f"  {pattern}\n"
            "}"
        )

    def _build_triple_pattern(self, filters: dict[str, Any]) -> str:
        """根据过滤条件构造 SPARQL 三元组模式。

参数：
    filters：过滤条件字典，例如 ``{"subject": "?s", "predicate": "rdf:type", "object": {"type": "literal", "value": "active"}}``。

返回：
    形如 ``"?s rdf:type "active" ."`` 的三元组模式字符串。
"""

        subject_value = filters.get("subject", filters.get("s"))
        predicate_value = filters.get("predicate", filters.get("p"))
        object_value = filters.get("object", filters.get("o"))
        subject = self._format_term(subject_value, var_name="?s", allow_literal=False)
        predicate = self._format_term(predicate_value, var_name="?p", allow_literal=False)
        obj = self._format_term(object_value, var_name="?o", allow_literal=True)
        return f"{subject} {predicate} {obj} ."

    def _format_term(self, value: Any | None, *, var_name: str, allow_literal: bool) -> str:
        """将任意取值转换为合法的 SPARQL 术语。

参数：
    value：需要格式化的取值，例如 ``"http://example.org/id/1"``、``"?s"`` 或 ``{"type": "literal", "value": "active"}``。
    var_name：缺省时使用的变量名，例如 ``"?s"``。
    allow_literal：布尔值，``True`` 允许字面量，``False`` 仅允许 IRI 或变量。

返回：
    可直接拼接入 SPARQL 的术语字符串。
"""

        if value is None:
            return var_name
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed.startswith("?"):
                return trimmed
            if self._is_iri(trimmed):
                return self._format_iri(trimmed)
            if allow_literal:
                literal = self._escape_literal(trimmed)
                return f'"{literal}"'
            raise ValueError(f"{var_name} 必须是合法的 IRI 表达式：{value}")
        if isinstance(value, dict):
            term_type = value.get("type") or value.get("kind")
            raw_value = value.get("value")
            if term_type in {"iri", "uri"} and raw_value is not None:
                return self._format_iri(str(raw_value))
            if term_type == "literal" and raw_value is not None and allow_literal:
                literal = self._escape_literal(str(raw_value))
                datatype = value.get("datatype")
                lang = value.get("lang") or value.get("language")
                if datatype:
                    return f'"{literal}"^^<{datatype}>'
                if lang:
                    return f'"{literal}"@{lang}'
                return f'"{literal}"'
        if allow_literal:
            literal = self._escape_literal(str(value))
            return f'"{literal}"'
        raise ValueError("object 参数必须提供合法的 IRI 或字面量描述")

    @staticmethod
    def _format_iri(value: str) -> str:
        """格式化为合法的 IRI 表达式。

参数：
    value：原始 IRI 字符串，例如 ``"http://example.org/id/1"`` 或 ``"rdf:type"``。

返回：
    符合 SPARQL 语法的 IRI 表达形式。
"""

        if value.startswith("<") and value.endswith(">"):
            return value
        if value.startswith("_:"):
            return value
        if NamedGraphManager._is_prefixed(value):
            return value
        return f"<{value}>"

    @staticmethod
    def _is_prefixed(value: str) -> bool:
        """判断字符串是否满足 ``prefix:local`` 形式。

参数：
    value：待检查的字符串，例如 ``"rdf:type"``。

返回：
    ``True`` 表示匹配前缀形式，否则为 ``False``。
"""

        if ':' not in value:
            return False
        prefix, rest = value.split(':', 1)
        if rest.startswith('//'):
            return False
        return prefix.isidentifier()

    @staticmethod
    def _is_iri(value: str) -> bool:
        """粗略判断值是否可以视作 IRI。

参数：
    value：待检查的字符串，例如 ``"http://example.org/id/1"`` 或 ``"urn:uuid:1234"``。

返回：
    ``True`` 或 ``False``。
"""

        lowered = value.lower()
        return value.startswith("<") or lowered.startswith(("http://", "https://", "urn:")) or ':' in value

    @staticmethod
    def _escape_literal(value: str) -> str:
        """转义反斜杠与引号，避免破坏 SPARQL 字面量。

参数：
    value：原始字面量内容，例如 ``He said "hello"``。

返回：
    经过转义的字符串，可直接包裹在引号中使用。
"""

        return value.replace('\\', '\\\\').replace('"', '\\"')

    def _create_client(self) -> FusekiClient:
        """根据当前配置构造默认的 :class:`FusekiClient`。

返回：
    配置好的 ``FusekiClient`` 实例，可直接执行查询或更新。
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

    def _resolve_graph(self, graph: GraphRef) -> str:
        """将 :class:`GraphRef` 解析为命名图 IRI。

参数：
    graph：命名图引用，例如 ``GraphRef(model="demo", version="v1", env="dev")``。

返回：
    非空字符串，表示解析后的命名图 IRI。
"""

        graph_iri = resolve_graph_iri(graph, self._settings)
        if not graph_iri:
            raise ValueError("无法解析命名图 IRI")
        return graph_iri

    def _compose_snapshot(self, graph: GraphRef) -> tuple[str, str]:
        """根据命名图模板生成快照 ID 与 IRI。

参数：
    graph：命名图引用，例如 ``GraphRef(model="demo", version="v1", env="dev", scenario_id="s01")``。

返回：
    二元组 ``(snapshot_id, snapshot_iri)``，例如 ``("snapshot-20250101010101", "http://example.org/graph/snapshots/demo")``。
"""

        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        snapshot_id = f"snapshot-{timestamp}"
        snapshot_iri = self._settings.rdf.naming.snapshot_format.format(
            model=graph.model or "default",
            version=graph.version or "v1",
            env=graph.env or self._settings.app.env,
            ts=timestamp,
        )
        if graph.scenario_id:
            snapshot_iri = f"{snapshot_iri}:scenario:{graph.scenario_id}"
        return snapshot_id, snapshot_iri
