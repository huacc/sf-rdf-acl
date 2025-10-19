"""graph 模块条件清理功能单元测试。"""
from __future__ import annotations

import re
import shlex
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from common.config import ConfigManager
from common.config.settings import Settings

from sf_rdf_acl.graph.named_graph import (
    ClearCondition,
    NamedGraphManager,
    TriplePattern,
)
from sf_rdf_acl.query.dsl import GraphRef


class StubFusekiClient:
    """模拟 Fuseki 客户端，以可控数据集实现查询与更新。"""

    def __init__(self, initial_data: dict[str, list[tuple[str, str, tuple[str, str]]]]) -> None:
        """初始化测试桩。

        功能:
            复制初始三元组数据，避免测试间的状态相互影响。
        参数:
            initial_data (dict[str, list[tuple[str, str, tuple[str, str]]]]):
                键为命名图 IRI，值为三元组列表；三元组格式为 ``(subject, predicate, (object_type, object_value))``。
        """

        self._data = {graph: list(triples) for graph, triples in initial_data.items()}

    async def select(
        self,
        query: str,
        *,
        timeout: int | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """模拟 SELECT 查询，返回 JSON 结构的结果。"""

        graph_iri = self._extract_graph(query)
        matched = self._filter_triples(graph_iri, query)
        if "COUNT(" in query:
            return {
                "vars": ["count"],
                "bindings": [
                    {"count": {"type": "literal", "value": str(len(matched))}}
                ],
            }
        bindings = [self._to_binding(triple) for triple in matched[:10]]
        return {"vars": ["s", "p", "o"], "bindings": bindings}

    async def update(
        self,
        query: str,
        *,
        timeout: int | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """模拟 UPDATE 删除操作，移除匹配的三元组。"""

        graph_iri = self._extract_graph(query)
        matched = self._filter_triples(graph_iri, query)
        triples = self._data.get(graph_iri, [])
        self._data[graph_iri] = [triple for triple in triples if triple not in matched]
        return {"status": 200, "durationMs": 15.0}

    def _extract_graph(self, query: str) -> str:
        """从 SPARQL 语句中提取 GRAPH IRI。"""

        match = re.search(r"GRAPH\s+<([^>]+)>", query)
        if not match:
            raise ValueError("未找到 GRAPH IRI")
        return match.group(1)

    def _filter_triples(self, graph_iri: str, query: str) -> list[tuple[str, str, tuple[str, str]]]:
        """根据 WHERE 子句过滤命名图中的三元组。"""

        patterns, filters = self._parse_conditions(query)
        triples = self._data.get(graph_iri, [])
        matched: list[tuple[str, str, tuple[str, str]]] = []
        for triple in triples:
            if self._match_patterns(triple, patterns) and self._match_filters(triple, filters):
                matched.append(triple)
        return matched

    def _parse_conditions(self, query: str) -> tuple[list[list[str]], dict[str, Any]]:
        """解析 WHERE 语句得到三元组模式与过滤规则。"""

        block_match = re.search(r"GRAPH\s+<[^>]+>\s*\{(.*?)\}\s*\}", query, re.DOTALL)
        if not block_match:
            return [], {}
        block = block_match.group(1)
        patterns: list[list[str]] = []
        filters: dict[str, Any] = {}
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or line == "}":
                continue
            if line.startswith("FILTER"):
                self._collect_filter(line, filters)
                continue
            if line.endswith("."):
                line = line[:-1].strip()
            parts = shlex.split(line)
            if len(parts) == 3:
                patterns.append(parts)
        return patterns, filters

    def _collect_filter(self, line: str, filters: dict[str, Any]) -> None:
        """解析 FILTER 条件，记录主语前缀、谓词白名单或对象类型。"""

        prefix_match = re.search(r'STRSTARTS\(STR\(\?s\), "([^"]*)"\)', line)
        if prefix_match:
            filters["subject_prefix"] = prefix_match.group(1)
        whitelist_match = re.search(r"\?p IN \(([^)]+)\)", line)
        if whitelist_match:
            values = [token.strip() for token in whitelist_match.group(1).split() if token.strip()]
            filters["predicate_whitelist"] = [value.strip("<>") for value in values]
        if "isIRI(?o)" in line:
            filters["object_type"] = "IRI"
        if "isLiteral(?o)" in line:
            filters["object_type"] = "Literal"

    def _match_patterns(self, triple: tuple[str, str, tuple[str, str]], patterns: list[list[str]]) -> bool:
        """校验给定三元组是否满足全部模式约束。"""

        if not patterns:
            return True
        subject_token, predicate_token, object_token = self._triple_tokens(triple)
        for parts in patterns:
            if len(parts) != 3:
                continue
            if not self._token_match(parts[0], subject_token):
                return False
            if not self._token_match(parts[1], predicate_token):
                return False
            if not self._token_match(parts[2], object_token):
                return False
        return True

    def _match_filters(self, triple: tuple[str, str, tuple[str, str]], filters: dict[str, Any]) -> bool:
        """按照解析出的过滤器判定三元组是否满足要求。"""

        subject, predicate, (obj_type, obj_value) = triple
        prefix = filters.get("subject_prefix")
        if prefix and not subject.startswith(prefix):
            return False
        whitelist = filters.get("predicate_whitelist")
        if whitelist and predicate not in whitelist:
            return False
        obj_limit = filters.get("object_type")
        if obj_limit == "IRI" and obj_type != "uri":
            return False
        if obj_limit == "Literal" and obj_type != "literal":
            return False
        return True

    def _triple_tokens(self, triple: tuple[str, str, tuple[str, str]]) -> tuple[str, str, str]:
        """将内部三元组表示转换为 SPARQL Token。"""

        subject, predicate, (obj_type, obj_value) = triple
        subject_token = f"<{subject}>"
        predicate_token = f"<{predicate}>"
        if obj_type == "uri":
            object_token = f"<{obj_value}>"
        else:
            object_token = f'"{obj_value}"'
        return subject_token, predicate_token, object_token

    def _token_match(self, token: str, actual: str) -> bool:
        """判断模式 token 与实际 token 是否匹配。"""

        if token.startswith("?"):
            return True
        return token == actual

    def _to_binding(self, triple: tuple[str, str, tuple[str, str]]) -> dict[str, Any]:
        """将内部三元组转换为 SPARQL JSON Binding。"""

        subject, predicate, (obj_type, obj_value) = triple
        binding = {
            "s": {"type": "uri", "value": subject},
            "p": {"type": "uri", "value": predicate},
        }
        binding["o"] = {
            "type": "uri" if obj_type == "uri" else "literal",
            "value": obj_value,
        }
        return binding


@pytest_asyncio.fixture
async def manager(monkeypatch: pytest.MonkeyPatch) -> NamedGraphManager:
    """构造带桩客户端的 NamedGraphManager 实例。"""

    settings = Settings()
    dummy_config = SimpleNamespace(settings=settings, security=settings.security)
    monkeypatch.setattr(ConfigManager, "current", classmethod(lambda cls: dummy_config))

    graph_iri = settings.rdf.naming.graph_format.format(model="test", version="v1", env="dev")
    bulk_triples = [
        (f"http://example.com/bulk/{idx}", "http://example.com/bulk", ("literal", f"bulk-{idx}"))
        for idx in range(20)
    ]
    initial_triples = [
        ("http://example.com/specific/1", "http://example.com/pred", ("literal", "value-1")),
        (
            "http://example.com/specific/2",
            "http://www.w3.org/2000/01/rdf-schema#label",
            ("literal", "标签-2"),
        ),
        (
            "http://example.com/specific/3",
            "http://www.w3.org/2000/01/rdf-schema#comment",
            ("literal", "注释"),
        ),
        ("http://example.com/other/1", "http://example.com/toDelete", ("literal", "x")),
        ("http://example.com/other/2", "http://example.com/toDelete", ("literal", "y")),
    ] + bulk_triples

    client = StubFusekiClient({graph_iri: initial_triples})
    return NamedGraphManager(client=client, settings=settings)


@pytest.fixture
def graph_ref() -> GraphRef:
    """提供测试所用的 GraphRef。"""

    return GraphRef(model="test", version="v1", env="dev")


@pytest.fixture
def graph_with_test_data(graph_ref: GraphRef) -> GraphRef:
    """保持与计划文档一致的别名。"""

    return graph_ref


@pytest.mark.asyncio
class TestConditionalClear:
    """验证条件清理各项子功能。"""

    async def test_dry_run_basic(self, manager: NamedGraphManager, graph_ref: GraphRef) -> None:
        """测试 Dry-Run 返回结构与字段。"""

        condition = ClearCondition(patterns=[TriplePattern(predicate="<http://example.com/pred>")])
        result = await manager.conditional_clear(graph_ref, condition, dry_run=True, trace_id="case-001")

        assert isinstance(result.graph_iri, str) and result.graph_iri
        assert result.estimated_deletes >= 0
        assert isinstance(result.sample_triples, list)

    async def test_subject_prefix_filter(self, manager: NamedGraphManager, graph_ref: GraphRef) -> None:
        """测试主语前缀过滤逻辑。"""

        condition = ClearCondition(
            patterns=[TriplePattern()],
            subject_prefix="http://example.com/specific/",
        )
        result = await manager.conditional_clear(graph_ref, condition, dry_run=True, trace_id="case-002")
        for triple in result.sample_triples:
            if "s" in triple:
                assert triple["s"]["value"].startswith("http://example.com/specific/")

    async def test_predicate_whitelist(self, manager: NamedGraphManager, graph_ref: GraphRef) -> None:
        """测试谓词白名单过滤。"""

        allowed_preds = [
            "http://www.w3.org/2000/01/rdf-schema#label",
            "http://www.w3.org/2000/01/rdf-schema#comment",
        ]
        condition = ClearCondition(patterns=[TriplePattern()], predicate_whitelist=allowed_preds)
        result = await manager.conditional_clear(graph_ref, condition, dry_run=True, trace_id="case-003")
        for triple in result.sample_triples:
            if "p" in triple:
                assert triple["p"]["value"] in allowed_preds

    async def test_max_deletes_limit(self, manager: NamedGraphManager, graph_ref: GraphRef) -> None:
        """当预估删除数量超过上限时应抛出异常。"""

        condition = ClearCondition(patterns=[TriplePattern()])
        with pytest.raises(ValueError, match="exceeds max_deletes"):
            await manager.conditional_clear(
                graph_ref,
                condition,
                dry_run=False,
                max_deletes=10,
                trace_id="case-004",
            )

    async def test_execute_conditional_delete(
        self,
        manager: NamedGraphManager,
        graph_with_test_data: GraphRef,
    ) -> None:
        """实际执行删除并验证复查结果为 0。"""

        condition = ClearCondition(patterns=[TriplePattern(predicate="<http://example.com/toDelete>")])

        dry_preview = await manager.conditional_clear(
            graph_with_test_data,
            condition,
            dry_run=True,
            trace_id="case-005",
        )
        initial_count = dry_preview.estimated_deletes
        assert initial_count > 0

        execute_result = await manager.conditional_clear(
            graph_with_test_data,
            condition,
            dry_run=False,
            trace_id="case-006",
        )
        assert execute_result["deleted_count"] == initial_count

        verify = await manager.conditional_clear(
            graph_with_test_data,
            condition,
            dry_run=True,
            trace_id="case-007",
        )
        assert verify.estimated_deletes == 0

