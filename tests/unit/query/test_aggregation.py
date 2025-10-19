"""聚合查询构建器的单元测试，覆盖计划中的 P0 聚合能力。"""
from __future__ import annotations

import pytest

from sf_rdf_acl.query.builder import SPARQLQueryBuilder
from sf_rdf_acl.query.dsl import Aggregation, Filter, GroupBy, QueryDSL


@pytest.fixture(scope="function")
def builder() -> SPARQLQueryBuilder:
    """提供带默认前缀的查询构造器，保证每个测试隔离执行且不会污染状态。"""

    return SPARQLQueryBuilder()


def test_support_all_aggregations(builder: SPARQLQueryBuilder) -> None:
    """验证 COUNT/SUM/AVG/MIN/MAX/GROUP_CONCAT 六种聚合函数均能生成正确的 SELECT 片段。"""

    # 聚合函数 function 取值必须属于 COUNT/SUM/AVG/MIN/MAX/GROUP_CONCAT 范围，变量与别名均需以 "?" 开头。
    dsl = QueryDSL(
        type="entity",
        aggregations=[
            Aggregation(function="COUNT", variable="?s", alias="?total"),
            Aggregation(function="SUM", variable="?amount", alias="?sum_amount"),
            Aggregation(function="AVG", variable="?amount", alias="?avg_amount"),
            Aggregation(function="MIN", variable="?score", alias="?min_score"),
            Aggregation(function="MAX", variable="?score", alias="?max_score"),
            Aggregation(
                function="GROUP_CONCAT",
                variable="?label",
                alias="?labels",
                separator=", ",
            ),
        ],
    )

    sparql = builder.build_select(dsl)

    assert "COUNT(?s) AS ?total" in sparql, "COUNT 聚合缺失或格式不正确"
    assert "SUM(?amount) AS ?sum_amount" in sparql, "SUM 聚合缺失"
    assert "AVG(?amount) AS ?avg_amount" in sparql, "AVG 聚合缺失"
    assert "MIN(?score) AS ?min_score" in sparql, "MIN 聚合缺失"
    assert "MAX(?score) AS ?max_score" in sparql, "MAX 聚合缺失"
    assert "GROUP_CONCAT(?label" in sparql and "AS ?labels" in sparql, "GROUP_CONCAT 聚合缺失"


def test_group_by_and_having_clause(builder: SPARQLQueryBuilder) -> None:
    """验证 GROUP BY 与 HAVING 子句能够针对分组字段与聚合别名生成正确的语法。"""

    # COUNT 聚合启用 DISTINCT，分组字段列表长度不少于 1，可使用裸变量名或以问号开头的变量名。
    dsl = QueryDSL(
        type="entity",
        aggregations=[Aggregation(function="COUNT", variable="?s", alias="?cnt", distinct=True)],
        group_by=GroupBy(variables=["?type", "?category"]),
        having=[Filter(field="?cnt", operator=">", value=10)],
    )

    sparql = builder.build_select(dsl)

    assert "GROUP BY ?type ?category" in sparql, "GROUP BY 子句缺失或变量未全部保留"
    assert "HAVING" in sparql and "?cnt > 10" in sparql, "HAVING 子句未包含别名判断"
    assert "COUNT(DISTINCT ?s) AS ?cnt" in sparql, "DISTINCT 聚合未生效"


def test_group_concat_with_separator_and_distinct(builder: SPARQLQueryBuilder) -> None:
    """验证 GROUP_CONCAT 支持 DISTINCT 与分隔符参数，确保生成的语法包含正确的转义。"""

    # 分隔符推荐为短文本（<=16 个字符），distinct=True 表示对聚合变量去重后再拼接字符串。
    dsl = QueryDSL(
        type="entity",
        aggregations=[
            Aggregation(
                function="GROUP_CONCAT",
                variable="?name",
                alias="?names",
                distinct=True,
                separator=" | ",
            )
        ],
    )

    sparql = builder.build_select(dsl)

    assert "GROUP_CONCAT(DISTINCT ?name" in sparql, "GROUP_CONCAT 未应用 DISTINCT"
    assert 'SEPARATOR=" | "' in sparql, "GROUP_CONCAT 分隔符未正确生成"


def test_multiple_aggregations_and_group_columns(builder: SPARQLQueryBuilder) -> None:
    """验证聚合与分组字段同时存在时，SELECT 子句能够合并聚合表达式与分组变量。"""

    # 同时验证 MAX/MIN 聚合与混合分组变量，裸变量会由构造器自动补齐问号前缀。
    dsl = QueryDSL(
        type="entity",
        aggregations=[
            Aggregation(function="MAX", variable="?score", alias="?max_score"),
            Aggregation(function="MIN", variable="?score", alias="?min_score"),
        ],
        group_by=GroupBy(variables=["type", "?source"]),
        having=[Filter(field="?max_score", operator=">=", value=90)],
    )

    sparql = builder.build_select(dsl)

    flattened = sparql.replace('\n', ' ')
    assert "SELECT (MAX(?score) AS ?max_score) (MIN(?score) AS ?min_score) ?type ?source" in flattened, "SELECT 子句未包含全部聚合与分组字段"
    assert "GROUP BY ?type ?source" in sparql, "GROUP BY 子句缺失"
    assert "?max_score >= 90" in sparql, "HAVING 子句未保留比较条件"
