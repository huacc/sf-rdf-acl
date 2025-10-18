"""Example: write RDF* provenance annotations to the live dataset."""
from __future__ import annotations

import asyncio

from sf_rdf_acl import ProvenanceService, Triple
from sf_rdf_acl.query.dsl import GraphRef
from sf_rdf_acl.transaction.upsert import Provenance

from helpers import build_fuseki_client, load_demo_config


async def main() -> None:
    load_demo_config()
    client = build_fuseki_client()
    service = ProvenanceService(client=client)

    triples = [
        Triple(
            s="http://example.com/entity/123",
            p="http://semanticforge.ai/ontologies/core#status",
            o="active",
        )
    ]
    provenance = Provenance(
        evidence="business-rule-approval",
        confidence=0.95,
        source="http://example.com/source",
    )

    result = await service.annotate(
        graph=GraphRef(model="demo", version="v1", env="dev"),
        triples=triples,
        provenance=provenance,
        trace_id="demo-provenance",
        metadata={"workflowId": "wf-001", "approved": True},
    )
    print("Statements written:")
    for line in result["statements"]:
        print("  ", line)
    print("Summary:", {k: v for k, v in result.items() if k != "statements"})


if __name__ == "__main__":
    asyncio.run(main())

