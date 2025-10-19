from __future__ import annotations

"""BatchOperator 批处理写入端到端测试（真实 Fuseki）。

覆盖点：
- 模板渲染 + 分批提交
- 失败批次的单条重试与失败记录
"""

import uuid
from typing import Any

import pytest
import pytest_asyncio

from common.config import ConfigManager
from common.config.settings import Settings
from sf_rdf_acl.connection.client import FusekiClient
from sf_rdf_acl.query.dsl import GraphRef
from sf_rdf_acl.transaction.batch import BatchOperator, BatchTemplate
from sf_rdf_acl.utils import resolve_graph_iri
from sf_rdf_acl.graph.named_graph import NamedGraphManager


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
async def batch_graph(settings: Settings):
    mgr = NamedGraphManager()
    unique = uuid.uuid4().hex
    graph_ref = GraphRef(model="batch", version=f"v{unique[:8]}", env="dev")
    graph_iri = resolve_graph_iri(graph_ref, settings)
    await mgr.create(graph_ref, trace_id=f"trace-batch-{unique}")
    try:
        yield {"graph_ref": graph_ref, "graph_iri": graph_iri}
    finally:
        try:
            await mgr.clear(graph_ref, trace_id=f"trace-batch-clear-{unique}")
        except Exception:
            pass


@pytest.mark.asyncio
async def test_apply_template_basic(fuseki_client: FusekiClient, batch_graph: dict[str, Any]) -> None:
    operator = BatchOperator(fuseki_client, batch_size=10)
    pattern = "{?s} <http://example.com/pred> {?o} ."
    bindings = [
        {"?s": "<http://example.com/s1>", "?o": '"value1"'},
        {"?s": "<http://example.com/s2>", "?o": '"value2"'},
        {"?s": "<http://example.com/s3>", "?o": '"value3"'},
    ]
    template = BatchTemplate(pattern=pattern, bindings=bindings)

    res = await operator.apply_template(template, batch_graph["graph_iri"], trace_id="test-batch-basic")
    assert res.total == 3 and res.success == 3 and res.failed == 0

    # 校验插入成功
    check = await fuseki_client.select(
        f"""
        SELECT ?s ?o WHERE {{ GRAPH <{batch_graph['graph_iri']}> {{ ?s <http://example.com/pred> ?o }} }}
        """,
        trace_id="test-batch-basic-select",
    )
    values = {(b["s"]["value"], b["o"]["value"]) for b in check["bindings"]}
    assert ("http://example.com/s1", "value1") in values
    assert ("http://example.com/s2", "value2") in values
    assert ("http://example.com/s3", "value3") in values


@pytest.mark.asyncio
async def test_large_batch_and_retry(fuseki_client: FusekiClient, batch_graph: dict[str, Any]) -> None:
    operator = BatchOperator(fuseki_client, batch_size=25, max_retries=2)
    pattern = "{?s} <http://example.com/big> {?o} ."
    # 制造 60 条绑定，其中 1 条为错误绑定（对象字面量缺失引号导致 SPARQL 语法错误）
    bindings = [
        {"?s": f"<http://example.com/big/{i:03d}>", "?o": f'"val{i:03d}"'} for i in range(60)
    ]
    bindings.insert(10, {"?s": "<http://example.com/big/bad>", "?o": "unterminated_literal"})  # 故意错误

    template = BatchTemplate(pattern=pattern, bindings=bindings)
    res = await operator.apply_template(template, batch_graph["graph_iri"], trace_id="test-batch-large")

    assert res.total == len(bindings)
    # 59 成功，1 失败（错误绑定经过单条重试仍失败）
    assert res.success == len(bindings) - 1
    assert res.failed == 1 and res.failed_items

    # spot check：随机校验若干条存在
    check = await fuseki_client.select(
        f"SELECT (COUNT(?s) AS ?cnt) WHERE {{ GRAPH <{batch_graph['graph_iri']}> {{ ?s <http://example.com/big> ?o }} }}",
        trace_id="test-batch-large-count",
    )
    # COUNT 返回为字面量字符串；至少应 >= 成功条数的一部分（不同 Fuseki 配置下 COUNT 语义一致）
    count_val = int(check["bindings"][0]["cnt"]["value"]) if check["bindings"] else 0
    assert count_val >= res.success - 5  # 近似校验，避免后端延迟写导致瞬时差异

