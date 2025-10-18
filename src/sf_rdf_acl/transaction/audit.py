"""审计与请求日志写入工具。"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


class AuditLogger:
    """封装 PostgreSQL 写入逻辑的审计记录器。"""

    def __init__(self, dsn: str, schema: str, *, engine: Optional[Engine] = None, logger: Optional[logging.Logger] = None) -> None:
        """初始化审计记录器，允许注入 Engine 便于测试。"""

        self._engine = engine or create_engine(dsn, future=True, pool_pre_ping=True)
        self._schema = schema
        self._logger = logger or logging.getLogger(__name__)

    async def log_operation_async(
        self,
        *,
        op_type: str,
        graph_iri: str,
        tx_id: str,
        trace_id: str,
        request_hash: str,
        result_status: str,
        latency_ms: float,
        payload: dict[str, Any] | None = None,
        error_code: str | None = None,
        actor: str | None = None,
    ) -> str | None:
        """异步写入 rdf_operation_audit，返回记录 ID。"""

        return await asyncio.to_thread(
            self.log_operation,
            op_type=op_type,
            graph_iri=graph_iri,
            tx_id=tx_id,
            trace_id=trace_id,
            request_hash=request_hash,
            result_status=result_status,
            latency_ms=latency_ms,
            payload=payload,
            error_code=error_code,
            actor=actor,
        )

    def log_operation(
        self,
        *,
        op_type: str,
        graph_iri: str,
        tx_id: str,
        trace_id: str,
        request_hash: str,
        result_status: str,
        latency_ms: float,
        payload: dict[str, Any] | None = None,
        error_code: str | None = None,
        actor: str | None = None,
    ) -> str | None:
        """同步写入 rdf_operation_audit，发生异常时记录日志并返回 None。"""

        try:
            sql = text(
                f"""
                INSERT INTO {self._schema}.rdf_operation_audit
                    (op_type, actor, graph_iri, tx_id, trace_id, request_hash,
                     result_status, error_code, latency_ms, payload)
                VALUES
                    (:op_type, :actor, :graph_iri, :tx_id, :trace_id, :request_hash,
                     :result_status, :error_code, :latency_ms, :payload)
                RETURNING id
                """
            )
            json_payload = json.dumps(payload or {}, ensure_ascii=False)
            with self._engine.begin() as conn:
                result = conn.execute(
                    sql,
                    {
                        "op_type": op_type,
                        "actor": actor or "system",
                        "graph_iri": graph_iri,
                        "tx_id": tx_id,
                        "trace_id": trace_id,
                        "request_hash": request_hash,
                        "result_status": result_status,
                        "error_code": error_code,
                        "latency_ms": int(latency_ms),
                        "payload": json_payload,
                    },
                )
                new_id = result.scalar_one()
            return str(new_id)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("写入 rdf_operation_audit 失败: %s", exc, exc_info=True)
            return None

    async def log_request_async(
        self,
        *,
        trace_id: str,
        route: str,
        method: str,
        status_code: int,
        duration_ms: float,
        params_hash: str,
        client_ip: str | None = None,
        user_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        """异步写入 request_log。"""

        await asyncio.to_thread(
            self.log_request,
            trace_id=trace_id,
            route=route,
            method=method,
            status_code=status_code,
            duration_ms=duration_ms,
            params_hash=params_hash,
            client_ip=client_ip,
            user_id=user_id,
            occurred_at=occurred_at,
        )

    def log_request(
        self,
        *,
        trace_id: str,
        route: str,
        method: str,
        status_code: int,
        duration_ms: float,
        params_hash: str,
        client_ip: str | None = None,
        user_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        """同步写入 request_log。失败时仅记录告警，不影响主流程。"""

        try:
            sql = text(
                f"""
                INSERT INTO {self._schema}.request_log
                    (trace_id, route, method, status_code, duration_ms, client_ip, user_id, params_hash, created_at)
                VALUES
                    (:trace_id, :route, :method, :status_code, :duration_ms, :client_ip, :user_id, :params_hash, :created_at)
                ON CONFLICT (trace_id) DO UPDATE SET
                    route = EXCLUDED.route,
                    method = EXCLUDED.method,
                    status_code = EXCLUDED.status_code,
                    duration_ms = EXCLUDED.duration_ms,
                    client_ip = EXCLUDED.client_ip,
                    user_id = EXCLUDED.user_id,
                    params_hash = EXCLUDED.params_hash,
                    created_at = EXCLUDED.created_at
                """
            )
            with self._engine.begin() as conn:
                conn.execute(
                    sql,
                    {
                        "trace_id": trace_id,
                        "route": route,
                        "method": method,
                        "status_code": status_code,
                        "duration_ms": int(duration_ms),
                        "client_ip": client_ip,
                        "user_id": user_id,
                        "params_hash": params_hash,
                        "created_at": occurred_at or datetime.utcnow(),
                    },
                )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("写入 request_log 失败: %s", exc, exc_info=True)
