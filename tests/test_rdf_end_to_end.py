from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from common.config import ConfigManager
from common.config.settings import Settings
from common.exceptions import ExternalServiceError

from sf_rdf_acl import (
    FusekiClient,
    GraphProjectionBuilder,
    NamedGraphManager,
    TransactionManager,
    UpsertRequest,
    Triple,
    ProvenanceService,
)
from sf_rdf_acl.query.dsl import GraphRef
from sf_rdf_acl.transaction.upsert import Provenance
from sf_rdf_acl.utils import resolve_graph_iri


@pytest.fixture(scope="session")
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def settings() -> Settings:
    return ConfigManager.current().settings


@pytest.fixture(scope="session")
def fuseki_client(settings: Settings) -> FusekiClient:
    rdf = settings.rdf
    security = settings.security
    auth: tuple[str, str] | None = None
    if rdf.auth.username and rdf.auth.password:
        auth = (rdf.auth.username, rdf.auth.password)
    retry_policy = rdf.retries.model_dump()
    breaker_policy = rdf.circuit_breaker.model_dump(by_alias=True)
    return FusekiClient(
        endpoint=str(rdf.endpoint),
        dataset=rdf.dataset,
        auth=auth,
        trace_header=security.trace_header,
        default_timeout=rdf.timeout.default,
        max_timeout=rdf.timeout.max,
        retry_policy=retry_policy,
        circuit_breaker=breaker_policy,
    )


@pytest_asyncio.fixture
async def graph_context(settings: Settings):
    manager = NamedGraphManager()
    unique = uuid.uuid4().hex
    graph_ref = GraphRef(model="e2e", version=f"v{unique[:8]}", env="dev")
    graph_iri = resolve_graph_iri(graph_ref, settings)
    trace_id = f"trace-e2e-{unique}"
    await manager.create(graph_ref, trace_id=trace_id)
    try:
        await manager.clear(graph_ref, trace_id=f"{trace_id}-init")
    except ExternalServiceError:
        pass
    try:
        yield {
            "graph_ref": graph_ref,
            "graph_iri": graph_iri,
            "trace_id": trace_id,
            "manager": manager,
        }
    finally:
        try:
            await manager.clear(graph_ref, trace_id=f"{trace_id}-final")
        except ExternalServiceError:
            pass


@pytest.mark.asyncio
async def test_upsert_and_projection_roundtrip(graph_context, fuseki_client):
    ctx = graph_context
    graph_ref: GraphRef = ctx["graph_ref"]
    trace_id: str = ctx["trace_id"]

    entity_uri = f"http://example.com/e2e/entity/{uuid.uuid4().hex}"
    related_uri = f"http://example.com/e2e/entity/{uuid.uuid4().hex}"
    status_predicate = "http://semanticforge.ai/ontologies/core#status"
    relates_to = "http://semanticforge.ai/ontologies/core#relatesTo"

    manager = TransactionManager()
    request = UpsertRequest(
        graph=graph_ref,
        triples=[
            Triple(s=entity_uri, p="http://www.w3.org/1999/02/22-rdf-syntax-ns#type", o="http://semanticforge.ai/ontologies/core#Entity"),
            Triple(s=entity_uri, p=status_predicate, o="active"),
            Triple(s=entity_uri, p=relates_to, o=related_uri),
            Triple(s=related_uri, p="http://www.w3.org/1999/02/22-rdf-syntax-ns#type", o="http://semanticforge.ai/ontologies/core#Entity"),
            Triple(s=related_uri, p=status_predicate, o="pending"),
        ],
        upsert_key="s",
        merge_strategy="replace",
    )

    result = await manager.upsert(request, trace_id=f"{trace_id}-upsert", actor="pytest")
    assert result["applied"] == 5
    assert result["conflicts"] == []

    select_query = f"""
    SELECT ?p ?o WHERE {{
      GRAPH <{ctx['graph_iri']}> {{
        <{entity_uri}> ?p ?o .
      }}
    }}
    """
    raw = await fuseki_client.select(select_query, trace_id=f"{trace_id}-select")
    values = {(binding["p"]["value"], binding["o"]["value"]) for binding in raw["bindings"]}
    assert (status_predicate, "active") in values
    assert (relates_to, related_uri) in values

    projection = GraphProjectionBuilder(client=fuseki_client)
    payload = await projection.project(graph_ref, profile="default", trace_id=f"{trace_id}-project")
    assert payload.graph["nodes"], "projection should yield nodes"
    assert payload.graph["edges"], "projection should yield edges"
    edge_targets = {edge["target"] for edge in payload.graph["edges"]}
    assert related_uri in edge_targets


