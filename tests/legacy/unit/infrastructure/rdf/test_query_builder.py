import re
from datetime import datetime

from sf_rdf_acl.query.builder import SPARQLQueryBuilder
from sf_rdf_acl.query.dsl import Filter, Page, QueryDSL, TimeWindow


def test_build_select_with_filters_and_expand() -> None:
    builder = SPARQLQueryBuilder(default_prefixes={"ex": "http://example.com/"})
    dsl = QueryDSL(
        type="entity",
        filters=[Filter(field="ex:type", op="=", value="ex:Person")],
        expand=["ex:knows as ?friend"],
        page=Page(size=10, offset=5),
        sort={"by": "?friend", "order": "desc"},
    )
    query = builder.build_select(dsl, graph="urn:test")

    assert "PREFIX ex:" in query
    assert "GRAPH <urn:test>" in query
    assert "FILTER(?f0 = ex:Person)" in query
    assert "?s ex:knows ?friend" in query
    assert "ORDER BY DESC(?friend)" in query
    assert "LIMIT 10" in query
    assert "OFFSET 5" in query


def test_build_select_with_time_window() -> None:
    builder = SPARQLQueryBuilder(default_prefixes={"ex": "http://example.com/"})
    window = TimeWindow(gte=datetime(2024, 1, 1), lte=datetime(2024, 1, 31))
    dsl = QueryDSL(type="entity", time_window=window)

    query = builder.build_select(dsl)

    assert "?s ?p ?o" in query
    assert "?__time" in query
    assert "FILTER(?__time >=" in query
    assert "FILTER(?__time <=" in query


def test_build_construct_uses_construct_block() -> None:
    builder = SPARQLQueryBuilder()
    dsl = QueryDSL(type="entity")

    query = builder.build_construct(dsl)

    assert query.startswith("PREFIX")
    assert "CONSTRUCT" in query
    assert re.search(r"CONSTRUCT\s*{\s*\?s \?p \?o .\s*}", query)





