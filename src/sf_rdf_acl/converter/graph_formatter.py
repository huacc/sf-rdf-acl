"""Graph formatting utilities for RDF outputs."""
from __future__ import annotations


class GraphFormatter:
    """Provide helpers for formatting graph payloads."""

    def to_turtle(self, graph_ttl: str) -> str:
        """Return the supplied Turtle snippet untouched.

        Args:
            graph_ttl: Turtle string returned by Fuseki, for example::

                @prefix ex: <http://example.com/> .
                ex:foo ex:bar ex:baz .

        Returns:
            The Turtle text as-is; downstream callers may add validation or
            canonicalisation when needed.
        """

        return graph_ttl
