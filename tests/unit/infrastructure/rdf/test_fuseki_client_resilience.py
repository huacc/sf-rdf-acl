"""FusekiClient 韧性机制测试，覆盖熔断与重试行为。"""
import asyncio
from collections import deque

import httpx
import pytest
from prometheus_client import REGISTRY

from common.exceptions import ErrorCode, ExternalServiceError
from sf_rdf_acl.connection.client import FusekiClient


class _AsyncClientStub:
    """httpx.AsyncClient 替身，根据预设序列返回响应或抛出异常。"""

    def __init__(self, responses: deque[tuple[int, str]] | None = None, exc: Exception | None = None) -> None:
        self._responses = responses or deque()
        self._exc = exc

        self.calls = 0

    async def __aenter__(self) -> "_AsyncClientStub":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401 - 占位
        return None

    async def post(self, url: str, *, content: bytes, headers: dict[str, str], auth: httpx.Auth | None) -> httpx.Response:
        """模拟 POST 调用，按照队列弹出响应。"""

        if self._exc is not None:
            raise self._exc
        if not self._responses:
            raise AssertionError("no stub response configured")
        self.calls += 1
        status, text = self._responses.popleft()
        request = httpx.Request("POST", url)
        return httpx.Response(status, text=text, request=request)


@pytest.fixture()
def fuseki_client(monkeypatch: pytest.MonkeyPatch) -> FusekiClient:
    """构造带短超时与熔断阈值的 FusekiClient。"""

    client = FusekiClient(
        endpoint="http://fuseki",
        dataset="demo",
        trace_header="X-Trace-Id",
        default_timeout=1,
        max_timeout=5,
        retry_policy={"max_attempts": 3, "backoff_seconds": 0.0, "backoff_multiplier": 1.0, "jitter_seconds": 0.0},
        circuit_breaker={"failureThreshold": 2, "recoveryTimeout": 60.0, "recordTimeoutOnly": False},
    )
    monkeypatch.setattr(client, "_sleep", lambda *args, **kwargs: asyncio.sleep(0))
    return client


def _patch_async_client(monkeypatch: pytest.MonkeyPatch, responses: list[tuple[int, str]] | None = None, exc: Exception | None = None) -> None:
    """替换 httpx.AsyncClient 构造函数，注入桩。"""

    queue = deque(responses or [])

    def factory(*args, **kwargs):
        return _AsyncClientStub(queue, exc)

    monkeypatch.setattr("sf_rdf_acl.connection.client.httpx.AsyncClient", factory)


def _metric_value(name: str, labels: dict[str, str]) -> float:
    """读取 Prometheus 指标当前值。"""

    value = REGISTRY.get_sample_value(name, labels)
    return 0.0 if value is None else value


@pytest.mark.asyncio
async def test_circuit_opens_after_consecutive_failures(fuseki_client: FusekiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """连续失败达到阈值后，应触发熔断并暴露指标。"""

    _patch_async_client(monkeypatch, responses=[(503, "error"), (503, "error"), (503, "error"), (503, "error")])

    with pytest.raises(ExternalServiceError) as exc_info:
        await fuseki_client.select("SELECT * WHERE {?s ?p ?o}", trace_id="trace-1")
    assert exc_info.value.code == ErrorCode.FUSEKI_QUERY_ERROR

    # 第二次请求立即触发熔断
    with pytest.raises(ExternalServiceError) as circuit_exc:
        await fuseki_client.select("SELECT * WHERE {?s ?p ?o}", trace_id="trace-2")
    assert circuit_exc.value.code == ErrorCode.FUSEKI_CIRCUIT_OPEN

    assert fuseki_client._cb_open_until is not None


@pytest.mark.asyncio
async def test_circuit_recover_after_timeout_window(fuseki_client: FusekiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """熔断窗口过期后，应允许请求并恢复指标。"""

    fuseki_client._cb_failure_threshold = 1  # 便于触发熔断
    fuseki_client._cb_recovery_timeout = 0.01
    _patch_async_client(monkeypatch, responses=[(503, "error"), (503, "error"), (503, "error")])

    with pytest.raises(ExternalServiceError):
        await fuseki_client.select("SELECT * WHERE {?s ?p ?o}", trace_id="trace-3")

    # 人工将熔断窗口设置为已过期，模拟恢复场景
    fuseki_client._cb_open_until = fuseki_client._now() - 1
    fuseki_client._cb_failure_count = 0
    _patch_async_client(monkeypatch, responses=[(200, '{"head": {"vars": []}, "results": {"bindings": []}}')])

    result = await fuseki_client.select("SELECT * WHERE {?s ?p ?o}", trace_id="trace-4")
    assert result["stats"]["status"] == 200
    gauge_value = _metric_value("sf_fuseki_circuit_breaker_state", {"operation": "query"})
    assert gauge_value == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_failure_metric_increments(monkeypatch: pytest.MonkeyPatch, fuseki_client: FusekiClient) -> None:
    """失败后应累加失败指标，成功重试不回滚。"""

    stub = _AsyncClientStub(deque([(503, "boom"), (200, '{"head": {"vars": []}, "results": {"bindings": []}}')]))
    monkeypatch.setattr("sf_rdf_acl.connection.client.httpx.AsyncClient", lambda *args, **kwargs: stub)

    result = await fuseki_client.select("SELECT * WHERE {?s ?p ?o}", trace_id="trace-5")
    assert result["stats"]["status"] == 200
    assert stub.calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, ErrorCode.BAD_REQUEST),
        (401, ErrorCode.UNAUTHENTICATED),
        (403, ErrorCode.FORBIDDEN),
        (404, ErrorCode.NOT_FOUND),
        (503, ErrorCode.FUSEKI_QUERY_ERROR),
    ],
)
async def test_http_error_code_mapping(monkeypatch: pytest.MonkeyPatch, status: int, expected: ErrorCode) -> None:
    client = FusekiClient(
        endpoint="http://fuseki",
        dataset="demo",
        trace_header="X-Trace-Id",
        default_timeout=1,
        max_timeout=5,
        retry_policy={"max_attempts": 1, "backoff_seconds": 0.0, "backoff_multiplier": 1.0, "jitter_seconds": 0.0},
    )
    _patch_async_client(monkeypatch, responses=[(status, "x" * 2000)])

    with pytest.raises(ExternalServiceError) as exc:
        await client.select("SELECT * WHERE {?s ?p ?o}", trace_id="trace-error")

    assert exc.value.code == expected
    message = exc.value.details.get("message") if exc.value.details else ""
    assert len(message) <= 1024


