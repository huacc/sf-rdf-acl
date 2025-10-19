"""图投影工具，将 RDF 查询结果转换为图结构视图。

提供 GraphJSON 和边列表等格式，方便后续算法与可视化组件使用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from common.config import ConfigManager
from common.config.settings import GraphConfig, Settings
from common.exceptions import APIError, ErrorCode
from common.logging import LoggerFactory

from ..connection.client import FusekiClient, RDFClient
from ..query.builder import SPARQLQueryBuilder
from ..query.dsl import GraphRef, QueryDSL
from ..utils import resolve_graph_iri


@dataclass(slots=True)
class ProjectionPayload:
    """图投影结果值对象。

属性：
    graph：GraphJSON 字典，例如 ``{"nodes": [], "edges": []}``。
    edgelist：边列表，例如 ``[("node1", "node2", {"predicate": "rdf:type"})]``。
    stats：统计信息，例如 ``{"rows": 128, "elapsedMs": 42}``。
    profile：使用的投影配置名称，例如 ``"default"``。
    config：合并后的配置字典，例如 ``{"limit": 500}``。
    graph_iri：命名图 IRI，例如 ``"http://example.org/graph/demo"`` 或 ``None``。
"""

    graph: dict[str, Any]
    edgelist: list[tuple[str, str, dict[str, Any]]]
    stats: dict[str, Any]
    profile: str
    config: dict[str, Any]
    graph_iri: str | None


class GraphProjectionBuilder:
    """图投影构建器。

职责：
1. 根据投影 profile 定义确定节点、边的抽取策略，支持自定义扩展。
2. 同步构建 GraphJSON 与边列表，满足算法与可视化的双重需求。
3. 支持 :class:`QueryDSL` 与 :class:`GraphRef` 两种输入来源的动态切换。
"""

    _DEFAULT_PREFIXES = {
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
        "prov": "http://www.w3.org/ns/prov#",
        "sf": "http://semanticforge.ai/ontologies/core#",
    }

    def __init__(
        self,
        *,
        client: Optional[RDFClient] = None,
        builder: Optional[SPARQLQueryBuilder] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        """初始化投影构建器。

参数：
    client：可选的 RDFClient，例如 ``FusekiClient(endpoint="http://localhost:3030", dataset="acl")``；缺省时自动构建。
    builder：可选的 SPARQL 构造器，例如 ``SPARQLQueryBuilder()``；缺省时使用默认实现。
    settings：可选的 Settings 配置，例如 ``ConfigManager.current().settings``；缺省时读取全局配置。
"""

        self._config_manager = ConfigManager.current()
        self._settings = settings or self._config_manager.settings
        self._client = client or self._create_client()
        self._builder = builder or SPARQLQueryBuilder()
        self._graph_config: GraphConfig = self._settings.graph
        self._logger = LoggerFactory.create_default_logger(__name__)

    async def project(
        self,
        source: QueryDSL | GraphRef,
        profile: str,
        *,
        config: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> ProjectionPayload:
        """执行图投影。

参数：
    source：``QueryDSL`` 或 ``GraphRef`` 实例，例如 ``QueryDSL.select("?s ?p ?o")`` 或 ``GraphRef(model="demo", version="v1", env="dev")``。
    profile：投影配置名称，例如 ``"default"``。
    config：可选覆盖参数，例如 ``{"limit": 200, "includeLiterals": True}``。
    trace_id：可选链路追踪 ID，例如 ``"trace-projection-0001"``。

返回：
    :class:`ProjectionPayload` 实例，包含 GraphJSON、边列表与统计信息。
"""

        merged_profile = self._merge_profile(profile, config)
        graph_json, edgelist, stats, graph_iri = await self._collect(
            source,
            merged_profile,
            trace_id=trace_id,
        )
        return ProjectionPayload(
            graph=graph_json,
            edgelist=edgelist,
            stats=stats,
            profile=profile,
            config=merged_profile,
            graph_iri=graph_iri,
        )

    async def to_graphjson(
        self,
        source: QueryDSL | GraphRef,
        *,
        profile: str,
        config: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """生成 GraphJSON 表示形式，并在 meta 字段写入上下文信息。

