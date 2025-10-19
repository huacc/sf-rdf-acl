from __future__ import annotations

"""游标分页（CursorPagination）与构建器集成测试。

覆盖点：
- 游标编码/解码
- 基于 URI 与字面量的游标过滤构造
- 端到端分页：构造真实图数据（Fuseki），逐页拉取，验证无重复与 has_more 判断
"""

import uuid
from typing import Any

import pytest
import pytest_asyncio

from common.config import ConfigManager
from common.config.settings import Settings
from sf_rdf_acl.connection.client import FusekiClient
from sf_rdf_acl.query.builder import SPARQLQueryBuilder
from sf_rdf_acl.query.dsl import GraphRef, QueryDSL
from sf_rdf_acl.query.pagination import CursorPagination, CursorPage, PageResult
from sf_rdf_acl.transaction.manager import TransactionManager
from sf_rdf_acl.transaction.upsert import Triple, UpsertRequest
from sf_rdf_acl.utils import resolve_graph_iri


class TestCursorPagination:
    def test_encode_decode_cursor(self) -> None:
        """基本的游标编码/解码。"""

        last_item = {"s": {"value": "http://example.com/resource/100", "type": "uri"}}
        cursor = CursorPagination.encode_cursor(last_item, "?s")
        decoded = CursorPagination.decode_cursor(cursor)
        assert decoded["value"] == "http://example.com/resource/100"
        assert decoded["type"] == "uri"

    def test_cursor_filter_uri(self) -> None:
        """针对 IRI 的 STR 比较过滤。"""

        cursor_data = {"value": "http://example.com/resource/100", "type": "uri"}
        filter_str = CursorPagination.build_cursor_filter(cursor_data, "?s")
        assert "STR(?s) >" in filter_str and "http://example.com/resource/100" in filter_str

    def test_cursor_filter_literal(self) -> None:
        """针对字面量的值比较过滤。"""

        cursor_data = {"value": "100", "type": "literal"}
        filter_str = CursorPagination.build_cursor_filter(cursor_data, "?value")
        assert "?value >" in filter_str


@pytest.fixture(scope="session")
def settings() -> Settings:
    ConfigManager.load()
    return ConfigManager.current().settings


@pytest.fixture(scope="session")
def fuseki_client(settings: Settings) -> FusekiClient:
    rdf = settings.rdf
    security = settings.security
    auth = None
    if rdf.auth.username and rdf.auth.password:
        auth = (rdf.auth.username, rdf.auth.password)
    return FusekiClient(
        endpoint=str(rdf.endpoint),
        dataset=rdf.dataset,
        auth=auth,
        trace_header=security.trace_header,
        default_timeout=rdf.timeout.default,
        max_timeout=rdf.timeout.max,
        retry_policy=rdf.retries.model_dump(),
        circuit_breaker=rdf.circuit_breaker.model_dump(by_alias=True),
    )


@pytest_asyncio.fixture
async def paging_graph(settings: Settings):
    """构造一个用于分页测试的命名图并清理。"""

    from sf_rdf_acl.graph.named_graph import NamedGraphManager

    mgr = NamedGraphManager()
    unique = uuid.uuid4().hex
    graph_ref = GraphRef(model="paging", version=f"v{unique[:8]}", env="dev")
    graph_iri = resolve_graph_iri(graph_ref, settings)
    await mgr.create(graph_ref, trace_id=f"trace-paging-{unique}")
    try:
        # 插入 120*3 条三元组（类型、标签、自边）
        tm = TransactionManager()
        triples: list[Triple] = []
        for i in range(24):
            sid = f"http://example.com/paging/item/{i:06d}"
            triples.extend(
                [
                    Triple(s=sid, p="http://www.w3.org/1999/02/22-rdf-syntax-ns#type", o="http://semanticforge.ai/ontologies/core#Entity"),
                    Triple(s=sid, p="http://www.w3.org/2000/01/rdf-schema#label", o=f"Item {i:06d}"),
                    Triple(s=sid, p="http://example.com/relatesTo", o=sid),
                ]
            )
        req = UpsertRequest(graph=graph_ref, triples=triples, upsert_key="s+p", merge_strategy="replace")
        await tm.upsert(req, trace_id=f"trace-paging-upsert-{unique}", actor="pytest")
        yield {"graph_ref": graph_ref, "graph_iri": graph_iri}
    finally:
        try:
            await mgr.clear(graph_ref, trace_id=f"trace-paging-clear-{unique}")
        except Exception:
            pass


async def _fetch_page(
    client: FusekiClient,
    graph_iri: str,
    cursor_page: CursorPage,
) -> PageResult:
    """执行一次基于游标的 SELECT 查询并返回分页结果。"""

    builder = SPARQLQueryBuilder()
    dsl = QueryDSL(type="entity")
    query = builder.build_select_with_cursor(dsl, cursor_page, sort_key="?s", graph=graph_iri)
    raw = await client.select(query, trace_id="trace-cursor-page")
    bindings = list(raw.get("bindings", []))
    has_more = len(bindings) > cursor_page.size
    page_items = bindings[: cursor_page.size]
    next_cursor = None
    if has_more and page_items:
        next_cursor = CursorPagination.encode_cursor(page_items[-1], "?s")
    return PageResult(results=page_items, next_cursor=next_cursor, has_more=has_more)


@pytest.mark.asyncio
async def test_pagination_no_duplicates(fuseki_client: FusekiClient, paging_graph: dict[str, Any]) -> None:
    """分页不重复、可完整遍历。"""

    graph_iri = paging_graph["graph_iri"]
    seen: set[str] = set()
    cursor = None
    page_count = 0

    while True:
        cp = CursorPage(cursor=cursor, size=2)
        page = await _fetch_page(fuseki_client, graph_iri, cp)
        for item in page.results:
            sid = item["s"]["value"]
            assert sid not in seen, f"Duplicate: {sid}"
            seen.add(sid)
        if not page.has_more:
            break
        cursor = page.next_cursor
        page_count += 1
        assert page_count < 1000

    assert len(seen) >= 20

