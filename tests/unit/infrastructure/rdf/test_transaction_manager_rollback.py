import pytest

from common.config import ConfigManager
from common.exceptions import ExternalServiceError
from common.exceptions.codes import ErrorCode
from sf_rdf_acl.transaction.manager import TransactionManager
from sf_rdf_acl.transaction.upsert import Triple, UpsertPlan, UpsertPlanner, UpsertRequest, UpsertStatement


ConfigManager.load()


class _SnapshotPlanner(UpsertPlanner):
    def plan(self, request: UpsertRequest) -> UpsertPlan:
        triple = Triple(s="urn:s", p="urn:p", o="literal")
        statement = UpsertStatement(
            sparql="DELETE { ?s ?p ?o } INSERT { ?s ?p ?o } WHERE { ?s ?p ?o }",
            key="s::urn:s",
            strategy="replace",
            triples=[triple],
            requires_snapshot=True,
        )
        return UpsertPlan(graph_iri="urn:test", statements=[statement], request_hash="hash")


class _FailingClient:
    def __init__(self) -> None:
        self.update_calls: list[str] = []
        self.construct_calls: list[str] = []
        self._first = True

    async def select(self, *args, **kwargs):  # pragma: no cover - not used here
        return {"bindings": []}

    async def construct(self, query: str, *, timeout: int | None = None, trace_id: str | None = None) -> dict:
        self.construct_calls.append(query)
        return {"turtle": '<urn:s> <urn:p> "literal" .'}

    async def update(self, query: str, *, timeout: int | None = None, trace_id: str | None = None) -> dict:
        self.update_calls.append(query)
        if self._first:
            self._first = False
            raise ExternalServiceError(ErrorCode.FUSEKI_QUERY_ERROR, "boom", details={})
        return {"status": 200}


class _StubAudit:
    async def log_operation_async(self, **kwargs):  # pragma: no cover
        return "audit-id"


@pytest.mark.asyncio
async def test_transaction_manager_rolls_back_on_failure() -> None:
    client = _FailingClient()
    manager = TransactionManager(planner=_SnapshotPlanner(), client=client, audit_logger=_StubAudit())
    request = UpsertRequest(graph={"name": "urn:test"}, triples=[Triple(s="urn:s", p="urn:p", o="literal")])

    with pytest.raises(ExternalServiceError):
        await manager.upsert(request, trace_id="trace")

    assert client.construct_calls, "Expected snapshot CONSTRUCT to be invoked"
    assert len(client.update_calls) >= 2, "Rollback update should be executed"
    assert "INSERT" in client.update_calls[-1]