参数：
    source：``QueryDSL`` 或 ``GraphRef``，示例同 ``project``。
    profile：投影配置名称，例如 ``"default"``。
    config：可选覆盖参数，例如 ``{"limit": 500}``。
    trace_id：可选链路追踪 ID，例如 ``"trace-graphjson-0001"``。

返回：
    GraphJSON 字典，包含 ``meta.profile``、``meta.config``、``meta.graphIri`` 等信息。
"""

        payload = await self.project(source, profile, config=config, trace_id=trace_id)
        graph = dict(payload.graph)
        meta = graph.setdefault("meta", {})
        meta["profile"] = payload.profile
        meta["config"] = payload.config
        meta["graphIri"] = payload.graph_iri
        meta["stats"] = payload.stats
        return graph

    async def to_edgelist(
        self,
        source: QueryDSL | GraphRef,
        *,
        profile: str,
        config: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """返回边列表表示，便于图算法或批量导出使用。

参数：
    source：``QueryDSL`` 或 ``GraphRef``，示例同 ``project``。
    profile：投影配置名称，例如 ``"default"``。
    config：可选覆盖参数，例如 ``{"limit": 300}``。
    trace_id：可选链路追踪 ID，例如 ``"trace-edgelist-0001"``。

返回：
    边列表 ``[(source, target, {"predicate": ...})]``，字面量目标会以 ``target = None`` 返回。
"""

        payload = await self.project(source, profile, config=config, trace_id=trace_id)
        return payload.edgelist

    # ---- 内部工具方法 -----------------------------------------------------

    def _create_client(self) -> FusekiClient:
        """根据当前配置构造默认的 :class:`FusekiClient`。

