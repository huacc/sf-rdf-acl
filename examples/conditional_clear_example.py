"""条件化清理示例

该示例展示如何安全地按条件清理命名图中的部分数据，支持 Dry-Run 预估与执行阶段阈值保护。

运行方式：
    python examples/conditional_clear_example.py

注意：
    - 默认读取 sf-common 的配置（RDF 端点、数据集、命名图命名规则等）。
    - 示例包含交互式确认；在自动化环境（如 CI）可直接调用 `run_example(dry_run=True)` 以跳过交互。
"""
from __future__ import annotations

import asyncio
from typing import Any

from common.config import ConfigManager
from common.config.settings import Settings

from sf_rdf_acl import NamedGraphManager
from sf_rdf_acl.graph.named_graph import TriplePattern, ClearCondition
from sf_rdf_acl.query.dsl import GraphRef


async def run_example(settings: Settings, *, dry_run: bool = True) -> dict[str, Any]:
    """执行条件化清理示例。

    参数：
        settings (Settings): 全局配置对象。
        dry_run (bool): 是否仅预估（不执行）。范围：True/False；默认 True。

    返回：
        dict[str, Any]: 当 dry_run=False 时返回执行结果；dry_run=True 时返回 Dry-Run 统计信息的字典化数据。
    """

    manager = NamedGraphManager()
    graph = GraphRef(model="demo", version="v1", env="dev")

    # 构造清理条件：删除 rdfs:comment 谓词的三元组，且仅针对特定前缀的主体
    condition = ClearCondition(
        patterns=[
            TriplePattern(predicate="<http://www.w3.org/2000/01/rdf-schema#comment>")
        ],
        subject_prefix="http://example.com/resource/",
    )

    result = await manager.conditional_clear(
        graph,
        condition,
        dry_run=dry_run,
        trace_id="clear-example-001",
        max_deletes=1000,
    )

    # 统一返回 dict 便于打印或测试断言
    if hasattr(result, "model_dump"):
        # pydantic/dataclass 兼容处理
        try:
            return result.model_dump()  # type: ignore[attr-defined]
        except Exception:
            pass
    if isinstance(result, dict):
        return result
    return {
        "graph": getattr(result, "graph_iri", ""),
        "estimated_deletes": getattr(result, "estimated_deletes", 0),
    }


async def main() -> None:
    """脚本入口：演示 dry-run 与交互式确认执行。"""

    ConfigManager.load()
    settings = ConfigManager.current().settings

    # 第一步：Dry-Run 预估
    print("Step 1: Dry-run to preview changes...")
    preview = await run_example(settings, dry_run=True)
    print(f"Will delete approximately {preview.get('estimated_deletes', 0)} triples")

    # 第二步：交互确认后执行
    confirm = input("\nProceed with deletion? (yes/no): ")
    if confirm.strip().lower() == "yes":
        print("\nStep 2: Executing conditional clear...")
        result = await run_example(settings, dry_run=False)
        print("Deleted:", result)
    else:
        print("Operation cancelled")


if __name__ == "__main__":
    asyncio.run(main())

