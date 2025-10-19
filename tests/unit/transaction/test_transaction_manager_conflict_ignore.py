from __future__ import annotations

"""TransactionManager 冲突忽略策略测试：存在即不更新。"""

import pytest

from common.config import ConfigManager
from sf_rdf_acl.transaction.manager import TransactionManager
from sf_rdf_acl.transaction.upsert import Triple, UpsertRequest


ConfigManager.load()


class _ConflictClient:
    def __init__(self) -> None:
        self.update_calls = 0

    async def select(self, query: str, *, timeout: int | None = None, trace_id: str | None = None) -> dict:
        return {"bindings": [{"s": {"type": "uri", "value": "urn:s"}}]}

    async def construct(self, *args, **kwargs):  # pragma: no cover - not used
        return {"turtle": ""}

    async def update(self, *args, **kwargs):  # pragma: no cover - should not run for ignore conflict
        self.update_calls += 1
        return {"status": 200}


class _StubAudit:
    async def log_operation_async(self, **kwargs):  # pragma: no cover
        return "audit-id"

    async def log_request_async(self, **kwargs):  # pragma: no cover
        return None


@pytest.mark.asyncio
async def test_transaction_manager_reports_ignore_conflict() -> None:
    client = _ConflictClient()
    manager = TransactionManager(client=client, audit_logger=_StubAudit())
    request = UpsertRequest(
        graph={"name": "urn:test"},
        triples=[Triple(s="urn:s", p="urn:p", o="literal")],
        merge_strategy="ignore",
    )

    result = await manager.upsert(request, trace_id="trace-ignore")

    assert result["conflicts"]
    assert result["conflicts"][0]["key"]
    assert client.update_calls == 0, "Ignore conflicts should not issue updates"

