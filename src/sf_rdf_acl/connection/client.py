"""Fuseki/RDF HTTP 客户端封装。

提供 `RDFClient` 协议与 `FusekiClient` 实现，支持 SELECT、CONSTRUCT、UPDATE 等常见
SPARQL 操作，同时在客户端侧内置以下能力：

* 按请求级别的超时控制与指数退避重试；
* 基于失败次数的熔断器（circuit breaker）；
* 失败/成功指标上报，便于监控可视化；
* 统一的 trace id 透传机制。

所有实际的 Fuseki 请求均使用 HTTP POST 完成，与 Jena Fuseki REST 接口保持兼容。"""
from __future__ import annotations

import asyncio
import random
import time
from threading import Lock
from typing import Any, Protocol

import httpx

from common.exceptions import ErrorCode, ExternalServiceError
from common.logging import LoggerFactory
from common.observability import (
    observe_fuseki_failure,
    observe_fuseki_response,
    set_fuseki_circuit_state,
)


class RDFClient(Protocol):
    """RDF 客户端最小协议。

    任何符合该协议的实现都需要提供 SELECT/CONSTRUCT/UPDATE/health 四类接口。
    每个方法必须支持超时与 trace id 透传，保持与本地 `FusekiClient` 一致。"""

    async def select(self, query: str, *, timeout: int | None = 30, trace_id: str | None = None) -> dict[str, Any]:
        """执行 SPARQL SELECT 查询。

        参数：
            query：完整的 SPARQL SELECT 语句。例如 ``"SELECT * WHERE { ?s ?p ?o } LIMIT 10"``。
            timeout：本次请求的超时时间（秒）。示例 ``10``；``None`` 表示使用默认值。
            trace_id：可选的链路追踪 ID，如 ``"trace-2025-01-01-0001"``。

        返回：与 Fuseki 返回结构一致的字典，至少包含 ``vars``、``bindings`` 和 ``stats``。"""

    async def construct(self, query: str, *, timeout: int | None = 30, trace_id: str | None = None) -> dict[str, Any]:
        """执行 SPARQL CONSTRUCT 查询。

        参数与 :meth:`select` 基本一致；返回值包含 ``turtle`` 文本与 ``stats`` 信息。"""

    async def update(self, update: str, *, timeout: int | None = 30, trace_id: str | None = None) -> dict[str, Any]:
        """执行 SPARQL UPDATE 语句。

        参数：
            update：诸如 ``"DELETE { ... } INSERT { ... } WHERE { ... }"`` 的更新语句。
            timeout：同上。
            trace_id：同上。

        返回：包含 ``status``、``durationMs`` 等统计字段的字典。"""

    async def health(self) -> dict[str, Any]:
        """返回健康检查信息，用于探活或快速测试。"""


