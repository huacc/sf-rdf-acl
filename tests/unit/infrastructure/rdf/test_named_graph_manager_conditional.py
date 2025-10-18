import pytest

from common.config import ConfigManager
from sf_rdf_acl.graph.named_graph import NamedGraphManager
from sf_rdf_acl.query.dsl import GraphRef


ConfigManager.load()


class _StubClient:
    def __init__(self, count: int) -> None:
        self.count = count
        self.last_update: str | None = None

    async def select(self, query: str, *, timeout: int | None = None, trace_id: str | None = None) -> dict:
        self.last_select = query
        return {"bindings": [{"count": {"value": str(self.count)}}]}

    async def update(self, query: str, *, timeout: int | None = None, trace_id: str | None = None) -> None:
        self.last_update = query


@pytest.mark.asyncio
async def test_conditional_clear_dry_run_returns_preview() -> None:
    manager = NamedGraphManager(client=_StubClient(3), settings=ConfigManager.current().settings)
    graph = GraphRef(name="urn:test")

    result = await manager.conditional_clear(graph, filters={"subject": "urn:s"}, dry_run=True, trace_id="trace")

    assert result["graph"] == "urn:test"
    assert result["matched"] == 3
    assert result["executed"] is False
    assert result["pattern"].startswith("urn:s")
    assert manager._client.last_update is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_conditional_clear_executes_delete_when_not_dry_run() -> None:
    client = _StubClient(2)
    manager = NamedGraphManager(client=client, settings=ConfigManager.current().settings)
    graph = GraphRef(name="urn:test")

    result = await manager.conditional_clear(graph, filters={"predicate": "ex:related"}, dry_run=False, trace_id="trace")

    assert result["matched"] == 2
    assert result["executed"] is True
    assert client.last_update is not None
    assert "DELETE" in client.last_update and "WHERE" in client.last_update


