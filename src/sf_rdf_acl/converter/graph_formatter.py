"""RDF 图数据格式化工具。

本模块提供将 Turtle 文本转换为多种输出格式的能力，包括：
- "turtle"：原样透传
- "json-ld"：使用 rdflib 进行 JSON‑LD 序列化，并支持自定义 ``@context``
- "simplified-json"：面向前端/可视化的简化 JSON 结构（节点/边/统计）

注意：为保证兼容性，保留 ``to_turtle`` 方法用于最简单的透传场景。
"""
from __future__ import annotations

from typing import Any, Literal

from common.logging import LoggerFactory
from rdflib import Graph as RDFGraph
from rdflib import Literal as RDFLiteral
from rdflib import RDF, RDFS, URIRef
import json


# 输出格式类型约束
FormatType = Literal["turtle", "json-ld", "simplified-json"]


class GraphFormatter:
    """图数据格式化与转换帮助类。

    功能：
    - ``format_graph``：根据 ``format_type`` 将 Turtle 文本转换为目标格式；
    - ``to_turtle``：与历史行为兼容的透传方法；

    线程安全：
    - 本类无共享可变状态，方法为纯函数式（除日志外），可在并发环境中安全复用。
    """

    def __init__(self) -> None:
        """初始化格式化器。

        无参数；创建模块级默认日志器用于调试与故障排查。
        """

        self._logger = LoggerFactory.create_default_logger(__name__)

    def to_turtle(self, graph_ttl: str) -> str:
        """将传入的 Turtle 文本原样返回（历史兼容）。

        参数:
            graph_ttl (str): Turtle 字符串（通常来自 Fuseki 的 CONSTRUCT 结果）。

        返回:
            str: 与 ``graph_ttl`` 一致的文本。
        """

        return graph_ttl

    def format_graph(
        self,
        turtle_data: str,
        *,
        format_type: FormatType = "turtle",
        context: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        """将 Turtle 文本格式化为指定目标格式。

        参数:
            turtle_data (str): Turtle 格式的 RDF 数据文本。
            format_type (Literal["turtle", "json-ld", "simplified-json"]): 目标格式类型。
            context (dict[str, Any] | None): 当 ``format_type="json-ld"`` 时可选的自定义
                ``@context`` 映射，键应为前缀或简名，值为 IRI 或映射对象。

        返回:
            str | dict[str, Any]:
                - 当 ``format_type="turtle"`` 时返回 ``str``；
                - 当 ``format_type="json-ld"`` 或 ``"simplified-json"`` 时返回 ``dict``。

        异常:
            ValueError: 当 ``format_type`` 不被支持时抛出。
        """

        if format_type == "turtle":
            return turtle_data

        # 解析 Turtle 为 RDFLib Graph
        graph = RDFGraph()
        graph.parse(data=turtle_data, format="turtle")

        if format_type == "json-ld":
            return self._to_jsonld(graph, context)
        if format_type == "simplified-json":
            return self._to_simplified_json(graph)
        raise ValueError(f"Unsupported format: {format_type}")

    # ----------------------------
    # 内部实现：JSON-LD 与简化 JSON
    # ----------------------------
    def _to_jsonld(self, graph: RDFGraph, context: dict[str, Any] | None) -> dict[str, Any]:
        """将 RDFLib Graph 转换为 JSON‑LD 数据结构。

        参数:
            graph (RDFGraph): 解析后的 RDF 图。
            context (dict[str, Any] | None): 自定义 ``@context`` 映射；``None`` 表示使用默认。

        返回:
            dict[str, Any]: JSON‑LD 对象，若提供 ``context`` 则会注入 ``@context`` 键。
        """

        jsonld_str = graph.serialize(format="json-ld")
        # rdflib 返回 str；出于健壮性允许 bytes → str
        if isinstance(jsonld_str, bytes):
            jsonld_str = jsonld_str.decode("utf-8")
        jsonld_data = json.loads(jsonld_str)
        # rdflib 在某些情形下直接返回顶层 list（expanded form），为便于消费统一包裹到 @graph
        if isinstance(jsonld_data, list):
            wrapped: dict[str, Any] = {"@graph": jsonld_data}
            if context:
                wrapped["@context"] = context
            return wrapped
        if context:
            jsonld_data["@context"] = context
        return jsonld_data

    def _to_simplified_json(self, graph: RDFGraph) -> dict[str, Any]:
        """将 RDFLib Graph 转换为简化 JSON（GraphJSON 风格）。

        结构示例:
            {
              "nodes": [
                {"id": "uri1", "type": "Class", "label": "...", "labels": {"en": "..."}, "properties": {...}},
                ...
              ],
              "edges": [
                {"source": "uri1", "target": "uri2", "predicate": "..."},
                ...
              ],
              "stats": {"node_count": 2, "edge_count": 1}
            }

        节点策略:
        - 所有出现为主语的 URI 都会成为节点；
        - 对象位为 URI 的也会成为节点；
        - ``rdf:type`` 的对象 URI 作为该节点的 ``type``（若出现多个取最后一个，同时保留完整列表到 ``types``）；
        - ``rdfs:label``：
            - ``label`` 字段保存一个默认显示字符串（优先无语言标签，或首个见到的标签）；
            - ``labels`` 字段为语言 → 文本的映射，支持多语言；
        - 其他字面量属性收集到 ``properties``，包含 ``value``、``datatype``、``language``。

        参数:
            graph (RDFGraph): 解析后的 RDF 图。

        返回:
            dict[str, Any]: 简化 JSON 结构。
        """

        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []

        def ensure_node(node_iri: URIRef) -> dict[str, Any]:
            sid = str(node_iri)
            if sid not in nodes:
                nodes[sid] = {
                    "id": sid,
                    "type": None,
                    "types": [],  # 记录全部类型以便调试/扩展
                    "label": None,
                    "labels": {},  # 多语言标签: lang -> text
                    "properties": {},  # 其他属性: predicate -> [{value, datatype, language}]
                }
            return nodes[sid]

        for s, p, o in graph:
            if isinstance(s, URIRef):
                s_node = ensure_node(s)
            else:
                # 主语若非 URI（如空白节点），忽略创建节点但仍处理特定边场景
                s_node = None

            # 对象为 URIRef：也创建节点并连边
            if isinstance(o, URIRef):
                # rdf:type 的对象（类）不作为节点抽取，也不生成边，只在源节点记录类型
                if p == RDF.type:
                    s_node = s_node or ensure_node(s)
                    s_node["type"] = str(o)
                    if str(o) not in s_node["types"]:
                        s_node["types"].append(str(o))
                else:
                    ensure_node(o)
                    edges.append(
                        {
                            "source": str(s),
                            "target": str(o),
                            "predicate": str(p),
                        }
                    )
            else:
                # 对象为字面量：处理 label 与常规属性
                if s_node is None:
                    continue
                if p == RDFS.label and isinstance(o, RDFLiteral):
                    text = str(o)
                    lang = o.language or ""
                    # 记录多语言标签
                    if lang:
                        s_node["labels"][lang] = text
                    # 选择一个默认 label（优先无 lang，其次首个见到）
                    if s_node["label"] is None or (lang == "" and s_node["label"]):
                        s_node["label"] = text
                elif isinstance(o, RDFLiteral):
                    pred = str(p)
                    entry = {
                        "value": str(o),
                        "datatype": str(o.datatype) if o.datatype else None,
                        "language": o.language,
                    }
                    current = s_node["properties"].get(pred)
                    if current is None:
                        s_node["properties"][pred] = [entry]
                    elif isinstance(current, list):
                        current.append(entry)
                    else:
                        s_node["properties"][pred] = [current, entry]

        result = {
            "nodes": list(nodes.values()),
            "edges": edges,
            "stats": {
                "node_count": len(nodes),
                "edge_count": len(edges),
            },
        }
        return result
