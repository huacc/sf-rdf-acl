from __future__ import annotations

"""GraphFormatter 模块单元测试。

覆盖内容：
- Turtle 透传
- JSON-LD 转换与 @context 注入
- simplified-json 转换（节点/边/统计）
- simplified-json 多语言标签支持
- 非法格式参数校验

测试数据尽量使用内联 Turtle，避免外部依赖；
本模块不访问外部 Fuseki/PG 服务，满足端到端（模块级）可运行。
"""

import pytest

from sf_rdf_acl.converter.graph_formatter import GraphFormatter


class TestGraphFormatter:
    def setup_method(self) -> None:
        """准备被测实例与基础 Turtle 文本。

        - formatter: 被测 GraphFormatter 实例
        - sample_turtle: 包含 2 个实体、标签、关系与数值属性
        - multilabel_turtle: 同一实体具备中英文两个 label 的示例
        """

        self.formatter = GraphFormatter()
        self.sample_turtle = (
            """
            @prefix ex: <http://example.com/> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

            ex:Person1 a ex:Person ;
                rdfs:label "Alice" ;
                ex:age 30 ;
                ex:knows ex:Person2 .

            ex:Person2 a ex:Person ;
                rdfs:label "Bob" .
            """
        )

        self.multilabel_turtle = (
            """
            @prefix ex: <http://example.com/> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

            ex:E1 a ex:Entity ;
                rdfs:label "示例"@zh ;
                rdfs:label "Sample"@en .
            """
        )

    def test_format_turtle_passthrough(self) -> None:
        """Turtle 格式透传应保持内容不变。"""

        result = self.formatter.format_graph(self.sample_turtle, format_type="turtle")
        assert result == self.sample_turtle

    def test_format_jsonld(self) -> None:
        """JSON-LD 转换应产出字典，包含 @context 或 @graph。"""

        result = self.formatter.format_graph(self.sample_turtle, format_type="json-ld")
        assert isinstance(result, dict)
        # 不同 rdflib 版本可能产出不同顶层键，但通常含 @context 或 @graph
        assert "@context" in result or "@graph" in result

    def test_format_jsonld_with_context(self) -> None:
        """JSON-LD 转换时自定义 @context 应被注入。"""

        custom_context = {
            "ex": "http://example.com/",
            "name": "http://www.w3.org/2000/01/rdf-schema#label",
        }
        result = self.formatter.format_graph(
            self.sample_turtle, format_type="json-ld", context=custom_context
        )
        assert isinstance(result, dict)
        assert result.get("@context") == custom_context

    def test_format_simplified_json(self) -> None:
        """简化 JSON 转换应包含 nodes/edges/stats，且内容合理。"""

        result = self.formatter.format_graph(
            self.sample_turtle, format_type="simplified-json"
        )
        assert isinstance(result, dict)
        assert "nodes" in result and "edges" in result and "stats" in result

        # 验证节点数量与字段
        nodes = result["nodes"]
        assert len(nodes) == 2  # Person1 与 Person2
        person1 = next(n for n in nodes if "Person1" in n["id"])
        assert person1["type"] == "http://example.com/Person"
        assert person1["label"] == "Alice"
        assert "http://example.com/age" in person1["properties"]

        # 验证边
        knows_edge = next(
            e
            for e in result["edges"]
            if e["predicate"] == "http://example.com/knows"
        )
        assert "Person1" in knows_edge["source"]
        assert "Person2" in knows_edge["target"]

        # 统计字段
        assert result["stats"]["node_count"] == 2
        assert result["stats"]["edge_count"] >= 1

    def test_simplified_json_multilang_labels(self) -> None:
        """同一实体存在多语言标签时，应同时记录 label 与 labels。"""

        result = self.formatter.format_graph(
            self.multilabel_turtle, format_type="simplified-json"
        )
        nodes = result["nodes"]
        e1 = next(n for n in nodes if n["id"].endswith("E1"))
        # labels 应包含 zh/en 两种语言
        assert e1["labels"]["zh"] == "示例"
        assert e1["labels"]["en"] == "Sample"
        # label 默认可取任意一个（实现为优先无语言标签，否则首个见到）——至少应为字符串
        assert isinstance(e1["label"], str)

    def test_invalid_format_type(self) -> None:
        """传入不支持的格式类型应抛出 ValueError。"""

        with pytest.raises(ValueError, match="Unsupported format"):
            self.formatter.format_graph(self.sample_turtle, format_type="invalid")

