from __future__ import annotations

"""GraphProjectionBuilder 过滤规则与限制策略测试。"""

import pytest

from common.config import ConfigManager
from common.config.settings import GraphConfig, GraphProjectionProfileConfig
from types import SimpleNamespace
from sf_rdf_acl.graph.projection import GraphProjectionBuilder
from sf_rdf_acl.query.dsl import GraphRef, QueryDSL


ConfigManager.load()


class _StubClient:
    def __init__(self) -> None:
        self.last_query: str | None = None

    async def select(self, query: str, *, timeout: int | None = None, trace_id: str | None = None) -> dict:
        self.last_query = query
        return {
            "bindings": [
                {
                    "s": {"type": "uri", "value": "urn:a"},
                    "p": {"type": "uri", "value": "http://semanticforge.ai/ontologies/core#relatesTo"},
                    "o": {"type": "uri", "value": "urn:b"},
                    "sourceType": {"type": "uri", "value": "ex:Node"},
                    "targetType": {"type": "uri", "value": "ex:Node"},
                },
                {
                    "s": {"type": "uri", "value": "urn:a"},
                    "p": {"type": "uri", "value": "http://semanticforge.ai/ontologies/core#filtered"},
                    "o": {"type": "literal", "value": "label"},
                },
            ],
            "stats": {"status": 200},
        }


@pytest.mark.asyncio
async def test_projection_filters_edges_and_literals() -> None:
    base_settings = ConfigManager.current().settings
    profile = GraphProjectionProfileConfig(
        edge_predicates=["sf:relatesTo"],
        include_literals=False,
        limit=100,
    )
    settings = SimpleNamespace(
        graph=GraphConfig(projection_profiles={"default": profile}),
        rdf=base_settings.rdf,
        security=base_settings.security,
        app=base_settings.app,
        postgres=getattr(base_settings, "postgres", SimpleNamespace(dsn="postgres://", schema="public")),
    )
    builder = GraphProjectionBuilder(client=_StubClient(), settings=settings)
    result = await builder.to_graphjson(
        GraphRef(name="urn:test"),
        profile="default",
        config={
            "edgePredicates": ["sf:relatesTo"],
            "includeLiterals": False,
            "limit": 10,
        },
        trace_id="trace",
    )

    assert result["nodes"]
    assert result["edges"] == [
        {"source": "urn:a", "target": "urn:b", "predicate": "http://semanticforge.ai/ontologies/core#relatesTo"}
    ]


@pytest.mark.asyncio
async def test_projection_limit_violation_raises_error() -> None:
    base_settings = ConfigManager.current().settings
    profile = GraphProjectionProfileConfig(limit=1)
    settings = SimpleNamespace(
        graph=GraphConfig(projection_profiles={"default": profile}),
        rdf=base_settings.rdf,
        security=base_settings.security,
        app=base_settings.app,
        postgres=getattr(base_settings, "postgres", SimpleNamespace(dsn="postgres://", schema="public")),
    )
    builder = GraphProjectionBuilder(client=_StubClient(), settings=settings)
    with pytest.raises(Exception):
        await builder.to_graphjson(
            GraphRef(name="urn:test"),
            profile="default",
            config={"limit": 1, "edgePredicates": ["ex:allowed"]},
            trace_id="trace",
        )

