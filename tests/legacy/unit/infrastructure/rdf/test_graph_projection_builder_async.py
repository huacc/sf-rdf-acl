import pytest

from common.config import ConfigManager
from common.config.settings import GraphConfig, GraphProjectionProfileConfig
from types import SimpleNamespace
from common.exceptions import APIError
from sf_rdf_acl.graph.projection import GraphProjectionBuilder
from sf_rdf_acl.query.dsl import GraphRef


class _StubClient:
    async def select(self, query: str, trace_id: str | None = None) -> dict[str, object]:
        return {
            "bindings": [
                {
                    "s": {"type": "uri", "value": "http://example.com/A"},
                    "p": {"type": "uri", "value": "http://semanticforge.ai/ontologies/core#relatesTo"},
                    "o": {"type": "uri", "value": "http://example.com/B"},
                    "sourceType": {"type": "uri", "value": "http://semanticforge.ai/ontologies/core#Entity"},
                    "targetType": {"type": "uri", "value": "http://semanticforge.ai/ontologies/core#Entity"},
                },
                {
                    "s": {"type": "uri", "value": "http://example.com/A"},
                    "p": {"type": "uri", "value": "http://semanticforge.ai/ontologies/core#relatesTo"},
                    "o": {"type": "literal", "value": "label", "datatype": "http://www.w3.org/2001/XMLSchema#string"},
                    "sourceType": {"type": "uri", "value": "http://semanticforge.ai/ontologies/core#Entity"},
                },
            ],
            "stats": {"status": 200},
        }


@pytest.mark.asyncio
async def test_project_from_graph_ref_filters_predicates():
    ConfigManager.load()
    base_settings = ConfigManager.current().settings
    profile = GraphProjectionProfileConfig(
        edge_predicates=["sf:relatesTo"],
        node_types=["http://semanticforge.ai/ontologies/core#Entity"],
        include_literals=True,
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
    payload = await builder.project(GraphRef(name="urn:test"), "default", config={"includeLiterals": True}, trace_id="trace-demo")
    assert payload.graph["nodes"]
    assert payload.stats["nodes"] == 2
    edges = payload.graph["edges"]
    assert any(edge.get("literal") == "label" for edge in edges)


@pytest.mark.asyncio
async def test_project_limit_violation_raises_api_error():
    ConfigManager.load()
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
    with pytest.raises(APIError):
        await builder.project(GraphRef(name="urn:test"), "default", config={"limit": 1}, trace_id="trace-limit")


