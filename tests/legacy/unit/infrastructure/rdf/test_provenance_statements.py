import pytest

from common.config import ConfigManager
from sf_rdf_acl.provenance.provenance import ProvenanceService
from sf_rdf_acl.query.dsl import GraphRef
from sf_rdf_acl.transaction.upsert import Provenance, Triple


ConfigManager.load()


class _StubClient:
    def __init__(self) -> None:
        self.last_update: str | None = None

    async def update(self, query: str, *, timeout: int | None = None, trace_id: str | None = None) -> None:
        self.last_update = query


@pytest.mark.asyncio
async def test_provenance_statements_cover_all_fields() -> None:
    client = _StubClient()
    service = ProvenanceService(client=client)
    graph = GraphRef(name="urn:test")
    triples = [
        Triple(s="urn:s", p="urn:p", o="urn:o"),
        Triple(s="urn:s2", p="urn:p2", o="literal", dtype="http://www.w3.org/2001/XMLSchema#string"),
    ]
    provenance = Provenance(evidence="source doc", confidence=0.85, source="http://source.example")
    metadata = {"pipeline": "daily", "attempt": 2, "success": True}

    result = await service.annotate(graph, triples, provenance, trace_id="trace-prov", metadata=metadata)

    assert result["count"] == len(result["statements"])
    statements = "\n".join(result["statements"])
    assert "prov:generatedAtTime" in statements
    assert "sf:evidence \"source doc\"" in statements
    assert "sf:confidence" in statements
    assert "prov:wasDerivedFrom <http://source.example>" in statements
    assert "sf:pipeline \"daily\"" in statements
    assert "sf:attempt 2" in statements
    assert "sf:success true" in statements
    assert client.last_update is not None and "INSERT DATA" in client.last_update


