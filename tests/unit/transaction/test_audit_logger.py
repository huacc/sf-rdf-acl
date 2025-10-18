from __future__ import annotations

import asyncio
from contextlib import contextmanager

from sf_rdf_acl.transaction.audit import AuditLogger


class _Result:
    def __init__(self, value: int = 1) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class _Conn:
    def __init__(self, should_fail: bool = False) -> None:
        self._should_fail = should_fail
        self.last_params: dict | None = None

    def execute(self, sql, params):  # noqa: ANN001 - mimic sqlalchemy API
        if self._should_fail:
            raise RuntimeError("fail execute")
        self.last_params = params
        # return insert id 123
        return _Result(123)


class _Engine:
    def __init__(self, should_fail: bool = False) -> None:
        self._should_fail = should_fail
        self.last_conn: _Conn | None = None

    @contextmanager
    def begin(self):
        conn = _Conn(self._should_fail)
        self.last_conn = conn
        try:
            yield conn
        finally:
            pass


def test_log_operation_success_and_failure() -> None:
    ok_engine = _Engine()
    logger = AuditLogger(dsn="postgresql://", schema="public", engine=ok_engine)
    new_id = logger.log_operation(
        op_type="test", graph_iri="g", tx_id="t", trace_id="tr",
        request_hash="h", result_status="completed", latency_ms=12.3, payload={"k": 1}, error_code=None, actor="u",
    )
    assert new_id == "123"
    assert ok_engine.last_conn and ok_engine.last_conn.last_params is not None

    fail_engine = _Engine(should_fail=True)
    logger2 = AuditLogger(dsn="postgresql://", schema="public", engine=fail_engine)
    assert logger2.log_operation(
        op_type="test", graph_iri="g", tx_id="t", trace_id="tr",
        request_hash="h", result_status="completed", latency_ms=1.0,
    ) is None


def test_log_request_async_runs_without_exception() -> None:
    ok_engine = _Engine()
    logger = AuditLogger(dsn="postgresql://", schema="public", engine=ok_engine)
    # should not raise
    asyncio.run(logger.log_request_async(
        trace_id="x", route="/r", method="GET", status_code=200, duration_ms=3.2, params_hash="p",
    ))

