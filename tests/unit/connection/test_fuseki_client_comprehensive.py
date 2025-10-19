from __future__ import annotations

"""FusekiClient 综合单元测试（以 mock/monkeypatch 方式验证关键路径）。

覆盖点：
- 熔断器开启/恢复
- 超时重试
- trace_id 透传
- 指标记录（observe_fuseki_response 调用）

说明：
- 本文件以 mock 为主；端到端覆盖在其它 e2e 用例中已验证（真实 Fuseki）。
"""

import asyncio
from collections import deque

import httpx
import pytest

from common.exceptions import ErrorCode, ExternalServiceError
from sf_rdf_acl.connection.client import FusekiClient


@pytest.fixture()
def client() -> FusekiClient:
    return FusekiClient(
        endpoint="http://fuseki",
        dataset="demo",
        retry_policy={"max_attempts": 3, "backoff_seconds": 0.0, "backoff_multiplier": 1.0, "jitter_seconds": 0.0},
        circuit_breaker={"failureThreshold": 3, "recoveryTimeout": 0.05},
    )


class _StubAsyncClient:
    """httpx.AsyncClient 的桩，用队列模拟状态码或异常。"""

    def __init__(self, responses: deque | None = None, exc: Exception | None = None) -> None:
        self._responses = responses or deque()
        self._exc = exc
        self.last_headers: dict[str, str] | None = None

    async def __aenter__(self) -> "_StubAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, *, content: bytes, headers: dict[str, str], auth: httpx.Auth | None) -> httpx.Response:
        self.last_headers = headers
        if self._exc is not None:
            raise self._exc
        if not self._responses:
            raise AssertionError("no stub response configured")
        status, text = self._responses.popleft()
        request = httpx.Request("POST", url)
        return httpx.Response(status, text=text, request=request)


@pytest.mark.asyncio
async def test_circuit_breaker_opens(client: FusekiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """连续失败达到阈值后，后续请求应直接返回熔断异常。"""

    queue = deque([(503, "err")] * 5)
    monkeypatch.setattr("sf_rdf_acl.connection.client.httpx.AsyncClient", lambda *a, **k: _StubAsyncClient(queue))

    with pytest.raises(ExternalServiceError) as exc:
        await client.select("SELECT * WHERE {?s ?p ?o}")
    assert exc.value.code == ErrorCode.FUSEKI_QUERY_ERROR

    with pytest.raises(ExternalServiceError) as exc2:
        await client.select("SELECT * WHERE {?s ?p ?o}")
    assert exc2.value.code == ErrorCode.FUSEKI_CIRCUIT_OPEN


@pytest.mark.asyncio
async def test_circuit_breaker_recovery(client: FusekiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """熔断窗口后，允许请求并在成功后复位。"""

    # 先让其进入 open 状态
    client._cb_failure_count = 3
    client._cb_open_until = client._now() + 0.01
    await asyncio.sleep(0.02)

    queue = deque([(200, '{"head": {"vars": []}, "results": {"bindings": []}}')])
    monkeypatch.setattr("sf_rdf_acl.connection.client.httpx.AsyncClient", lambda *a, **k: _StubAsyncClient(queue))

    res = await client.select("SELECT * WHERE {?s ?p ?o}")
    assert res["stats"]["status"] == 200
    assert client._cb_open_until is None


@pytest.mark.asyncio
async def test_retry_on_timeout(client: FusekiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """前两次超时后第三次成功，应正好尝试3次。"""

    attempts = {"n": 0}

    class _TimeoutThenOK:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *args, **kwargs):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise httpx.ReadTimeout("timeout")
            request = httpx.Request("POST", "http://fuseki")
            return httpx.Response(200, text='{"head": {"vars": []}, "results": {"bindings": []}}', request=request)

    monkeypatch.setattr("sf_rdf_acl.connection.client.httpx.AsyncClient", lambda *a, **k: _TimeoutThenOK())

    await client.select("SELECT * WHERE {?s ?p ?o}")
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_trace_id_propagation(client: FusekiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """trace_id 应注入到 HTTP 头部。"""

    stub = _StubAsyncClient(deque([(200, '{"head": {"vars": []}, "results": {"bindings": []}}')]))
    monkeypatch.setattr("sf_rdf_acl.connection.client.httpx.AsyncClient", lambda *a, **k: stub)

    await client.select("SELECT * WHERE {?s ?p ?o}", trace_id="trace-xyz")
    assert stub.last_headers and stub.last_headers.get(client.trace_header) == "trace-xyz"


@pytest.mark.asyncio
async def test_metrics_recording(client: FusekiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """成功响应应调用 observe_fuseki_response。"""

    calls = {"n": 0}

    def fake_observe(operation: str, status: int, duration: float) -> None:  # pragma: no cover - 简单计数
        calls["n"] += 1

    monkeypatch.setattr("sf_rdf_acl.connection.client.observe_fuseki_response", fake_observe)
    monkeypatch.setattr(
        "sf_rdf_acl.connection.client.httpx.AsyncClient",
        lambda *a, **k: _StubAsyncClient(deque([(200, '{"head": {"vars": []}, "results": {"bindings": []}}')]))
    )

    await client.select("SELECT * WHERE {?s ?p ?o}")
    assert calls["n"] >= 1

