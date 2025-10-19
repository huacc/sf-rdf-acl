"""端到端示例：使用内存版 Fuseki 客户端串联 RDF ACL 的核心流程。"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# 将仓库内共享模块及当前包源码加入 sys.path，确保示例脚本可直接运行。
PROJECTS_ROOT = Path(__file__).resolve().parents[2]
EXTRA_PATHS = [
    PROJECTS_ROOT / "sf-rdf-acl" / "src",
    PROJECTS_ROOT / "sf-common" / "src",
    PROJECTS_ROOT / "sf-api-schemas" / "src",
]
for _path in EXTRA_PATHS:
    if _path.exists() and str(_path) not in sys.path:
        sys.path.append(str(_path))

from common.config import ConfigManager
from sf_rdf_acl import (
    GraphFormatter,
    GraphProjectionBuilder,
    NamedGraphManager,
    ProvenanceService,
    ResultMapper,
    TransactionManager,
    Triple,
    UpsertPlanner,
    UpsertRequest,
)
from sf_rdf_acl.transaction.upsert import Provenance
from sf_rdf_acl.query.dsl import GraphRef
from helpers import build_fuseki_client, load_demo_config
SF = "http://semanticforge.ai/ontologies/core#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
PROV_GENERATED_AT = "http://www.w3.org/ns/prov#generatedAtTime"


async def main() -> None:
    """构造“产线质检”故事线，演示写入、查询、投影、溯源的完整链路。"""

    # 1) 载入示例配置，确保命名图解析与投影配置与真实环境一致。
    load_demo_config()
    settings = ConfigManager.current().settings

    # 2) 准备内存版 Fuseki 客户端，并为各个服务注入同一个客户端实例。
    client = build_fuseki_client()
    graph_ref = GraphRef(model="demo", version="v1", env="dev", scenario_id="quality")
    planner = UpsertPlanner(settings=settings)
    tx_manager = TransactionManager(planner=planner, client=client)
    graph_manager = NamedGraphManager(client=client, settings=settings)
    provenance_service = ProvenanceService(client=client, settings=settings)
    projection_builder = GraphProjectionBuilder(client=client, settings=settings)
    formatter = GraphFormatter()
    mapper = ResultMapper()

    # 3) 创建命名图，并通过 Upsert 写入订单、设备、产品等主数据。
    await graph_manager.create(graph_ref, trace_id="demo-e2e-init")

    order_iri = "http://example.com/order/PO-10001"
    machine_iri = "http://example.com/machine/M-9"
    product_iri = "http://example.com/product/P-500"
    inspector_iri = "http://example.com/staff/Alice"
    occurred_at = datetime.now(timezone.utc)

    upsert_request = UpsertRequest(
        graph=graph_ref,
        triples=[
            # 生产订单的实体定义：类型、状态以及与产品/设备的关联。
            Triple(s=order_iri, p=RDF_TYPE, o=SF + "ProductionOrder"),
            Triple(s=order_iri, p=SF + "status", o="quality_check"),
            Triple(s=order_iri, p=SF + "relatesTo", o=product_iri),
            Triple(s=order_iri, p=SF + "usesMachine", o=machine_iri),
            Triple(
                s=order_iri,
                p=SF + "updatedAt",
                o=occurred_at.isoformat(),
                dtype="http://www.w3.org/2001/XMLSchema#dateTime",
            ),
            # 产品与设备的补充属性，展示 IRI 与字面量的混合写入。
            Triple(s=product_iri, p=RDF_TYPE, o=SF + "Product"),
            Triple(s=product_iri, p=SF + "name", o="训练用智能终端"),
            Triple(s=machine_iri, p=RDF_TYPE, o=SF + "Machine"),
            Triple(s=machine_iri, p=SF + "serialNumber", o="SN-M-9-2025"),
            Triple(s=machine_iri, p=SF + "status", o="online"),
            # 质检人员与订单之间的责任链。
            Triple(s=inspector_iri, p=RDF_TYPE, o=SF + "Person"),
            Triple(s=inspector_iri, p=SF + "name", o="Alice"),
            Triple(s=order_iri, p=SF + "checkedBy", o=inspector_iri),
        ],
        merge_strategy="replace",
    )

    await tx_manager.upsert(upsert_request, trace_id="demo-e2e-upsert", actor="quality-bot")

    # 4) 写入 RDF* 溯源片段，记录数据来源与置信度，模拟追责场景。
    provenance = Provenance(evidence="人工巡检", confidence=0.95, source="http://example.com/process/manual")
    await provenance_service.annotate(
        graph=graph_ref,
        triples=[
            Triple(s=order_iri, p=SF + "status", o="quality_check"),
            Triple(s=order_iri, p=SF + "checkedBy", o=inspector_iri),
        ],
        provenance=provenance,
        trace_id="demo-e2e-provenance",
        metadata={
            "operator": "质量管理员",
            "batch": "demo-20251018",
            # generatedAtTime is added automatically by service
        },
    )

    # 5) 通过图投影生成 GraphJSON，供前端或算法消费。
    projection = await projection_builder.project(
        source=graph_ref,
        profile="default",
        trace_id="demo-e2e-projection",
    )

    # 6) 运行一次 SELECT 查询，并使用 ResultMapper 统一字段形态。
    raw_query = (
        "SELECT ?s ?p ?o ?sourceType ?targetType WHERE { "
        f"GRAPH <{projection.graph_iri}> {{ "
        "?s ?p ?o . "
        "OPTIONAL { ?s <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ?sourceType . } "
        "OPTIONAL { ?o <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ?targetType . } "
        "}}"
    )
    raw_result = await client.select(raw_query, trace_id="demo-e2e-select")
    mapped_rows = mapper.map_bindings(raw_result["vars"], raw_result["bindings"])

    # 7) 导出命名图的 Turtle 片段，方便人工复核或下游集成。
    construct_query = (
        f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{projection.graph_iri}> {{ ?s ?p ?o }} }}"
    )
    construct_res = await client.construct(construct_query, trace_id="demo-e2e-construct")
    formatted_ttl = formatter.to_turtle(construct_res.get("turtle", ""))
    construct_query = (
        f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{projection.graph_iri}> {{ ?s ?p ?o }} }}"
    )
    construct_res = await client.construct(construct_query, trace_id="demo-e2e-construct")
    formatted_ttl = formatter.to_turtle(construct_res.get("turtle", ""))
    # 8) 生成一次快照，展示命名图管理能力（复制到新的 snapshot 图）。
    snapshot_info = await graph_manager.snapshot(graph_ref, trace_id="demo-e2e-snapshot")

    # ---- 演示输出 -----------------------------------------------------
    print("\n=== 图投影 GraphJSON ===")
    print(projection.graph)

    print("\n=== ResultMapper 结构化结果 ===")
    for row in mapped_rows:
        print(row)

    print("\n=== 导出的 Turtle 片段 ===")
    print(formatted_ttl)

    print("\n=== 快照信息 ===")
    print(snapshot_info)


if __name__ == "__main__":
    asyncio.run(main())






