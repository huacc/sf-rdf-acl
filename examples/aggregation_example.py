"""聚合查询示例

该示例演示如何使用 QueryDSL 与 SPARQLQueryBuilder 构建 COUNT + GROUP BY 等聚合查询，
并通过 FusekiClient 执行 SELECT 查询。

运行方式：
    python examples/aggregation_example.py

注意：
    - 本示例需要可访问的 Fuseki 服务；默认读取 sf-common 的配置，如需覆盖可修改相关配置文件。
    - 仅进行只读查询，不会修改数据。
"""
from __future__ import annotations

import asyncio
from typing import Any

from common.config import ConfigManager
from common.config.settings import Settings

from sf_rdf_acl import FusekiClient, SPARQLQueryBuilder
from sf_rdf_acl.query.dsl import QueryDSL, Aggregation, GroupBy


async def run_aggregation(settings: Settings) -> dict[str, Any]:
    """执行一次聚合查询并返回结果。

    参数：
        settings (Settings): 全局配置对象，包含 RDF 端点、数据集、重试/超时等设置。

    返回：
        dict[str, Any]: Fuseki SELECT 返回的 JSON 结果（含 `vars`、`bindings` 等字段）。
    """

    builder = SPARQLQueryBuilder()
    dsl = QueryDSL(
        type="entity",
        # 通过 expand 绑定 ?type 变量，便于按类型分组
        expand=["rdf:type as type"],
        aggregations=[Aggregation(function="COUNT", variable="?s", alias="?count")],
        group_by=GroupBy(variables=["?type"]),
    )
    sparql = builder.build_select(dsl)

    rdf = settings.rdf
    client = FusekiClient(endpoint=str(rdf.endpoint), dataset=rdf.dataset)
    return await client.select(sparql, trace_id="agg-example-001")


async def main() -> None:
    """脚本入口：加载配置、执行聚合查询并打印结果。"""

    ConfigManager.load()
    settings = ConfigManager.current().settings
    result = await run_aggregation(settings)

    print("Results:")
    for binding in result.get("bindings", []):
        # 结合 ResultMapper 可进一步规整结构，这里直接读原始字段
        print(binding)


if __name__ == "__main__":
    asyncio.run(main())
