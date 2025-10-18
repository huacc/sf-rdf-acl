"""SPARQL 结果映射工具。

`ResultMapper` 负责将 Fuseki 等 SPARQL 服务返回的 JSON 结构映射为平台内部
使用的统一格式：每个变量都带有 `value`、`raw`、`type` 等元信息，方便上层
业务进行二次处理或序列化。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any


class ResultMapper:
    """将 SPARQL 绑定结果转换为规范 JSON 结构。

    - 支持常见的 XSD 数值、布尔、日期时间类型自动转换。
    - 保留原始文本（`raw`）以及语言标签和数据类型信息，便于前端或日志使用。
    - 遇到未知类型时保持原样，避免误报错或数据丢失。
    """

    #: 可被视为整数的 XSD 类型集合。
    _INT_TYPES = {
        "http://www.w3.org/2001/XMLSchema#integer",
        "http://www.w3.org/2001/XMLSchema#int",
        "http://www.w3.org/2001/XMLSchema#long",
        "http://www.w3.org/2001/XMLSchema#short",
        "http://www.w3.org/2001/XMLSchema#byte",
        "http://www.w3.org/2001/XMLSchema#nonNegativeInteger",
        "http://www.w3.org/2001/XMLSchema#positiveInteger",
        "http://www.w3.org/2001/XMLSchema#nonPositiveInteger",
        "http://www.w3.org/2001/XMLSchema#negativeInteger",
        "http://www.w3.org/2001/XMLSchema#unsignedInt",
        "http://www.w3.org/2001/XMLSchema#unsignedShort",
        "http://www.w3.org/2001/XMLSchema#unsignedByte",
    }

    #: 可被视为浮点或高精度小数的 XSD 类型集合。
    _DECIMAL_TYPES = {
        "http://www.w3.org/2001/XMLSchema#decimal",
        "http://www.w3.org/2001/XMLSchema#double",
        "http://www.w3.org/2001/XMLSchema#float",
    }

    _BOOL_TYPE = "http://www.w3.org/2001/XMLSchema#boolean"
    _DATETIME_TYPE = "http://www.w3.org/2001/XMLSchema#dateTime"

    def map_bindings(self, vars: list[str], bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将 SPARQL JSON 绑定数组转换为统一结构。

        参数:
            vars (list[str]): 查询头部返回的变量名列表，例如 ``["s", "p", "o"]``。
            bindings (list[dict[str, Any]]): Fuseki 返回的 `results.bindings` 数组，
                每个元素代表一行数据，且包含变量到单元格的映射。例如::

                    {
                        "s": {"type": "uri", "value": "http://example.com/entity/123"},
                        "label": {
                            "type": "literal",
                            "value": "示例",
                            "xml:lang": "zh"
                        }
                    }

        返回:
            list[dict[str, Any]]: 每行数据被转换为 ``{变量名: {value, raw, type, ...}}`` 的字典。
                当某个变量在该行不存在时，其值为 ``None``。
        """

        rows: list[dict[str, Any]] = []
        for binding in bindings:
            row: dict[str, Any] = {}
            for var in vars:
                cell = binding.get(var)
                row[var] = self._convert_cell(cell)
            rows.append(row)
        return rows

    def _convert_cell(self, cell: dict[str, Any] | None) -> dict[str, Any] | None:
        """将单个 SPARQL 单元格转换为标准结构。

        参数:
            cell (dict[str, Any] | None): 原始单元格，如 ``{"type": "literal", "value": "42"}``。
                当传入 ``None``（变量缺失）时直接返回 ``None``。

        返回:
            dict[str, Any] | None: 包含 ``value``、``raw``、``type`` 等字段的结果。
        """

        if cell is None:
            return None
        value = cell.get("value")
        dtype = cell.get("datatype")
        ctype = cell.get("type")
        lang = cell.get("xml:lang")
        converted = self._cast_value(value, dtype, ctype)
        payload = {
            "value": converted,
            "raw": value,
            "type": ctype,
        }
        if dtype:
            payload["datatype"] = dtype
        if lang:
            payload["lang"] = lang
        return payload

    def _cast_value(self, value: Any, dtype: str | None, ctype: str | None) -> Any:
        """根据数据类型尝试做类型转换。

        参数:
            value (Any): 单元格里的原始值（字符串、数字等）。
            dtype (str | None): XSD 数据类型 URI，可为 ``None``。
            ctype (str | None): 单元格类型（`uri`、`literal`、`bnode` 等）。

        返回:
            Any: 转换后的 Python 对象；若无法转换则返回原值。
        """

        if dtype is None:
            # 对于没有显式数据类型的值，仅在 URI / 空白节点时原样返回。
            if ctype in {"uri", "bnode"}:
                return value
            return value
        if dtype in self._INT_TYPES:
            try:
                return int(value)
            except (TypeError, ValueError):
                return value
        if dtype in self._DECIMAL_TYPES:
            try:
                return float(Decimal(value))
            except (TypeError, ValueError, ArithmeticError):
                return value
        if dtype == self._BOOL_TYPE:
            return str(value).lower() in {"true", "1"}
        if dtype == self._DATETIME_TYPE:
            return self._normalize_datetime(str(value))
        if dtype.endswith("#string"):
            return value
        return value

    @staticmethod
    def _normalize_datetime(text: str) -> str:
        """将 XSD `dateTime` 文本统一为 ISO 8601 字符串。

        - 自动将结尾的 ``Z`` 替换为 ``+00:00`` 再解析。
        - 若原始字符串无时区，将结果补齐 ``Z``，便于前端一致展示。

        参数:
            text (str): 原始日期时间字符串，例如 ``"2025-10-17T12:30:00Z"``。

        返回:
            str: 标准化后的 ISO 字符串；当解析失败时返回原值。
        """

        normalized = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo:
                return dt.isoformat()
            return f"{dt.isoformat()}Z"
        except ValueError:
            return text
