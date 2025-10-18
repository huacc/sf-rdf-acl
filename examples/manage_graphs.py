"""Example: manage named graphs against the live Fuseki service."""
from __future__ import annotations

import asyncio

from common.exceptions import ExternalServiceError
from sf_rdf_acl import NamedGraphManager
from sf_rdf_acl.query.dsl import GraphRef

from helpers import build_fuseki_client, load_demo_config


async def main() -> None:
    load_demo_config()
    client = build_fuseki_client()
    manager = NamedGraphManager(client=client)
    graph = GraphRef(model="demo", version="v1", env="dev")

    created = await manager.create(graph, trace_id="demo-create")
    print("Graph create response:", created)

    try:
        preview = await manager.conditional_clear(
            graph,
            filters={"predicate": {"type": "uri", "value": "<http://semanticforge.ai/ontologies/core#status>"}},
            dry_run=True,
            trace_id="demo-clear-preview",
        )
        print("Dry-run preview:", preview)
    except ExternalServiceError as exc:
        print("conditional_clear failed:", getattr(exc, "details", {}))
        raise

    snapshot = await manager.snapshot(graph, trace_id="demo-snapshot")
    print("Snapshot summary:", snapshot)


if __name__ == "__main__":
    asyncio.run(main())


