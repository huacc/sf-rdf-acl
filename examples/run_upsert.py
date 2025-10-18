"""Example: perform an UPSERT against the live Fuseki dataset."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sf_rdf_acl import TransactionManager, Triple, UpsertPlanner, UpsertRequest
from sf_rdf_acl.query.dsl import GraphRef

from helpers import build_fuseki_client, load_demo_config

SF_BASE = "http://semanticforge.ai/ontologies/core#"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


async def main() -> None:
    load_demo_config()
    client = build_fuseki_client()
    manager = TransactionManager(planner=UpsertPlanner(), client=client)

    occurred_at = datetime.now(timezone.utc)

    request = UpsertRequest(
        graph=GraphRef(model="demo", version="v1", env="dev"),
        triples=[
            Triple(
                s="http://example.com/entity/123",
                p=RDF_TYPE,
                o=SF_BASE + "Entity",
            ),
            Triple(
                s="http://example.com/entity/123",
                p=SF_BASE + "status",
                o="active",
            ),
            Triple(
                s="http://example.com/entity/123",
                p=SF_BASE + "updatedAt",
                o=occurred_at.isoformat(),
                dtype="http://www.w3.org/2001/XMLSchema#dateTime",
            ),
            Triple(
                s="http://example.com/entity/123",
                p=RDFS_LABEL,
                o="Demo entity",
            ),
            Triple(
                s="http://example.com/entity/123",
                p=SF_BASE + "relatesTo",
                o="http://example.com/entity/456",
            ),
            Triple(
                s="http://example.com/entity/456",
                p=RDF_TYPE,
                o=SF_BASE + "Entity",
            ),
            Triple(
                s="http://example.com/entity/456",
                p=SF_BASE + "status",
                o="pending",
            ),
            Triple(
                s="http://example.com/entity/456",
                p=RDFS_LABEL,
                o="Related entity",
            ),
        ],
        upsert_key="s",
        merge_strategy="replace",
    )

    result = await manager.upsert(request, trace_id="demo-upsert", actor="demo-script")
    print("Upsert result:", result)


if __name__ == "__main__":
    asyncio.run(main())
