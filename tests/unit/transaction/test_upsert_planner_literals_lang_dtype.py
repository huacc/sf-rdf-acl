from __future__ import annotations

"""UpsertPlanner 字面量的类型与语言标记渲染测试。"""

from common.config import ConfigManager
from sf_rdf_acl.transaction.upsert import Triple, UpsertPlanner, UpsertRequest


ConfigManager.load()


def test_literal_rendering_with_dtype_and_lang() -> None:
    planner = UpsertPlanner()
    request = UpsertRequest(
        graph={"name": "urn:sf:test"},
        triples=[
            Triple(s="urn:s", p="urn:typed", o="42", dtype="http://www.w3.org/2001/XMLSchema#integer"),
            Triple(s="urn:s", p="urn:lang", o="bonjour", lang="fr"),
            Triple(s="urn:s", p="urn:iri", o="http://example.com/obj"),
        ],
        upsert_key="s",
        merge_strategy="append",
    )

    plan = planner.plan(request)

    assert len(plan.statements) == 1
    sparql = plan.statements[0].sparql
    assert '"42"^^<http://www.w3.org/2001/XMLSchema#integer>' in sparql
    assert '"bonjour"@fr' in sparql
    assert '<http://example.com/obj>' in sparql

