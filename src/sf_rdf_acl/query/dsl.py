"""查询 DSL 数据模型，服务于 SPARQL 构建与校验。

本模块采用 Pydantic v2 模型与标准 dataclass 混合的方式描述：
- Page/TimeWindow/Filter/QueryDSL/GraphRef/SPARQLRequest 使用 Pydantic；
- Aggregation/GroupBy 使用 dataclass，便于在 DSL 中自然表达聚合与分组定义。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Page(BaseModel):
    """分页参数配置。

    参数：
        size: 每页大小，范围 1~1000，默认 100；
        offset: 偏移量，None 或 0 表示第一页。
    """

    size: int = Field(ge=1, le=1000, default=100, description="每页大小，范围 1~1000")
    offset: int | None = Field(default=None, ge=0, description="偏移量，None 或 0 表示第一页")


class TimeWindow(BaseModel):
    """时间窗过滤配置。"""

    gte: datetime | None = None
    lte: datetime | None = None


class Filter(BaseModel):
    """字段过滤条件。

    参数：
        field: 谓词或变量名，如 "sf:name" 或 "?cnt"；
        op/operator: 过滤操作符，含 =, !=, >, >=, <, <=, in, range, contains, regex, exists, isNull；
        value: 过滤值，类型随 op 变化。
    """

    model_config = ConfigDict(populate_by_name=True)

    field: str
    op: Literal["=", "!=", ">", ">=", "<", "<=", "in", "range", "contains", "regex", "exists", "isNull"] = Field(
        alias="operator"
    )
    value: Any


@dataclass(frozen=True, slots=True)
class Aggregation:
    """聚合查询定义。

    属性说明：
        - function: COUNT/SUM/AVG/MIN/MAX/GROUP_CONCAT；
        - variable: 参与聚合的变量名（如 "?s"）；
        - alias: 结果别名（如 "?cnt"）；
        - distinct: 是否对聚合变量去重；
        - separator: GROUP_CONCAT 的分隔符。
    """

    function: Literal["COUNT", "SUM", "AVG", "MIN", "MAX", "GROUP_CONCAT"]
    variable: str
    alias: str | None = None
    distinct: bool = False
    separator: str | None = None


@dataclass(frozen=True, slots=True)
class GroupBy:
    """分组定义。"""

    variables: list[str]


class QueryDSL(BaseModel):
    """查询 DSL 根模型。"""

    type: Literal["entity", "relation", "event", "raw"]
    filters: list[Filter] = Field(default_factory=list)
    expand: list[str] = Field(default_factory=list)
    time_window: TimeWindow | None = None
    participants: list[str] = Field(default_factory=list)
    scenario_id: str | None = None
    include_subgraph: bool = False
    page: Page = Page()
    sort: dict | None = None
    prefixes: dict[str, str] | None = None
    # 聚合能力（P0）
    aggregations: list[Aggregation] | None = None
    group_by: GroupBy | None = None
    having: list[Filter] | None = None


class GraphRef(BaseModel):
    """命名图引用。"""

    name: str | None = None
    model: str | None = None
    version: str | None = None
    env: Literal["dev", "test", "prod"] | None = None
    scenario_id: str | None = None


class SPARQLRequest(BaseModel):
    """原始 SPARQL 请求模型。"""

    sparql: str
    type: Literal["select", "construct"] = "select"
    timeout: int | None = Field(default=30, ge=1, le=600)

