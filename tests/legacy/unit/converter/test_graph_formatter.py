from __future__ import annotations

from sf_rdf_acl.converter.graph_formatter import GraphFormatter


def test_to_turtle_roundtrip() -> None:
    fmt = GraphFormatter()
    turtle = "@prefix ex: <http://example.com/> . ex:a ex:p ex:b .\n"
    assert fmt.to_turtle(turtle) == turtle


def test_to_turtle_empty_string() -> None:
    fmt = GraphFormatter()
    assert fmt.to_turtle("") == ""