class FusekiClient:
    """与 Fuseki REST 接口交互的 HTTP 客户端。"""

    _DEFAULT_RETRY_CODES = {408, 409, 429, 500, 502, 503, 504}

    def __init__(
        self,
        endpoint: str,
        dataset: str,
        *,
        auth: tuple[str, str] | None = None,
        trace_header: str = "X-Trace-Id",
        default_timeout: int = 30,
        max_timeout: int = 120,
        retry_policy: dict[str, Any] | None = None,
        circuit_breaker: dict[str, Any] | None = None,
    ) -> None:
        """构造 Fuseki 客户端。

        参数：
            endpoint：Fuseki 服务地址。例如 ``"http://192.168.0.119:3030"``。
            dataset：目标数据集名称。例如 ``"semantic_forge_test"``。
            auth：可选的 Basic Auth 凭据 ``("username", "password")``。
            trace_header：用于携带 ``trace_id`` 的 HTTP 请求头名称，默认 ``"X-Trace-Id"``。
            default_timeout：默认超时时间（秒），示例 ``30``，必须 >= 1。
            max_timeout：允许的最大超时上限（秒），示例 ``120``，必须 >= ``default_timeout``。
            retry_policy：自定义重试策略，可包含：
                * ``max_attempts``：最大重试次数（>=1）；
                * ``backoff_seconds``：首轮退避（秒）；
                * ``backoff_multiplier``：指数退避乘子；
                * ``jitter_seconds``：随机扰动范围；
                * ``retryable_status_codes``：自定义可重试的 HTTP 状态码集合。
            circuit_breaker：熔断器配置，可包含：
                * ``failureThreshold``：连续失败阈值，示例 ``5``；
                * ``recoveryTimeout``：熔断后休眠时间（秒），示例 ``30``；
                * ``recordTimeoutOnly``：是否只将超时计入熔断统计。"""

        self.endpoint = endpoint.rstrip("/")
        self.dataset = dataset.strip("/")
        self.trace_header = trace_header
        self._default_timeout = default_timeout
        self._max_timeout = max_timeout
        self._retry_policy = {
            "max_attempts": 3,
            "backoff_seconds": 0.5,
            "backoff_multiplier": 2.0,
            "jitter_seconds": 0.1,
        }
        if retry_policy:
            self._retry_policy.update(retry_policy)
        self._retry_codes = set(self._DEFAULT_RETRY_CODES)
        if retry_policy and "retryable_status_codes" in retry_policy:
            codes = retry_policy["retryable_status_codes"]
            self._retry_codes = set(codes) or self._retry_codes
        self._auth = httpx.BasicAuth(*auth) if auth else None
        self._logger = LoggerFactory.create_default_logger(__name__)

        cb = circuit_breaker or {}
        self._cb_failure_threshold = int(cb.get("failureThreshold", 5))
        self._cb_recovery_timeout = float(cb.get("recoveryTimeout", 30.0))
        self._cb_record_timeout_only = bool(cb.get("recordTimeoutOnly", False))
        self._cb_failure_count = 0
        self._cb_open_until: float | None = None
        self._breaker_lock = Lock()

    async def select(self, query: str, *, timeout: int | None = 30, trace_id: str | None = None) -> dict[str, Any]:
        """执行 SPARQL SELECT 请求。

        参数：与 :class:`RDFClient.select` 相同。

        返回：包含 ``vars``、``bindings``、``stats`` 等字段的字典。"""

        response, duration_ms = await self._execute(
            path=f"/{self.dataset}/query",
            query=query,
            accept="application/sparql-results+json",
            content_type="application/sparql-query",
            timeout=timeout,
            trace_id=trace_id,
        )
        data = response.json()
        return {
            "vars": data.get("head", {}).get("vars", []),
            "bindings": data.get("results", {}).get("bindings", []),
            "stats": {
                "status": response.status_code,
                "durationMs": duration_ms,
            },
        }

    async def construct(self, query: str, *, timeout: int | None = 30, trace_id: str | None = None) -> dict[str, Any]:
        """执行 SPARQL CONSTRUCT 请求，返回 Turtle 文本。"""

        response, duration_ms = await self._execute(
            path=f"/{self.dataset}/query",
            query=query,
            accept="text/turtle",
            content_type="application/sparql-query",
            timeout=timeout,
            trace_id=trace_id,
        )
        return {
            "turtle": response.text,
            "stats": {
                "status": response.status_code,
                "durationMs": duration_ms,
            },
        }

    async def update(self, update: str, *, timeout: int | None = 30, trace_id: str | None = None) -> dict[str, Any]:
        """执行 SPARQL UPDATE 请求并返回执行统计。"""

        response, duration_ms = await self._execute(
            path=f"/{self.dataset}/update",
            query=update,
            accept="application/sparql-results+json",
            content_type="application/sparql-update",
            timeout=timeout,
            trace_id=trace_id,
        )
        return {
            "status": response.status_code,
            "durationMs": duration_ms,
        }

    async def health(self) -> dict[str, Any]:
        """返回快速探活信息，避免产生实际负载。"""

        return {"ok": True, "backend": "fuseki", "dataset": self.dataset}

    # ---- 内部工具 -----------------------------------------------------

    async def _execute(
        self,
        *,
        path: str,
        query: str,
        accept: str,
        content_type: str,
        timeout: int | None,
        trace_id: str | None,
    ) -> tuple[httpx.Response, float]:
        """执行底层 HTTP POST 请求并应用重试/熔断策略。

        参数：
            path：请求路径，示例 ``"/semantic_forge_test/query"``，必须以 ``/`` 开头。
            query：要提交的 SPARQL 字符串，例如 ``"SELECT * WHERE { ?s ?p ?o }"``。
            accept：HTTP `Accept` 头部，例如 ``"application/sparql-results+json"``。
            content_type：HTTP `Content-Type`，如 ``"application/sparql-query"``。
            timeout：单次请求的超时（秒），范围 ``1``~``max_timeout``，``None`` 表示默认值。
            trace_id：链路追踪 ID，例如 ``"span-2025-10-18-01"``。

        返回：二元组 ``(response, duration_ms)``，其中 ``duration_ms`` 是耗时（毫秒）。

        异常：达到最大重试次数或遇到不可恢复错误时抛出 :class:`ExternalServiceError`。"""

        operation = self._operation_from_path(path)
        self._ensure_circuit_allows(operation, trace_id)

        url = f"{self.endpoint}{path}"
        resolved_timeout = self._resolve_timeout(timeout)
        headers = {
            "Accept": accept,
            "Content-Type": content_type,
        }
        if trace_id:
            headers[self.trace_header] = trace_id

        attempt = 0
        backoff = float(self._retry_policy["backoff_seconds"])
        max_attempts = int(self._retry_policy["max_attempts"])
        multiplier = float(self._retry_policy["backoff_multiplier"])
        jitter = float(self._retry_policy["jitter_seconds"])

        while True:
            attempt += 1
            start = time.perf_counter()
            try:
                # 每次请求使用新的 AsyncClient，确保超时设置独立
                async with httpx.AsyncClient(timeout=resolved_timeout) as client:
                    response = await client.post(
                        url,
                        content=query.encode("utf-8"),
                        headers=headers,
                        auth=self._auth,
                    )
                duration_ms = (time.perf_counter() - start) * 1000
                status_code = response.status_code

                if status_code >= 400:
                    observe_fuseki_response(operation, status_code, duration_ms / 1000)
                    reason = self._response_reason(status_code)
                    should_break = self._should_count_failure_status(status_code)
                    observe_fuseki_failure(operation, reason)
                    self._record_failure(operation, reason, should_break, trace_id)
                    if self._should_retry(status_code, attempt, max_attempts):
                        await self._sleep(backoff, jitter)
                        backoff *= multiplier
                        continue
                    self._raise_http_error(response, reason)

                self._record_success(operation)
                observe_fuseki_response(operation, status_code, duration_ms / 1000)
                return response, duration_ms
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError) as exc:
                reason = self._exception_reason(exc)
                count_for_breaker = (
                    not self._cb_record_timeout_only
                    or isinstance(exc, (httpx.ReadTimeout, httpx.ConnectTimeout))
                )
                observe_fuseki_failure(operation, reason)
                self._record_failure(operation, reason, count_for_breaker, trace_id)
                if attempt >= max_attempts:
                    raise ExternalServiceError(
                        ErrorCode.FUSEKI_CONNECT_ERROR,
                        "Fuseki 连接失败",
                        details={"endpoint": url, "error": str(exc)},
                    ) from exc
                await self._sleep(backoff, jitter)
                backoff *= multiplier

    def _resolve_timeout(self, timeout: int | None) -> httpx.Timeout:
        """计算本次请求使用的超时时间对象。"""

        if timeout is None:
            effective = self._default_timeout
        else:
            effective = max(1, min(timeout, self._max_timeout))
        return httpx.Timeout(effective, connect=effective)

    def _should_retry(self, status_code: int, attempt: int, max_attempts: int) -> bool:
        """根据状态码与重试次数判断是否继续重试。"""

        return status_code in self._retry_codes and attempt < max_attempts

    async def _sleep(self, backoff: float, jitter: float) -> None:
        """根据退避参数异步等待。"""

        delay = backoff + random.uniform(0, jitter)
        await asyncio.sleep(delay)

    def _raise_http_error(self, response: httpx.Response, reason: str) -> None:
        """将 HTTP 错误响应转换为平台统一异常。"""

        message = response.text
        code = ErrorCode.FUSEKI_QUERY_ERROR
        if response.status_code == 400:
            code = ErrorCode.BAD_REQUEST
        elif response.status_code == 404:
            code = ErrorCode.NOT_FOUND
        elif response.status_code in {401, 403}:
            code = ErrorCode.FORBIDDEN if response.status_code == 403 else ErrorCode.UNAUTHENTICATED
        raise ExternalServiceError(
            code,
            "Fuseki 查询失败",
            details={"status": response.status_code, "message": message[:1024], "reason": reason},
        )

    # ---- 熔断与指标 -----------------------------------------------------

    def _ensure_circuit_allows(self, operation: str, trace_id: str | None) -> None:
        """检查熔断器状态，必要时直接拒绝请求。"""

        with self._breaker_lock:
            if self._cb_open_until is None:
                return
            now = self._now()
            if now >= self._cb_open_until:
                # 熔断窗口已结束，允许半开重试
                self._cb_open_until = None
                self._cb_failure_count = 0
                set_fuseki_circuit_state(operation, False)
                self._logger.info("Fuseki 熔断窗口结束，允许请求重试", extra={"trace_id": trace_id})
                return
        if self._cb_open_until is not None:
            observe_fuseki_failure(operation, "circuit_open")
            remaining = max(0.0, (self._cb_open_until or 0) - self._now())
            raise ExternalServiceError(
                ErrorCode.FUSEKI_CIRCUIT_OPEN,
                "Fuseki 服务已被熔断",
                details={"recoveryAfter": remaining, "operation": operation},
            )

    def _record_failure(self, operation: str, reason: str, count_for_breaker: bool, trace_id: str | None) -> None:
        """记录失败并在达到阈值后打开熔断。"""

        if not count_for_breaker:
            return
        with self._breaker_lock:
            if self._cb_open_until is not None:
                return
            self._cb_failure_count += 1
            if self._cb_failure_count >= self._cb_failure_threshold:
                self._cb_open_until = self._now() + self._cb_recovery_timeout
                set_fuseki_circuit_state(operation, True)
                self._logger.warning(
                    "Fuseki 熔断器已打开",
                    extra={
                        "trace_id": trace_id,
                        "operation": operation,
                        "reason": reason,
                        "recovery_timeout": self._cb_recovery_timeout,
                    },
                )

    def _record_success(self, operation: str) -> None:
        """在成功请求后重置熔断状态。"""

        with self._breaker_lock:
            self._cb_failure_count = 0
            if self._cb_open_until is not None:
                self._cb_open_until = None
                set_fuseki_circuit_state(operation, False)

    def _should_count_failure_status(self, status_code: int) -> bool:
        """是否将该状态码计入熔断失败次数。"""

        return status_code >= 500 or status_code in self._retry_codes

    @staticmethod
    def _response_reason(status_code: int) -> str:
        """根据状态码映射统一的失败原因标签。"""

        if status_code >= 500:
            return "server_error"
        if status_code in {429}:
            return "rate_limited"
        if status_code in {408}:
            return "timeout"
        if status_code in {409}:
            return "conflict"
        return "client_error"

    @staticmethod
    def _exception_reason(exc: Exception) -> str:
        """将异常对象归类为标准原因标签。"""

        if isinstance(exc, httpx.ReadTimeout):
            return "timeout"
        if isinstance(exc, httpx.ConnectTimeout):
            return "connect_timeout"
        if isinstance(exc, httpx.ConnectError):
            return "connect_error"
        return "unknown"

    @staticmethod
    def _operation_from_path(path: str) -> str:
        """根据 URL 路径推断操作类型（query/update）。"""

        return "update" if "update" in path else "query"

    @staticmethod
    def _now() -> float:
        """返回单调递增时间戳，用于计算耗时。"""

        return time.monotonic()
