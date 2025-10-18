import asyncio

import pytest

from common.config import ConfigManager
from sf_rdf_acl.transaction.manager import TransactionManager
from sf_rdf_acl.transaction.upsert import Triple, UpsertRequest


ConfigManager.load()


class StubClient:
    def __init__(self) -> None:
        self.updates: list[str] = []

    async def select(self, query: str, *, timeout: int | None = None, trace_id: str | None = None) -> dict:
        return {"bindings": []}

    async def construct(self, query: str, *, timeout: int | None = None, trace_id: str | None = None) -> dict:
        return {"turtle": ""}

    async def update(self, update: str, *, timeout: int | None = None, trace_id: str | None = None) -> dict:
        self.updates.append(update)
        return {"status": 200, "durationMs": 1.0}

    async def health(self) -> dict[str, str]:  # pragma: no cover
        return {"ok": True}


class StubAudit:
    async def log_operation_async(self, **kwargs):  # pragma: no cover
        return "audit-id"

    async def log_request_async(self, **kwargs):  # pragma: no cover
        return None


@pytest.mark.asyncio
async def test_transaction_manager_executes_updates():
    client = StubClient()
    manager = TransactionManager(client=client, audit_logger=StubAudit())
    request = UpsertRequest(
        graph={"name": "urn:sf:test"},
        triples=[Triple(s="http://example.com/a", p="http://example.com/name", o="Alice")],
        upsert_key="s+p",
        merge_strategy="append",
    )

    result = await manager.upsert(request, trace_id="trace-a", actor="tester")

    assert client.updates, "预期至少执行一条 UPDATE"
    assert result["applied"] == 1
    assert result.get("auditId") == "audit-id"


