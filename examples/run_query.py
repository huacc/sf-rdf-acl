"""Example: execute a SELECT query against the live Fuseki endpoint."""
from __future__ import annotations

import asyncio

from sf_rdf_acl import Filter, QueryDSL, ResultMapper, SPARQLQueryBuilder

from helpers import build_fuseki_client, load_demo_config


async def main() -> None:
    load_demo_config()
    client = build_fuseki_client()

    dsl = QueryDSL(
        type="entity",
        filters=[
            Filter(field="rdf:type", op="=", value="sf:Entity"),
            Filter(field="sf:status", op="in", value=["active", "pending"]),
        ],
        expand=["rdfs:label as ?label"],
        page={"size": 10, "offset": 0},
    )

    builder = SPARQLQueryBuilder(default_prefixes={"sf": "http://semanticforge.ai/ontologies/core#"})
    sparql = builder.build_select(dsl, graph="urn:sf:demo:v1:dev")
    print("Generated SPARQL:\n", sparql, "\n", sep="")

    raw = await client.select(sparql, trace_id="demo-select")
    mapped = ResultMapper().map_bindings(raw.get("vars", []), raw.get("bindings", []))
    if not mapped:
        print("No rows matched the query.")
    else:
        print("Query results:")
        for row in mapped:
            print(row)


if __name__ == "__main__":
    asyncio.run(main())

