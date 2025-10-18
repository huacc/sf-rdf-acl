from sf_rdf_acl.query.builder import SPARQLQueryBuilder
from sf_rdf_acl.query.dsl import QueryDSL


def test_expand_alias_and_sort_column() -> None:
    builder = SPARQLQueryBuilder(default_prefixes={"ex": "http://example.com/"})
    dsl = QueryDSL(
        type="entity",
        expand=["ex:knows as ?friend"],
        sort={"by": "?friend", "order": "desc"},
    )

    query = builder.build_select(dsl)

    assert "OPTIONAL { ?s ex:knows ?friend . }" in query
    assert "SELECT DISTINCT ?s ?p ?o ?friend" in query.replace("\n", " ")
    assert "ORDER BY DESC(?friend) ?s" in query


