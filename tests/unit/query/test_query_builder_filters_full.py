from __future__ import annotations

"""SPARQLQueryBuilder 过滤器全集测试。"""

from datetime import datetime

import pytest

from sf_rdf_acl.query.builder import SPARQLQueryBuilder
from sf_rdf_acl.query.dsl import Filter, Page, QueryDSL, TimeWindow


def _builder() -> SPARQLQueryBuilder:
    return SPARQLQueryBuilder(default_prefixes={"ex": "http://example.com/"})


def test_build_select_with_all_supported_filters() -> None:
    builder = _builder()
    dsl = QueryDSL(
        type="entity",
        filters=[
            Filter(field="ex:name", op="exists", value=True),
            Filter(field="ex:label", op="isNull", value=True),
            Filter(field="ex:status", op="in", value=["open", "closed"]),
            Filter(field="ex:score", op="range", value={"gte": 1, "lte": 10}),
            Filter(field="ex:description", op="contains", value="Net"),
            Filter(field="ex:pattern", op="regex", value="^A"),
        ],
        page=Page(size=5, offset=0),
        time_window=None,
    )

    query = builder.build_select(dsl)

    assert "FILTER(BOUND(?f0))" in query
    assert "FILTER(!BOUND(?f1))" in query
    assert "FILTER(?f2 IN (\"open\", \"closed\"))" in query
    assert "FILTER(?f3 >= 1)" in query and "FILTER(?f3 <= 10)" in query
    assert "FILTER(CONTAINS(LCASE(STR(?f4)), LCASE(\"Net\")))" in query
    assert "FILTER(REGEX(STR(?f5), \"^A\", \"i\"))" in query
    assert "LIMIT 5" in query


def test_build_select_with_time_window_and_literals() -> None:
    builder = _builder()
    dsl = QueryDSL(
        type="event",
        time_window=TimeWindow(gte=datetime(2024, 1, 1), lte=datetime(2024, 12, 31)),
        filters=[Filter(field="ex:title", op="=", value="Alpha")],
    )

    query = builder.build_select(dsl)

    assert "prov:generatedAtTime" in query
    assert "FILTER(?__time >= \"2024-01-01T00:00:00" in query
    assert "FILTER(?__time <= \"2024-12-31T00:00:00" in query


def test_unknown_prefix_raises_value_error() -> None:
    builder = _builder()
    dsl = QueryDSL(type="entity", filters=[Filter(field="unknown:attr", op="=", value="x")])

    with pytest.raises(ValueError):
        builder.build_select(dsl)

