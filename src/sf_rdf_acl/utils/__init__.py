"""RDF 领域通用工具方法。"""
from __future__ import annotations

from typing import Optional

from common.config.settings import Settings
from sf_rdf_acl.query.dsl import GraphRef


def resolve_graph_iri(graph: Optional[GraphRef], settings: Settings) -> Optional[str]:
    """根据 GraphRef 与全局配置生成命名图 IRI。"""

    if graph is None:
        return None
    if graph.name:
        return graph.name
    naming = settings.rdf.naming
    base = naming.graph_format.format(
        model=graph.model or "default",
        version=graph.version or "v1",
        env=graph.env or settings.app.env,
    )
    if graph.scenario_id:
        base = f"{base}:scenario:{graph.scenario_id}"
    return base
