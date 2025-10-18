"""事务管理与 Upsert 执行实现。"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING, Optional

from rdflib import BNode, Graph as RDFGraph, Literal, URIRef

from common.config import ConfigManager
from common.config.settings import Settings
from common.exceptions import ExternalServiceError
from common.logging import LoggerFactory

from sf_rdf_acl.connection.client import FusekiClient, RDFClient
from sf_rdf_acl.transaction.upsert import Triple, UpsertPlan, UpsertPlanner, UpsertStatement, UpsertRequest
if TYPE_CHECKING:  # pragma: no cover - 仅用于类型提示
    from sf_rdf_acl.transaction.audit import AuditLogger


@dataclass(slots=True)
class _RollbackEntry:
    """描述一次回滚所需执行的 SPARQL 语句。"""

    graph_iri: str
    sparql: str


class TransactionManager:
    """事务管理器，负责调度 Upsert 计划并与 RDF 存储交互。"""

    def __init__(
        self,
        *,
        planner: Optional[UpsertPlanner] = None,
        client: Optional[RDFClient] = None,
        audit_logger: Optional[AuditLogger] = None,
    ) -> None:
        """允许注入规划器、RDF 客户端与审计记录器。"""

        self._config_manager = ConfigManager.current()
        self._settings: Settings = self._config_manager.settings
        self._planner = planner or UpsertPlanner(self._settings)
        self._client = client or self._create_client()
        self._audit_logger = audit_logger
        self._logger = LoggerFactory.create_default_logger(__name__)

    async def begin(self) -> str:
        """生成事务 ID，后续可用于审计。"""

        return str(uuid.uuid4())

    async def commit(self, tx_id: str) -> None:  # noqa: ARG002 - 预留扩展
        """当前实现无需额外动作，保留接口以便扩展真正事务。"""

        return None

    async def rollback(self, tx_id: str) -> None:  # noqa: ARG002 - 预留扩展
        """当前实现无需额外动作，保留接口以便扩展真正事务。"""

        return None

    async def upsert(
        self,
        request: UpsertRequest,
        *,
        trace_id: str,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """执行 Upsert 操作，返回统计信息与潜在冲突。"""

        plan: UpsertPlan = self._planner.plan(request)
        tx_id = await self.begin()
        start = time.perf_counter()

        applied_count = 0
        executed_statements = 0
        conflicts: list[dict[str, Any]] = []
        rollback_stack: list[_RollbackEntry] = []

        try:
            for statement in plan.statements:
                if statement.strategy == "ignore":
                    exists = await self._check_conflict(plan.graph_iri, statement.triples[0], trace_id)
                    if exists:
                        conflicts.append({"key": statement.key, "reason": "duplicate"})
                        continue

                if statement.requires_snapshot:
                    rollback_sql = await self._build_rollback(plan.graph_iri, statement, trace_id)
                    if rollback_sql:
                        rollback_stack.append(_RollbackEntry(graph_iri=plan.graph_iri, sparql=rollback_sql))

                await self._client.update(statement.sparql, trace_id=trace_id)
                executed_statements += 1
                applied_count += len(statement.triples)

            duration_ms = (time.perf_counter() - start) * 1000
            await self.commit(tx_id)

        except Exception:
            await self.rollback(tx_id)
            if rollback_stack:
                await self._apply_rollback(list(reversed(rollback_stack)), trace_id)
            raise

        audit_id: str | None = None
        if self._audit_logger:
            audit_id = await self._audit_logger.log_operation_async(
                op_type="rdf.upsert",
                graph_iri=plan.graph_iri,
                tx_id=tx_id,
                trace_id=trace_id,
                request_hash=plan.request_hash,
                result_status="conflict" if conflicts else "success",
                latency_ms=duration_ms,
                payload={
                    "applied": applied_count,
                    "statements": executed_statements,
                    "conflicts": len(conflicts),
                },
                error_code=None,
                actor=actor,
            )

        result: dict[str, Any] = {
            "graph": plan.graph_iri,
            "txId": tx_id,
            "applied": applied_count,
            "statements": executed_statements,
            "durationMs": duration_ms,
            "conflicts": conflicts,
            "requestHash": plan.request_hash,
        }
        if audit_id:
            result["auditId"] = audit_id
        return result

    # ---- 内部工具 -----------------------------------------------------

    def _create_client(self) -> FusekiClient:
        rdf = self._settings.rdf
        security = self._settings.security
        auth_tuple: tuple[str, str] | None = None
        if rdf.auth.username and rdf.auth.password:
            auth_tuple = (rdf.auth.username, rdf.auth.password)
        retry_policy = {
            "max_attempts": rdf.retries.max_attempts,
            "backoff_seconds": rdf.retries.backoff_seconds,
            "backoff_multiplier": rdf.retries.backoff_multiplier,
            "jitter_seconds": rdf.retries.jitter_seconds or 0.0,
        }
        breaker_policy = rdf.circuit_breaker.model_dump(by_alias=True)
        return FusekiClient(
            endpoint=str(rdf.endpoint),
            dataset=rdf.dataset,
            auth=auth_tuple,
            trace_header=security.trace_header,
            default_timeout=rdf.timeout.default,
            max_timeout=rdf.timeout.max,
            retry_policy=retry_policy,
            circuit_breaker=breaker_policy,
        )

    async def _check_conflict(self, graph_iri: str, triple: Triple, trace_id: str) -> bool:
        """检查 ignore 策略下是否已存在完全相同的三元组。"""

        subject = self._planner._format_subject(triple.s)  # noqa: SLF001
        predicate = self._planner._format_predicate(triple.p)  # noqa: SLF001
        obj = self._planner._format_object(triple)  # noqa: SLF001
        query = (
            "SELECT ?s WHERE {\n"
            f"  GRAPH <{graph_iri}> {{ {subject} {predicate} {obj} . }}\n"
            "} LIMIT 1"
        )
        raw = await self._client.select(query, trace_id=trace_id)
        return bool(raw.get("bindings"))

    async def _build_rollback(self, graph_iri: str, statement: UpsertStatement, trace_id: str) -> str | None:
        """构造回滚语句，通过 CONSTRUCT 捕获原始三元组。"""

        snapshot_query = self._build_snapshot_query(graph_iri, statement)
        if snapshot_query is None:
            return None
        try:
            raw = await self._client.construct(snapshot_query, trace_id=trace_id)
        except ExternalServiceError as exc:
            self._logger.warning("获取回滚快照失败: %s", exc, exc_info=True)
            return None
        turtle = raw.get("turtle", "")
        if not turtle.strip():
            return None
        graph = RDFGraph()
        graph.parse(data=turtle, format="turtle")
        triple_lines: list[str] = []
        for s, p, o in graph:
            triple_lines.append(self._render_rdflib_triple(s, p, o))
        if not triple_lines:
            return None
        inner = "\n    ".join(triple_lines)
        return (
            "INSERT {\n"
            f"  GRAPH <{graph_iri}> {{\n    {inner}\n  }}\n"
            "}\nWHERE { }"
        )

    def _build_snapshot_query(self, graph_iri: str, statement: UpsertStatement) -> str | None:
        """根据分组键构造 CONSTRUCT 查询，用于生成回滚快照。"""

        key_map = self._parse_key(statement.key)
        subject = self._planner._format_subject(key_map.get("s", statement.triples[0].s))  # noqa: SLF001
        where_lines = [
            f"BIND({subject} AS ?__target_s)",
            f"GRAPH <{graph_iri}> {{ ?__target_s ?p ?o . }}",
        ]
        filters: list[str] = []
        if "p" in key_map:
            predicate = self._planner._format_predicate(key_map["p"])  # noqa: SLF001
            where_lines.insert(1, f"BIND({predicate} AS ?__target_p)")
            filters.append("?p = ?__target_p")
        if "o" in key_map:
            triple = Triple(s=key_map.get("s", statement.triples[0].s), p=key_map.get("p", statement.triples[0].p), o=key_map["o"])
            obj_literal = self._planner._format_object(triple)  # noqa: SLF001
            where_lines.insert(1, f"BIND({obj_literal} AS ?__target_o)")
            filters.append("?o = ?__target_o")
        filter_clause = f"FILTER({' && '.join(filters)})" if filters else ""
        construct = (
            "CONSTRUCT {\n"
            f"  GRAPH <{graph_iri}> {{ ?__target_s ?p ?o . }}\n"
            "}\nWHERE {\n"
            f"  {' '.join(where_lines)}\n"
            f"  {filter_clause}\n"
            "}"
        )
        return construct

    async def _apply_rollback(self, entries: list[_RollbackEntry], trace_id: str) -> None:
        """执行回滚语句，忽略失败但记录日志。"""

        for entry in entries:
            try:
                await self._client.update(entry.sparql, trace_id=trace_id)
            except ExternalServiceError as exc:
                self._logger.warning("回滚语句执行失败: %s", exc, exc_info=True)

    def _render_rdflib_triple(self, s: URIRef | BNode, p: URIRef, o: URIRef | BNode | Literal) -> str:
        """将 rdflib 三元组渲染为 SPARQL 片段。"""

        if isinstance(o, Literal):
            triple = Triple(
                s=str(s),
                p=str(p),
                o=str(o),
                lang=o.language,
                dtype=str(o.datatype) if o.datatype else None,
            )
        else:
            triple = Triple(s=str(s), p=str(p), o=str(o))
        return self._planner._render_triple(triple)  # noqa: SLF001

    @staticmethod
    def _parse_key(key: str) -> dict[str, str]:
        """解析分组键为字段字典。"""

        if key.startswith("s::"):
            return {"s": key.split("::", 1)[1]}
        if key.startswith("sp::"):
            _, s_val, p_val = key.split("::", 2)
            return {"s": s_val, "p": p_val}
        if key.startswith("custom[") and "]::" in key:
            marker, rest = key.removeprefix("custom[").split("]::", 1)
            parts = rest.split("::")
            mapping: dict[str, str] = {}
            for index in range(0, len(parts), 2):
                field = parts[index]
                if index + 1 < len(parts):
                    mapping[field] = parts[index + 1]
            return mapping
        return {}




