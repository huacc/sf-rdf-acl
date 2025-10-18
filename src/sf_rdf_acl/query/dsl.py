"""查询 DSL 数据模型定义，供 SPARQL 构建器与后端服务共用。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Page(BaseModel):
    """
    分页参数配置。

    属性:
        size: 每页条数，例如 100，允许范围 1~1000。
        offset: 结果偏移量，例如 0 表示第一页，需大于等于 0。
    """

    size: int = Field(
        ge=1,
        le=1000,
        default=100,
        description="每页条数，例如 100，允许范围 1~1000",
    )
    offset: int | None = Field(
        default=None,
        ge=0,
        description="偏移量，例如 0 表示第一页，需大于等于 0",
    )


class TimeWindow(BaseModel):
    """
    时间窗口过滤条件。

    属性:
        gte: 起始时间，例如 datetime(2024, 1, 1, 0, 0, 0)。
        lte: 结束时间，例如 datetime(2024, 1, 31, 23, 59, 59)。
    """

    gte: datetime | None = None
    lte: datetime | None = None


class Filter(BaseModel):
    """
    字段过滤条件定义。

    属性:
        field: 谓词标识，例如 "sf:name" 或 "http://example.org/name"。
        op: 操作符，可选 "=", "!=", "in", "range", "contains", "regex", "exists", "isNull"。
        value: 过滤值，示例 "Alice"、["Alice", "Bob"]、{"gte": 1, "lte": 10}。
    """

    field: str
    op: Literal["=", "!=", "in", "range", "contains", "regex", "exists", "isNull"]
    value: Any


class QueryDSL(BaseModel):
    """
    查询 DSL 主体信息。

    属性:
        type: 查询类型，可选 "entity"、"relation"、"event"、"raw"。
        filters: Filter 列表，例如 [Filter(field="sf:name", op="=", value="Alice")]。
        expand: 展开字段列表，例如 ["sf:hasActor as actor"]。
        time_window: 时间窗口设置，例如 TimeWindow(gte=datetime(2024, 1, 1))。
        participants: 参与者筛选列表，例如 ["sf:Agent/Alice"]。
        scenario_id: 场景标识，例如 "scenario-001"，可为空。
        include_subgraph: 是否返回相关子图，示例 False。
        page: 分页配置，例如 Page(size=50, offset=0)。
        sort: 排序配置字典，例如 {"by": "__time", "order": "desc"}。
        prefixes: 自定义前缀映射，例如 {"ex": "http://example.org/"}。
    """

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


class GraphRef(BaseModel):
    """
    命名图引用描述。

    属性:
        name: 图名称，例如 "default"。
        model: 模型名称，例如 "sf-core"。
        version: 模型版本，例如 "v1.2.3"。
        env: 部署环境，可选 "dev"、"test"、"prod"。
        scenario_id: 场景标识，例如 "scenario-001"。
    """

    name: str | None = None
    model: str | None = None
    version: str | None = None
    env: Literal["dev", "test", "prod"] | None = None
    scenario_id: str | None = None


class SPARQLRequest(BaseModel):
    """
    原生 SPARQL 请求模型。

    属性:
        sparql: 查询文本，例如 "SELECT * WHERE { ?s ?p ?o }"。
        type: 查询类型，可选 "select" 或 "construct"。
        timeout: 超时秒数，例如 30，允许范围 1~600。
    """

    sparql: str
    type: Literal["select", "construct"] = "select"
    timeout: int | None = Field(default=30, ge=1, le=600)
