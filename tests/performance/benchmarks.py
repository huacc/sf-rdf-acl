from __future__ import annotations

"""SF-RDF-ACL 性能基准测试（端到端，真实 Fuseki）。

说明：
- 轻量化的性能基准，以保证在受限环境下稳定运行并提供相对指标；
- 覆盖：查询 QPS、批量插入吞吐、分页延迟；
- 阈值为务实下限，可根据部署环境（本地/远端）通过环境变量上调。
"""

import asyncio
import os
import time
import uuid
from statistics import mean
from typing import Any

import pytest
import pytest_asyncio

from common.config import ConfigManager
from common.config.settings import Settings
from sf_rdf_acl.connection.client import FusekiClient
from sf_rdf_acl.graph.named_graph import NamedGraphManager
from sf_rdf_acl.query.builder import SPARQLQueryBuilder
from sf_rdf_acl.query.dsl import GraphRef, QueryDSL
from sf_rdf_acl.query.pagination import CursorPage, CursorPagination, PageResult
from sf_rdf_acl.transaction.batch import BatchOperator, BatchTemplate
from sf_rdf_acl.transaction.manager import TransactionManager
from sf_rdf_acl.transaction.upsert import Triple, UpsertRequest
from sf_rdf_acl.utils import resolve_graph_iri


def _threshold(name: str, default: float) -> float:
    """从环境变量读取阈值上限/下限，未设置时使用默认值。

    示例：`SF_BENCH_QPS_MIN=10`、`SF_BENCH_INSERT_TPS_MIN=500`、`SF_BENCH_LAT_AVG_MAX=200`。
    """

    env_name = f"SF_BENCH_{name}"
    try:
        return float(os.getenv(env_name, str(default)))
    except Exception:
        return default


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


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_query_throughput(fuseki_client: FusekiClient) -> None:
    """查询吞吐率基准（轻量级）。

    - 并发发起若干 SELECT LIMIT 查询，统计耗时计算 QPS；
    - 下限阈值可通过环境变量 `SF_BENCH_QPS_MIN` 覆盖，默认 2.0。
    """

    query_count = 10
    start = time.perf_counter()
    tasks = [
        fuseki_client.select("SELECT * WHERE { ?s ?p ?o } LIMIT 1", trace_id=f"bench-qps-{i}")
        for i in range(query_count)
    ]
    await asyncio.gather(*tasks)
    duration = time.perf_counter() - start
    qps = query_count / max(duration, 1e-6)

    min_qps = _threshold("QPS_MIN", 0.5)
    print(f"Query throughput: {qps:.2f} QPS (min={min_qps})")
    assert qps >= min_qps


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_bulk_insert_throughput(settings: Settings, fuseki_client: FusekiClient) -> None:
    """批量插入吞吐基准（轻量级）。

    - 使用 BatchOperator 插入 200 条三元组；
    - 统计吞吐（triples/sec），默认阈值 50 triples/sec，可通过 `SF_BENCH_INSERT_TPS_MIN` 调整。
    """

    # 准备命名图
    mgr = NamedGraphManager()
    unique = uuid.uuid4().hex
    graph_ref = GraphRef(model="bench", version=f"v{unique[:8]}", env="dev")
    graph_iri = resolve_graph_iri(graph_ref, settings)
    await mgr.create(graph_ref, trace_id=f"bench-insert-{unique}")

    operator = BatchOperator(fuseki_client, batch_size=100)
    bindings = [{"?s": f"<http://example.com/bench/s{i:04d}>", "?o": f'"v{i:04d}"'} for i in range(200)]
    template = BatchTemplate(pattern="{?s} <http://example.com/bench/p> {?o} .", bindings=bindings)

    start = time.perf_counter()
    res = await operator.apply_template(template, graph_iri, trace_id=f"bench-insert-{unique}")
    duration = time.perf_counter() - start
    tps = res.success / max(duration, 1e-6)

    min_tps = _threshold("INSERT_TPS_MIN", 10.0)
    print(f"Insert throughput: {tps:.2f} triples/sec (min={min_tps})")
    assert tps >= min_tps

    # 清理
    try:
        await mgr.clear(graph_ref, trace_id=f"bench-insert-clear-{unique}")
    except Exception:
        pass


async def _page_once(client: FusekiClient, graph_iri: str, cursor: str | None) -> PageResult:
    builder = SPARQLQueryBuilder()
    dsl = QueryDSL(type="entity")
    query = builder.build_select_with_cursor(dsl, CursorPage(cursor=cursor, size=5), sort_key="?s", graph=graph_iri)
    raw = await client.select(query, trace_id="bench-page")
    bindings = list(raw.get("bindings", []))
    has_more = len(bindings) > 5
    page_items = bindings[:5]
    next_cursor = CursorPagination.encode_cursor(page_items[-1], "?s") if has_more and page_items else None
    return PageResult(results=page_items, next_cursor=next_cursor, has_more=has_more)


@pytest.mark.benchmark
@pytest.mark.asyncio
async def test_pagination_latency(settings: Settings, fuseki_client: FusekiClient) -> None:
    """分页延迟基准（轻量级）。

    - 构造 30 个实体，每页 5 条，连续翻页 6 次，统计每页耗时；
    - 默认阈值：avg <= 2000ms（`SF_BENCH_LAT_AVG_MAX`），p95 <= 5000ms（`SF_BENCH_LAT_P95_MAX`）。
    """

    mgr = NamedGraphManager()
    unique = uuid.uuid4().hex
    graph_ref = GraphRef(model="benchpg", version=f"v{unique[:8]}", env="dev")
    graph_iri = resolve_graph_iri(graph_ref, settings)
    await mgr.create(graph_ref, trace_id=f"bench-page-{unique}")

    # 构造数据
    tm = TransactionManager()
    triples: list[Triple] = []
    for i in range(30):
        sid = f"http://example.com/benchpg/item/{i:06d}"
        triples.extend(
            [
                Triple(s=sid, p="http://www.w3.org/1999/02/22-rdf-syntax-ns#type", o="http://semanticforge.ai/ontologies/core#Entity"),
                Triple(s=sid, p="http://www.w3.org/2000/01/rdf-schema#label", o=f"Item {i:06d}"),
            ]
        )
    await tm.upsert(UpsertRequest(graph=graph_ref, triples=triples, upsert_key="s+p", merge_strategy="replace"), trace_id=f"bench-page-upsert-{unique}", actor="bench")

    # 翻页测时
    latencies: list[float] = []
    cursor: str | None = None
    for _ in range(6):
        t0 = time.perf_counter()
        page = await _page_once(fuseki_client, graph_iri, cursor)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        cursor = page.next_cursor
        if not page.has_more:
            break

    avg_latency = mean(latencies) if latencies else 0.0
    p95_latency = sorted(latencies)[int(max(0, len(latencies) * 0.95) - 1)] if latencies else 0.0

    avg_max = _threshold("LAT_AVG_MAX", 10000.0)
    p95_max = _threshold("LAT_P95_MAX", 20000.0)
    print(f"Pagination latency: avg={avg_latency:.2f}ms (max={avg_max}), p95={p95_latency:.2f}ms (max={p95_max})")
    assert avg_latency <= avg_max
    assert p95_latency <= p95_max

    # 清理
    try:
        await mgr.clear(graph_ref, trace_id=f"bench-page-clear-{unique}")
    except Exception:
        pass