返回：
    已配置完成的 ``FusekiClient`` 实例，用于执行查询与更新。
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

    async def _collect(
        self,
        source: QueryDSL | GraphRef,
        profile: dict[str, Any],
        *,
        trace_id: str | None,
    ) -> tuple[dict[str, Any], list[tuple[str, str, dict[str, Any]]], dict[str, Any], str | None]:
        """执行查询并基于 profile 构建投影数据。

参数：
    source：``QueryDSL`` 或 ``GraphRef``。
    profile：已合并的投影配置，例如 ``{"edgePredicates": ["rdf:type"], "limit": 1000}``。
    trace_id：可选链路追踪 ID，例如 ``"trace-collect-0001"``。

返回：
    元组 ``(graph_json, edgelist, stats, graph_iri)``，其中 ``graph_iri`` 可能为 ``None``。
"""

        if isinstance(source, QueryDSL):
            query = self._builder.build_select(source)
            graph_iri = None
        else:
            graph_iri = self._resolve_graph(source)
            query = self._build_graph_query(
                graph_iri=graph_iri,
                edge_predicates=profile["edgePredicates"],
                include_literals=profile.get("includeLiterals", False),
                limit=profile.get("limit", 1000),
            )
        # 向 Fuseki 发送查询并记录耗时统计
        response = await self._client.select(query, trace_id=trace_id)
        stats = response.get("stats", {})
        bindings = response.get("bindings", [])
        graph_json, edgelist, stats, graph_iri = self._build_graphjson(
            bindings=bindings,
            directed=profile.get("directed", True),
            flatten_reification=profile.get("flattenReification", True),
            graph_iri=graph_iri,
            stats=stats,
        )
        # 若要求不包含字面量，结果层面再过滤一次，避免上游桩绕过查询过滤
        if not profile.get("includeLiterals", False):
            graph_json["edges"] = [e for e in graph_json.get("edges", []) if e.get("target") is not None]
        return graph_json, edgelist, stats, graph_iri

    def _merge_profile(self, profile_name: str, override: dict[str, Any] | None) -> dict[str, Any]:
        """合并 profile 默认配置与覆盖参数。

参数：
    profile_name：配置名称，例如 ``"default"``。
    override：可选覆盖字典，例如 ``{"limit": 200}`` 或 ``None``。

返回：
    已合并的配置字典，后续用于驱动查询与转换。
"""

        profiles = self._graph_config.projection_profiles
        if profile_name not in profiles:
            raise APIError(ErrorCode.BAD_REQUEST, f"未找到投影配置：{profile_name}")
        merged = profiles[profile_name].model_dump(by_alias=True)
        if override:
            # 若 profile 指定了最大 limit，则运行时覆盖必须严格小于该上限
            if "limit" in override and merged.get("limit") is not None:
                try:
                    o = int(override.get("limit"))
                    p = int(merged.get("limit"))
                    if o >= p:
                        raise APIError(ErrorCode.BAD_REQUEST, "Limit override violates profile bound")
                except Exception:
                    raise APIError(ErrorCode.BAD_REQUEST, "Invalid limit override")
            merged.update(override)
        return merged

    def _resolve_graph(self, graph: GraphRef) -> str:
        """将 :class:`GraphRef` 解析为命名图 IRI。

参数：
    graph：命名图引用，例如 ``GraphRef(model="demo", version="v1", env="dev")``。

返回：
    非空字符串，表示命名图 IRI。
"""

        graph_iri = resolve_graph_iri(graph, self._settings)
        if not graph_iri:
            raise ValueError("无法解析命名图 IRI")
        return graph_iri

    def _build_graphjson(
        self,
        *,
        bindings: list[dict[str, Any]],
        directed: bool,
        flatten_reification: bool,
        graph_iri: str | None,
        stats: dict[str, Any],
    ) -> tuple[dict[str, Any], list[tuple[str, str, dict[str, Any]]], dict[str, Any], str | None]:
        """将 SPARQL 绑定结果转换为 GraphJSON、边列表与统计数据。

参数：
    bindings：SPARQL 结果行列表，例如 ``[{"s": {...}, "p": {...}, "o": {...}}]``。
    directed：布尔值，指示图是否有向，例如 ``True``。
    flatten_reification：布尔值，是否展开再ification 结构，例如 ``True``。
    graph_iri：命名图 IRI 或 ``None``。
    stats：统计信息字典，将被就地更新节点、边数量。

返回：
    元组 ``(graph_json, edgelist, stats, graph_iri)``。
"""

        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        edgelist: list[tuple[str, str, dict[str, Any]]] = []

        for binding in bindings:
            subj = self._extract_term(binding, "s")
            pred = self._extract_term(binding, "p")
            obj = self._extract_term(binding, "o")
            source_type = self._extract_term(binding, "sourceType")
            target_type = self._extract_term(binding, "targetType")

            if not subj or not pred or not obj:
                continue

            source_id = subj["value"]
            predicate_value = pred["value"]
            target_id = obj["value"]

            # 维护节点缓存，聚合类型信息供前端渲染
            node_entry = nodes.setdefault(source_id, {"id": source_id, "types": set()})
            if source_type:
                node_entry["types"].add(source_type["value"])

            if obj["type"] != "literal":
                target_entry = nodes.setdefault(target_id, {"id": target_id, "types": set()})
                if target_type:
                    target_entry["types"].add(target_type["value"])

            edge_payload: dict[str, Any] = {
                "source": source_id,
                "target": None if obj["type"] == "literal" else target_id,
                "predicate": predicate_value,
            }
            if obj["type"] == "literal":
                edge_payload["literal"] = obj["value"]
                edge_payload["datatype"] = obj.get("datatype")
                edge_payload["lang"] = obj.get("lang")
            edges.append(edge_payload)

            if edge_payload["target"] is not None:
                edgelist.append(
                    (
                        edge_payload["source"],
                        edge_payload["target"],
                        {"predicate": predicate_value},
                    )
                )

        for node in nodes.values():
            node["types"] = sorted(node["types"]) if node["types"] else []

        graph_json = {
            "directed": directed,
            "nodes": list(nodes.values()),
            "edges": edges,
        }
        stats.update({"nodes": len(nodes), "edges": len(edgelist)})
        return graph_json, edgelist, stats, graph_iri

    def _build_graph_query(
        self,
        graph_iri: str,
        edge_predicates: list[str],
        include_literals: bool,
        limit: int,
    ) -> str:
        """根据投影配置生成针对命名图的 SELECT 查询语句。

参数：
    graph_iri：命名图 IRI，例如 ``"http://example.org/graph/demo"``。
    edge_predicates：谓词列表，例如 ``["rdf:type", "sf:relatedTo"]``。
    include_literals：布尔值，``True`` 时保留字面量目标。
    limit：整数限制，最小值为 1，例如 ``500``。

返回：
    可直接执行的 SPARQL 查询字符串。
"""

        prefixes = dict(self._DEFAULT_PREFIXES)
        for term in edge_predicates:
            if ':' in term:
                prefix, _ = term.split(':', 1)
                if prefix not in prefixes:
                    raise APIError(ErrorCode.BAD_REQUEST, f"未知前缀：{prefix}")

        prefix_block = "\n".join(f"PREFIX {k}: <{v}>" for k, v in sorted(prefixes.items()))
        filter_clause = ""
        if edge_predicates:
            formatted = " ".join(self._format_term(term) for term in edge_predicates)
            filter_clause = f"    VALUES ?p {{ {formatted} }}"

        literal_filter = ""
        if not include_literals:
            literal_filter = "    FILTER(isIRI(?o))"

        lines = [
            prefix_block,
            "SELECT ?s ?p ?o ?sourceType ?targetType WHERE {",
            f"  GRAPH <{graph_iri}> {{",
            "    ?s ?p ?o .",
            "    OPTIONAL { ?s rdf:type ?sourceType . }",
            "    OPTIONAL { ?o rdf:type ?targetType . }",
        ]
        if filter_clause:
            lines.append(filter_clause)
        if literal_filter:
            lines.append(literal_filter)
        lines.extend([
            "  }",
            "}",
            f"LIMIT {max(1, limit)}",
        ])
        return "\n".join(lines)

    def _extract_term(self, binding: dict[str, Any], key: str) -> dict[str, Any] | None:
        """从查询结果绑定中提取指定键的取值描述。

参数：
    binding：单行绑定字典，例如 ``{"s": {"type": "uri", "value": "http://example.org"}}``。
    key：要提取的键名，例如 ``"s"`` 或 ``"sourceType"``。

返回：
    包含 ``type``/``value`` 及可选 ``lang``、``datatype`` 的字典；若不存在则返回 ``None``。
"""

        cell = binding.get(key)
        if not cell:
            return None
        value = cell.get("value")
        if value is None:
            return None
        result = {
            "type": cell.get("type", "literal"),
            "value": value,
        }
        if "xml:lang" in cell:
            result["lang"] = cell.get("xml:lang")
        if "datatype" in cell:
            result["datatype"] = cell.get("datatype")
        return result

    def _expand_to_iri(self, term: str) -> str:
        """将 ``prefix:local`` 表达式展开为完整 IRI。

参数：
    term：待转换的字符串，例如 ``"rdf:type"`` 或 ``"sf:edge"``。

返回：
    完整的 IRI 字符串。
"""

        if term.startswith(("http://", "https://", "urn:")):
            return term
        if term.startswith("<") and term.endswith(">"):
            return term[1:-1]
        if ':' in term:
            prefix, local = term.split(':', 1)
            base = self._DEFAULT_PREFIXES.get(prefix)
            if base is None:
                raise APIError(ErrorCode.BAD_REQUEST, f"未知前缀：{prefix}")
            return base + local
        return term

    def _format_term(self, term: str) -> str:
        """格式化谓词取值便于拼入 VALUES 子句。

参数：
    term：待格式化的字符串，例如 ``"rdf:type"`` 或 ``"http://example.org/p"``。

返回：
    适合放入 ``VALUES`` 子句的字符串，必要时会自动包裹 ``<>``。
"""

        if term.startswith("<") and term.endswith(">"):
            return term
        if term.startswith("http://") or term.startswith("https://") or term.startswith("urn:"):
            return f"<{term}>"
        return term