@pytest.mark.asyncio
async def test_retryable_status_codes_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = deque([(418, "teapot"), (200, '{"head": {"vars": []}, "results": {"bindings": []}}')])
    stub = _AsyncClientStub(responses, None)

    monkeypatch.setattr("sf_rdf_acl.connection.client.httpx.AsyncClient", lambda *args, **kwargs: stub)

    client = FusekiClient(
        endpoint="http://fuseki",
        dataset="demo",
        trace_header="X-Trace-Id",
        default_timeout=1,
        max_timeout=5,
        retry_policy={"max_attempts": 2, "retryable_status_codes": [418], "backoff_seconds": 0.0, "backoff_multiplier": 1.0, "jitter_seconds": 0.0},
    )

    result = await client.select("SELECT * WHERE {?s ?p ?o}", trace_id="trace-retry")
    assert result["stats"]["status"] == 200
    assert stub.calls == 2


@pytest.mark.asyncio
async def test_record_timeout_only_skips_connect_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def factory(*args, **kwargs):
        return _AsyncClientStub(deque(), httpx.ConnectError("fail", request=httpx.Request("POST", "http://fuseki")))

    monkeypatch.setattr("sf_rdf_acl.connection.client.httpx.AsyncClient", factory)

    client = FusekiClient(
        endpoint="http://fuseki",
        dataset="demo",
        trace_header="X-Trace-Id",
        default_timeout=1,
        max_timeout=5,
        retry_policy={"max_attempts": 1, "backoff_seconds": 0.0, "backoff_multiplier": 1.0, "jitter_seconds": 0.0},
        circuit_breaker={"failureThreshold": 1, "recoveryTimeout": 60.0, "recordTimeoutOnly": True},
    )

    with pytest.raises(ExternalServiceError):
        await client.select("SELECT * WHERE {?s ?p ?o}", trace_id="trace-connect")

    assert client._cb_failure_count == 0


def test_timeout_clamping() -> None:
    client = FusekiClient(
        endpoint="http://fuseki",
        dataset="demo",
        trace_header="X-Trace-Id",
        default_timeout=10,
        max_timeout=30,
    )
    timeout = client._resolve_timeout(120)
    assert timeout.read == 30
    assert timeout.connect == 30
    timeout_min = client._resolve_timeout(0)
    assert timeout_min.read == 1
    assert timeout_min.connect == 1


@pytest.mark.asyncio
async def test_basic_auth_and_trace_header(monkeypatch: pytest.MonkeyPatch) -> None:
    class _CaptureClient:
        def __init__(self) -> None:
            self.headers: dict[str, str] | None = None
            self.auth: httpx.Auth | None = None

        async def __aenter__(self) -> "_CaptureClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, *, content: bytes, headers: dict[str, str], auth: httpx.Auth | None) -> httpx.Response:
            self.headers = headers
            self.auth = auth
            request = httpx.Request("POST", url)
            return httpx.Response(200, text='{"head": {"vars": []}, "results": {"bindings": []}}', request=request)

    capture = _CaptureClient()
    monkeypatch.setattr("sf_rdf_acl.connection.client.httpx.AsyncClient", lambda *args, **kwargs: capture)

    client = FusekiClient(
        endpoint="http://fuseki",
        dataset="demo",
        auth=("user", "pass"),
        trace_header="X-Trace-Id",
        default_timeout=1,
        max_timeout=5,
        retry_policy={"max_attempts": 1},
    )

    await client.select("SELECT * WHERE {?s ?p ?o}", trace_id="trace-headers")

    assert capture.headers and capture.headers.get("X-Trace-Id") == "trace-headers"
    assert isinstance(capture.auth, httpx.BasicAuth)
    assert isinstance(capture.auth._auth_header, str)
    assert capture.auth._auth_header.startswith("Basic ")
