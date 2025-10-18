"""Example: project graph data from Fuseki into GraphJSON and edgelist."""
from __future__ import annotations

import asyncio

from sf_rdf_acl import GraphProjectionBuilder
from sf_rdf_acl.query.dsl import GraphRef

from helpers import build_fuseki_client, load_demo_config


async def main() -> None:
    load_demo_config()
    client = build_fuseki_client()
    builder = GraphProjectionBuilder(client=client)

    payload = await builder.project(
        source=GraphRef(model="demo", version="v1", env="dev"),
        profile="default",
        trace_id="demo-projection",
    )

    print("Graph nodes:", payload.graph)
    print("Edgelist:", payload.edgelist)
    print("Stats:", payload.stats)


if __name__ == "__main__":
    asyncio.run(main())
