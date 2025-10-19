"""基于游标的 SPARQL 分页工具。

提供将上一页最后一条记录编码为 Base64 游标、从游标构建 FILTER 子句、
以及分页参数的数据结构，便于与 Fuseki 的 SELECT 查询配合使用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import base64
import json


@dataclass(frozen=True, slots=True)
class CursorPage:
    """游标分页参数。

    参数:
        cursor (str | None): 上一页游标；None 表示第一页。
        size (int): 每页条数，建议范围 1~1000，默认 100。
    """

    cursor: str | None = None
    size: int = 100


@dataclass
class PageResult:
    """分页结果载体。

    参数:
        results (list[dict[str, Any]]): 当前页的绑定结果（最多 size 条）。
        next_cursor (str | None): 下一页游标；当 `has_more=False` 时为 None。
        has_more (bool): 是否仍有下一页数据。
        total_estimate (int | None): 可选的总量估计（如需要额外统计时填写）。
    """

    results: list[dict[str, Any]]
    next_cursor: str | None
    has_more: bool
    total_estimate: int | None = None


class CursorPagination:
    """游标分页工具集合。"""

    @staticmethod
    def encode_cursor(last_item: dict[str, Any], sort_key: str) -> str:
        """从当前页的最后一条记录生成 Base64 游标。

        参数:
            last_item: 当前页最后一条绑定记录，例如 {"s": {"value": "...", "type": "uri"}}。
            sort_key: 用于排序与比较的变量名，例如 "?s"、"?value"。

        返回:
            str: 可放入下页查询参数的 Base64 游标字符串。
        """

        key = sort_key.lstrip("?")
        if key not in last_item:
            raise ValueError(f"Sort key {sort_key} not in item")
        cell = last_item[key]
        cursor_data = {"value": cell.get("value"), "type": cell.get("type", "uri")}
        json_str = json.dumps(cursor_data, sort_keys=True, ensure_ascii=False)
        return base64.urlsafe_b64encode(json_str.encode("utf-8")).decode("utf-8")

    @staticmethod
    def decode_cursor(cursor: str) -> dict[str, Any]:
        """解析 Base64 游标为原始数据结构。"""

        try:
            json_str = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
            return json.loads(json_str)
        except Exception as e:  # pragma: no cover - 防御性
            raise ValueError(f"Invalid cursor: {e}")

    @staticmethod
    def build_cursor_filter(cursor_data: dict[str, Any], sort_key: str) -> str:
        """基于游标构建 SPARQL FILTER 断言。

        参数:
            cursor_data: 由 `decode_cursor` 返回的数据，至少包含 `value` 与 `type`。
            sort_key: 比较的变量名，例如 "?s" 或 "?value"。

        返回:
            str: 可直接拼接到 WHERE 的 FILTER 片段。
        """

        value = cursor_data["value"]
        value_type = cursor_data.get("type", "uri")
        if value_type == "uri":
            # 对 IRI 使用 STR() 比较（保持词法序）
            return f'FILTER(STR({sort_key}) > "{value}")'
        # 对字面量直接比较
        return f'FILTER({sort_key} > "{value}")'