@pytest.mark.asyncio
async def test_snapshot_and_conditional_clear(graph_context, fuseki_client):
    ctx = graph_context
    graph_ref: GraphRef = ctx["graph_ref"]
    trace_id: str = ctx["trace_id"]
    subject = f"http://example.com/e2e/snapshot/{uuid.uuid4().hex}"

    manager = TransactionManager()
    request = UpsertRequest(
        graph=graph_ref,
        triples=[
            Triple(s=subject, p="http://www.w3.org/2000/01/rdf-schema#label", o="Snapshot target"),
        ],
        upsert_key="s",
        merge_strategy="replace",
    )
    await manager.upsert(request, trace_id=f"{trace_id}-upsert", actor="pytest")

    named_manager = NamedGraphManager()
    snapshot = await named_manager.snapshot(graph_ref, trace_id=f"{trace_id}-snapshot")
    assert snapshot["snapshotGraph"].startswith("urn:sf:")

    snapshot_query = f"""
    SELECT ?o WHERE {{
      GRAPH <{snapshot['snapshotGraph']}> {{ <{subject}> ?p ?o }}
    }}
    """
    snapshot_raw = await fuseki_client.select(snapshot_query, trace_id=f"{trace_id}-snapshot-check")
    assert any(binding["o"]["value"] == "Snapshot target" for binding in snapshot_raw["bindings"])

    clear_result = await named_manager.conditional_clear(
        graph_ref,
        filters={"subject": subject},
        dry_run=False,
        trace_id=f"{trace_id}-clear",
    )
    assert clear_result["executed"] is True

    confirm_query = f"""
    SELECT ?o WHERE {{
      GRAPH <{ctx['graph_iri']}> {{
        <{subject}> ?p ?o .
      }}
    }}
    LIMIT 1
    """
    confirm_raw = await fuseki_client.select(confirm_query, trace_id=f"{trace_id}-confirm")
    assert not confirm_raw["bindings"], "original graph should be empty after conditional clear"

    await fuseki_client.update(
        f"CLEAR GRAPH <{snapshot['snapshotGraph']}>",
        trace_id=f"{trace_id}-snapshot-clear",
    )


@pytest.mark.asyncio
async def test_provenance_annotation(graph_context, fuseki_client):
    ctx = graph_context
    graph_ref: GraphRef = ctx["graph_ref"]
    trace_id: str = ctx["trace_id"]

    subject = f"http://example.com/e2e/provenance/{uuid.uuid4().hex}"
    predicate = "http://semanticforge.ai/ontologies/core#status"
    base_triple = Triple(s=subject, p=predicate, o="verified")

    manager = TransactionManager()
    await manager.upsert(
        UpsertRequest(
            graph=graph_ref,
            triples=[base_triple],
            upsert_key="s+p",
            merge_strategy="replace",
        ),
        trace_id=f"{trace_id}-upsert",
        actor="pytest",
    )

    provenance_service = ProvenanceService()
    provenance = Provenance(evidence="manual-review", confidence=0.98, source="http://example.com/source")
    await provenance_service.annotate(
        graph_ref,
        triples=[base_triple],
        provenance=provenance,
        trace_id=f"{trace_id}-prov",
        metadata={"operator": "pytest", "batch": datetime.now(timezone.utc).date().isoformat()},
    )

    construct_query = f"""
    PREFIX prov: <http://www.w3.org/ns/prov#>
    PREFIX sf: <http://semanticforge.ai/ontologies/core#>
    PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
    CONSTRUCT {{
      << <{subject}> <{predicate}> "verified" >> ?p ?o .
    }} WHERE {{
      GRAPH <{ctx['graph_iri']}> {{
        << <{subject}> <{predicate}> "verified" >> ?p ?o .
      }}
    }}
    """
    turtle = await fuseki_client.construct(construct_query, trace_id=f"{trace_id}-construct")
    text = turtle["turtle"]

    normalized = ' '.join(text.split())
    assert 'prov:generatedAtTime "' in normalized
    assert 'sf:evidence "manual-review"' in normalized
    assert 'sf:confidence' in normalized and '0.98' in normalized
    assert 'prov:wasDerivedFrom <http://example.com/source>' in normalized
    assert 'sf:operator "pytest"' in normalized

