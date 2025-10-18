from datetime import datetime

from sf_rdf_acl.converter.result_mapper import ResultMapper


def test_map_bindings_casts_core_types() -> None:
    mapper = ResultMapper()
    bindings = [
        {
            "name": {
                "type": "literal",
                "value": "Alice",
                "datatype": "http://www.w3.org/2001/XMLSchema#string",
            },
            "age": {
                "type": "literal",
                "value": "42",
                "datatype": "http://www.w3.org/2001/XMLSchema#integer",
            },
            "active": {
                "type": "literal",
                "value": "true",
                "datatype": "http://www.w3.org/2001/XMLSchema#boolean",
            },
            "ts": {
                "type": "literal",
                "value": "2024-01-01T08:00:00Z",
                "datatype": "http://www.w3.org/2001/XMLSchema#dateTime",
            },
            "uri": {
                "type": "uri",
                "value": "http://example.com/Alice",
            },
        }
    ]

    rows = mapper.map_bindings(["name", "age", "active", "ts", "uri"], bindings)

    first = rows[0]
    assert first["age"]["value"] == 42
    assert first["active"]["value"] is True
    assert first["name"]["value"] == "Alice"
    assert first["ts"]["value"].startswith("2024-01-01T08:00:00")
    assert first["uri"]["value"] == "http://example.com/Alice"


def test_map_bindings_handles_missing_cells() -> None:
    mapper = ResultMapper()

    rows = mapper.map_bindings(["col"], [{}])

    assert rows == [{"col": None}]


