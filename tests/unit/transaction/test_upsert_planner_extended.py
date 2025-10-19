from __future__ import annotations

"""UpsertPlanner 替换策略基本路径测试。"""

import pytest

from common.config import ConfigManager
from sf_rdf_acl.transaction.upsert import Triple, UpsertPlanner, UpsertRequest


ConfigManager.load()


def test_plan_replace_by_subject_predicate_generates_statement():
    planner = UpsertPlanner()
    request = UpsertRequest(
        graph={"name": "urn:sf:test"},
        triples=[
            Triple(s="http://example.com/a", p="http://example.com/name", o="Alice"),
        ],
        upsert_key="s+p",
        merge_strategy="replace",
    )

    plan = planner.plan(request)

    assert plan.graph_iri == "urn:sf:test"
    assert len(plan.statements) == 1
    statement = plan.statements[0]
    assert statement.strategy == "replace"
    assert "DELETE" in statement.sparql
    assert "INSERT" in statement.sparql
    assert "http://example.com/a" in statement.sparql
    assert "Alice" in statement.sparql

