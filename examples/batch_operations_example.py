"""批处理操作示例

该示例演示如何使用 BatchOperator/BatchTemplate 以模板驱动方式进行大批量写入，
并统计写入耗时/吞吐等指标。

运行方式：
    python examples/batch_operations_example.py

注意：
    - 写入示例将尝试向目标命名图追加 1000 条关系，请在测试环境中运行。
    - 可设置 `dry_run=True` 进行试运行，仅统计不提交。
"""
from __future__ import annotations

import asyncio
from typing import Any

from common.config import ConfigManager
from common.config.settings import Settings

from sf_rdf_acl import FusekiClient
from sf_rdf_acl.transaction.batch import BatchOperator, BatchTemplate


async def run_batch(settings: Settings, *, count: int = 1000, dry_run: bool = True) -> dict[str, Any]:
    """执行一次批处理写入。

    参数：
        settings (Settings): 全局配置对象。
        count (int): 生成的关系数量，范围建议 1~100000，默认 1000。
        dry_run (bool): 是否仅试运行（不提交）。默认 True。

    返回：
        dict[str, Any]: 统计结果字典，包含 total/success/failed/duration_ms/throughput 等字段。
    """

    rdf = settings.rdf
    client = FusekiClient(endpoint=str(rdf.endpoint), dataset=rdf.dataset)
    operator = BatchOperator(client, batch_size=500)

    bindings: list[dict[str, str]] = []
    for i in range(count):
        bindings.append(
            {
                "?user": f"<http://example.com/user/u{i}>",
                "?order": f"<http://example.com/order/o{i}>",
            }
        )

    template = BatchTemplate(
        pattern="{?user} <http://example.com/hasOrder> {?order} .",
        bindings=bindings,
    )

    result = await operator.apply_template(
        template,
        "http://example.com/graph/orders",
        trace_id="batch-example-001",
        dry_run=dry_run,
    )

    duration_sec = max(1e-6, result.duration_ms / 1000.0)
    return {
        "total": result.total,
        "success": result.success,
        "failed": result.failed,
        "duration_ms": result.duration_ms,
        "throughput": result.total / duration_sec,
    }


async def main() -> None:
    """脚本入口：默认以 dry-run 形式运行批处理，并打印指标。"""

    ConfigManager.load()
    settings = ConfigManager.current().settings
    metrics = await run_batch(settings, count=1000, dry_run=True)
    print("Metrics:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())

