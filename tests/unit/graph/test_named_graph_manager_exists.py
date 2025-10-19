from __future__ import annotations

"""NamedGraphManager create 行为测试：已存在与新创建分支。"""

import pytest

from common.config import ConfigManager
from common.exceptions import ExternalServiceError
from common.exceptions.codes import ErrorCode
from sf_rdf_acl.graph.named_graph import NamedGraphManager
from sf_rdf_acl.query.dsl import GraphRef


ConfigManager.load()


class _CreateClient:
    def __init__(self, *, already_exists: bool) -> None:
        self.already_exists = already_exists
        self.update_calls: list[str] = []

    async def update(self, query: str, *, timeout: int | None = None, trace_id: str | None = None) -> dict:
        self.update_calls.append(query)
        if self.already_exists:
            raise ExternalServiceError(ErrorCode.FUSEKI_QUERY_ERROR, "Graph already exists", details={})
        return {"status": 200}


@pytest.mark.asyncio
async def test_create_returns_exists_when_backend_reports_already() -> None:
    manager = NamedGraphManager(client=_CreateClient(already_exists=True), settings=ConfigManager.current().settings)
    graph = GraphRef(name="urn:test")

    result = await manager.create(graph, trace_id="trace")

    assert result["status"] == "exists"


@pytest.mark.asyncio
async def test_create_success_returns_created() -> None:
    manager = NamedGraphManager(client=_CreateClient(already_exists=False), settings=ConfigManager.current().settings)
    graph = GraphRef(name="urn:test")

    result = await manager.create(graph, trace_id="trace")

    assert result["status"] == "created"

