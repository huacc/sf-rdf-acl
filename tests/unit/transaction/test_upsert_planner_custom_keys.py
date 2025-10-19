from __future__ import annotations

"""UpsertPlanner 自定义主键组合计划生成测试。"""

import pytest

from common.config import ConfigManager
from sf_rdf_acl.transaction.upsert import Triple, UpsertPlanner, UpsertRequest


ConfigManager.load()


def test_custom_key_statement_contains_all_fields() -> None:
    planner = UpsertPlanner()
    request = UpsertRequest(
        graph={"name": "urn:sf:test"},
        triples=[
            Triple(s="urn:s", p="urn:p", o="literal"),
            Triple(s="urn:s", p="urn:label", o="Name", lang="en"),
        ],
        upsert_key="custom",
        custom_key_fields=["s", "p", "o"],
        merge_strategy="replace",
    )

    plan = planner.plan(request)

    assert plan.graph_iri == "urn:sf:test"
    assert len(plan.statements) == 2
    keys = {statement.key for statement in plan.statements}
    assert "custom[s,p,o]::s::urn:s::p::urn:p::o::literal" in keys
    assert "custom[s,p,o]::s::urn:s::p::urn:label::o::Name" in keys


def test_custom_key_with_invalid_field_raises() -> None:
    planner = UpsertPlanner()
    request = UpsertRequest(
        graph={"name": "urn:sf:test"},
        triples=[Triple(s="urn:s", p="urn:p", o="literal")],
        upsert_key="custom",
        custom_key_fields=["s", "x"],
    )

    with pytest.raises(ValueError):
        planner.plan(request)

