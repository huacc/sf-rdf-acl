from __future__ import annotations

import asyncio
import pytest

from common.config import ConfigManager
from sf_rdf_acl.graph.named_graph import NamedGraphManager
from sf_rdf_acl.query.dsl import GraphRef
from common.exceptions import ExternalServiceError


class _StubClient:
    def __init__(self) -> None:
        self.updates: list[str] = []
        self.raise_exc: ExternalServiceError | None = None

    async def select(self, query: str, *, timeout: int | None = None, trace_id: str | None = None) -> dict:
        # return a count of 1 for conditional clear
        return {"bindings": [{"count": {"value": "1"}}]}

    async def update(self, update: str, *, timeout: int | None = None, trace_id: str | None = None) -> dict:
        if self.raise_exc:
            raise self.raise_exc
        self.updates.append(update)
        return {"status": 200}


def test_create_returns_exists_on_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ConfigManager.current().settings
    stub = _StubClient()
    mgr = NamedGraphManager(client=stub, settings=cfg)

    # simulate backend saying already exists
    stub.raise_exc = ExternalServiceError(code=5002, message="Already exists")  # type: ignore[arg-type]
    result = asyncio.run(mgr.create(GraphRef(name="urn:sf:test"), trace_id="t"))
    assert result["status"] == "exists"


def test_create_raises_for_other_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ConfigManager.current().settings
    stub = _StubClient()
    mgr = NamedGraphManager(client=stub, settings=cfg)

    # simulate non-existence related error
    stub.raise_exc = ExternalServiceError(code=5001, message="boom")  # type: ignore[arg-type]
    with pytest.raises(ExternalServiceError):
        asyncio.run(mgr.create(GraphRef(name="urn:sf:err"), trace_id="t"))


def test_conditional_clear_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = ConfigManager.current().settings
    stub = _StubClient()
    mgr = NamedGraphManager(client=stub, settings=cfg)

    # cause update to raise when not dry-run with matched > 0
    stub.raise_exc = ExternalServiceError(code=5001, message="delete fail")  # type: ignore[arg-type]
    with pytest.raises(ExternalServiceError):
        asyncio.run(mgr.conditional_clear(GraphRef(name="urn:sf:test"), filters={"s": "?s"}, dry_run=False, trace_id="t"))
