"""示例脚本冒烟测试

为了满足“3.2 代码示例完善”的验收，本测试验证示例中的核心函数可在真实配置下运行。
由于示例本身具有交互或大量写入风险，这里全部以非交互、dry-run 模式运行。
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from common.config import ConfigManager
import importlib.util
import types
from pathlib import Path


@pytest.mark.asyncio
async def test_aggregation_example_smoke() -> None:
    """聚合示例应能成功生成并执行查询，返回标准结果结构。"""

    ConfigManager.load()
    settings = ConfigManager.current().settings

    # 从文件路径加载示例模块，避免路径依赖
    repo_root = Path(__file__).resolve().parents[4]
    mod_path = repo_root / "projects" / "sf-rdf-acl" / "examples" / "aggregation_example.py"
    spec = importlib.util.spec_from_file_location("aggregation_example", mod_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    assert isinstance(module, types.ModuleType)
    spec.loader.exec_module(module)  # type: ignore[assignment]

    result: dict[str, Any] = await module.run_aggregation(settings)
    assert isinstance(result, dict)
    assert "bindings" in result


@pytest.mark.asyncio
async def test_conditional_clear_example_dry_run() -> None:
    """条件清理示例在 dry-run 下返回评估信息。"""

    ConfigManager.load()
    settings = ConfigManager.current().settings

    repo_root = Path(__file__).resolve().parents[4]
    mod_path = repo_root / "projects" / "sf-rdf-acl" / "examples" / "conditional_clear_example.py"
    spec = importlib.util.spec_from_file_location("conditional_clear_example", mod_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    assert isinstance(module, types.ModuleType)
    spec.loader.exec_module(module)  # type: ignore[assignment]

    preview = await module.run_example(settings, dry_run=True)
    assert isinstance(preview, dict)
    assert "estimated_deletes" in preview


@pytest.mark.asyncio
async def test_batch_operations_example_dry_run_small() -> None:
    """批处理示例在 dry-run 下返回统计指标，且可指定较小数量（例如 10 条）。"""

    ConfigManager.load()
    settings = ConfigManager.current().settings

    repo_root = Path(__file__).resolve().parents[4]
    mod_path = repo_root / "projects" / "sf-rdf-acl" / "examples" / "batch_operations_example.py"
    spec = importlib.util.spec_from_file_location("batch_operations_example", mod_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    assert isinstance(module, types.ModuleType)
    spec.loader.exec_module(module)  # type: ignore[assignment]

    metrics = await module.run_batch(settings, count=10, dry_run=True)
    assert isinstance(metrics, dict)
    for key in ("total", "success", "failed", "duration_ms", "throughput"):
        assert key in metrics
