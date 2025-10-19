"""条件化清理示例

演示如何按条件安全删除命名图中的部分数据，支持 Dry-Run 预估与执行阈值保护。
运行方式: python examples/conditional_clear_example.py
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

    返回统一的字典结果，便于日志与测试断言。
    """

    manager = NamedGraphManager()
    graph = GraphRef(model="demo", version="v1", env="dev")

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

    if hasattr(result, "model_dump"):
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
    """脚本入口: 先 Dry-Run 预估，再询问是否执行。"""

    ConfigManager.load(env=None, override_path=r"D:\coding\OntologyGraph\projects\sf-rdf-acl\examples\config\demo.yaml")
    settings = ConfigManager.current().settings

    print("Step 1: Dry-run to preview changes...")
    preview = await run_example(settings, dry_run=True)
    print(f"Will delete approximately {preview.get('estimated_deletes', 0)} triples")

    try:
        confirm = input("\nProceed with deletion? (yes/no): ")
    except EOFError:
        print("No stdin available; skipping execution step.")
        return
    if confirm.strip().lower() == "yes":
        print("\nStep 2: Executing conditional clear...")
        result = await run_example(settings, dry_run=False)
        print("Deleted:", result)
    else:
        print("Operation cancelled")


if __name__ == "__main__":
    asyncio.run(main())

