"""事务批处理执行器：支持基于模板的大批量写入，并提供重试机制。

本模块面向高吞吐写入场景，提供以下能力：
- 使用 `BatchTemplate` 承载 SPARQL 片段模板与多组变量绑定；
- `BatchOperator.apply_template(...)` 将模板渲染为 INSERT DATA，并分批提交；
- 在批次失败时，自动对每条绑定进行单条重试，最大重试次数可配置；
- 返回 `BatchResult` 汇总结果，包含总量/成功/失败/失败项/耗时等信息。

注意：模板字符串中变量形式为 `{?s}`、`{?o}`，绑定中键名需与之完全一致，例如：

    pattern = "{?s} <http://example.com/pred> {?o} ."
    bindings = [
        {"?s": "<http://example.com/s1>", "?o": '"value1"'},
        {"?s": "<http://example.com/s2>", "?o": '"value2"'},
    ]

模板中应保证谓词等固定位置为合法 IRI 或 CURIE；变量替换后整体需构成有效的三元组序列。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, List

from common.logging import LoggerFactory

from ..connection.client import RDFClient


@dataclass
class BatchTemplate:
    """批处理模板定义。

    参数:
        pattern (str): SPARQL 三元组模板片段，变量使用 `{?x}` 包裹，如 `{?s} <pred> {?o} .`
        bindings (list[dict[str, str]]): 变量绑定列表，每个绑定提供与模板变量一致的键名；
            例如：`{"?s": "<http://ex/s>", "?o": '"value"'}`。
    """

    pattern: str
    bindings: list[dict[str, str]]


@dataclass
class BatchResult:
    """批处理结果汇总。"""

    total: int
    success: int
    failed: int
    failed_items: list[dict[str, Any]]
    duration_ms: float


class BatchOperator:
    """批处理执行器。

    通过分批 INSERT DATA 提交，失败时逐条重试，兼顾吞吐与稳定性。
    """

    def __init__(self, client: RDFClient, batch_size: int = 1000, max_retries: int = 3) -> None:
        """初始化执行器。

        参数:
            client (RDFClient): RDF 客户端，通常为 `FusekiClient` 实例。
            batch_size (int): 每个批次写入的绑定条数；建议 100~2000。
            max_retries (int): 单条失败的最大重试次数（指数退避）。
        """

        self._client = client
        self._batch_size = max(1, int(batch_size))
        self._max_retries = max(0, int(max_retries))
        self._logger = LoggerFactory.create_default_logger(__name__)

    async def apply_template(
        self,
        template: BatchTemplate,
        graph_iri: str,
        *,
        trace_id: str,
        dry_run: bool = False,
    ) -> BatchResult:
        """应用模板并提交到目标图。

        参数:
            template (BatchTemplate): 三元组模板与绑定集合。
            graph_iri (str): 目标命名图 IRI。
            trace_id (str): 追踪 ID，用于日志/链路追踪。
            dry_run (bool): 若为 True，仅统计与拼装，不发起更新。

        返回:
            BatchResult: 包含总量、成功、失败与耗时的统计信息。
        """

        import time

        start = time.perf_counter()
        total = len(template.bindings)
        success = 0
        failed = 0
        failed_items: list[dict[str, Any]] = []

        # 分批执行
        for i in range(0, total, self._batch_size):
            batch = template.bindings[i : i + self._batch_size]
            try:
                if not dry_run and batch:
                    await self._execute_batch(template.pattern, batch, graph_iri, trace_id)
                success += len(batch)
            except Exception as exc:  # 批次失败，逐条重试
                self._logger.error("Batch %s failed: %s", i // self._batch_size, exc)
                for binding in batch:
                    ok = await self._retry_single(template.pattern, binding, graph_iri, trace_id)
                    if ok:
                        success += 1
                    else:
                        failed += 1
                        failed_items.append(binding)

        duration_ms = (time.perf_counter() - start) * 1000.0
        return BatchResult(total=total, success=success, failed=failed, failed_items=failed_items, duration_ms=duration_ms)

    async def _execute_batch(self, pattern: str, bindings: list[dict[str, str]], graph_iri: str, trace_id: str) -> None:
        """执行单个批次 INSERT DATA。

        参数:
            pattern (str): 模板字符串。
            bindings (list[dict[str, str]]): 变量绑定列表。
            graph_iri (str): 目标命名图 IRI。
            trace_id (str): 追踪 ID。
        """

        triple_snippets: List[str] = []
        for binding in bindings:
            stmt = pattern
            for var, value in binding.items():
                stmt = stmt.replace(f"{{{var}}}", value)
            triple_snippets.append(stmt)

        update_query = (
            "INSERT DATA {\n"
            f"  GRAPH <{graph_iri}> {{\n"
            f"    {' '.join(triple_snippets)}\n"
            "  }\n"
            "}"
        )
        await self._client.update(update_query, trace_id=trace_id)

    async def _retry_single(self, pattern: str, binding: dict[str, str], graph_iri: str, trace_id: str) -> bool:
        """在批次失败时，针对单个绑定进行重试。

        参数:
            pattern (str): 模板字符串。
            binding (dict[str,str]): 单条变量绑定。
            graph_iri (str): 目标命名图 IRI。
            trace_id (str): 追踪 ID。

        返回:
            bool: 是否最终写入成功。
        """

        for attempt in range(self._max_retries):
            try:
                await self._execute_batch(pattern, [binding], graph_iri, trace_id)
                return True
            except Exception as exc:
                if attempt == self._max_retries - 1:
                    self._logger.error("Final retry failed: %s", exc)
                    return False
                # 指数退避：0.5, 1.0, 2.0 ... 秒
                await asyncio.sleep(0.5 * (2 ** attempt))
        return False

