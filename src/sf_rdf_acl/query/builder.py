"""QueryDSL 对 SPARQL 语句构建的具体实现。"""
from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any, Iterable, Sequence

from .dsl import Aggregation, Filter, GroupBy, QueryDSL, TimeWindow


class SPARQLSanitizer:
    """SPARQL 参数安全转义工具。

    提供 IRI 校验、字符串字面量转义，以及前缀名合法性校验，尽量在构建查询
    的早期阶段发现并阻断潜在的注入或格式风险。

    注意：该工具仅负责语法级别的安全防护，不等价于权限与数据级安全控制。
    """

    @staticmethod
    def escape_uri(uri: str) -> str:
        """转义并校验 IRI。

        参数：
            uri: 原始 IRI 字符串。必须是非空字符串，推荐以 http/https 开头。

        返回：
            通过校验的 IRI 字符串（原样返回，不包角括号）。

        异常：
            ValueError: 当 IRI 为空、类型错误、或包含危险字符时抛出。
        """

        if not uri or not isinstance(uri, str):
            raise ValueError(f"Invalid URI: {uri}")

        # 要求 http/https IRI，其他协议或裸字符串一律拒绝
        if not (uri.startswith("http://") or uri.startswith("https://")):
            raise ValueError(f"Invalid URI scheme: {uri}")

        # 拦截常见危险字符，避免拼接破坏 SPARQL 结构
        dangerous_chars = ["<", ">", '"', "{", "}", "|", "\\", "^", "`"]
        if any(ch in uri for ch in dangerous_chars):
            raise ValueError(f"URI contains dangerous characters: {uri}")

        return uri

    @staticmethod
    def escape_literal(value: str, datatype: str | None = None) -> str:
        """转义字面量为安全的 SPARQL 表达式。

        参数：
            value: 原始字符串字面量。
            datatype: 可选的数据类型 IRI（不带尖括号）。

        返回：
            转义后的 SPARQL 字面量表达式，例如：
            - 普通字符串："hello"
            - 带类型："2024-01-01"^^<http://www.w3.org/2001/XMLSchema#date>
        """

        # 仅进行必要转义：反斜杠与双引号
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        if datatype:
            return f'"{escaped}"^^<{datatype}>'
        return f'"{escaped}"'

    @staticmethod
    def validate_prefix(prefix: str) -> bool:
        """验证前缀名称是否合法。

        参数：
            prefix: 前缀名（需满足 XML NCName 约束）。

        返回：
            True 表示合法，False 表示不合法。
        """

        import re as _re

        # XML NCName 的近似校验：首字符字母或下划线，后续为字母/数字/下划线/连字符
        pattern = r"^[A-Za-z_][A-Za-z0-9_-]*$"
        return bool(_re.match(pattern, prefix))


class SPARQLQueryBuilder:
    """
    将平台内部的 QueryDSL 转换为 SPARQL 语句的帮助类。

    典型使用示例:
        builder = SPARQLQueryBuilder()
        sparql = builder.build_select(
            dsl=QueryDSL(type="entity", filters=[]),
            graph=None,
        )

    通过 default_prefixes 参数可以注入新的前缀映射，例如 {"ex": "http://example.com/"}。
    """

    _PREFIX_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*:[A-Za-z0-9_-]+$")

    _DEFAULT_PREFIXES: dict[str, str] = {
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        "xsd": "http://www.w3.org/2001/XMLSchema#",
        "owl": "http://www.w3.org/2002/07/owl#",
        "prov": "http://www.w3.org/ns/prov#",
        "sf": "http://semanticforge.ai/ontologies/core#",
    }

    _TIME_PREDICATE = "prov:generatedAtTime"
    _PARTICIPANT_PREDICATE = "sf:participant"

    def __init__(self, *, default_prefixes: dict[str, str] | None = None) -> None:
        """
        初始化 SPARQLQueryBuilder 实例。

        参数:
            default_prefixes: dict[str, str]，例如 {"ex": "http://example.org/"}；
                如果提供，将与内置前缀合并，可覆盖相同前缀键。
        """

        self._default_prefixes = {**self._DEFAULT_PREFIXES}
        if default_prefixes:
            self._default_prefixes.update(default_prefixes)

    def build_select(self, dsl: QueryDSL, *, graph: str | None = None) -> str:
        """
        按 DSL 定义构建 SELECT 查询语句。

        参数:
            dsl: QueryDSL，例如 QueryDSL(type="entity", filters=[]).
            graph: 命名图 IRI，例如 "http://data.example/graph/a"；None 表示默认图。

        返回:
            可直接发送至 SPARQL 端点的 SELECT 查询字符串。
        """

        return self._build_query(dsl, graph=graph, construct=False)

    def build_construct(self, dsl: QueryDSL, *, graph: str | None = None) -> str:
        """
        按 DSL 定义构建 CONSTRUCT 查询语句。

        参数:
            dsl: QueryDSL，例如 QueryDSL(type="event", expand=["sf:hasActor"]).
            graph: 命名图 IRI，例如 "http://data.example/graph/b"；None 表示默认图。

        返回:
            可用于生成子图的 CONSTRUCT 查询字符串。
        """

        return self._build_query(dsl, graph=graph, construct=True)

    # -------------------- 游标分页 SELECT --------------------

    def build_select_with_cursor(
        self,
        dsl: QueryDSL,
        cursor_page: "CursorPage",
        sort_key: str = "?s",
        *,
        graph: str | None = None,
    ) -> str:
        """基于游标分页生成 SELECT 查询。

        参数:
            dsl: 查询 DSL，参与构建 WHERE 的过滤、展开、时间窗等内容。
            cursor_page: 分页参数，包含上页游标与每页大小。
            sort_key: 排序与游标比较的变量名，默认为 "?s"（主语）。
            graph: 可选的命名图 IRI；None 表示默认图。

        返回:
            str: 可直接发送至 Fuseki 的 SPARQL 查询文本。
        """

        # 延迟导入，避免循环依赖
        from .pagination import CursorPagination

        prefixes = self._merge_prefixes(dsl)

        # 构造 WHERE 内容：复用 _build_query 的分解逻辑
        where_lines: list[str] = ["?s ?p ?o ."]
        select_vars: list[str] = ["?s", "?p", "?o"]
        next_index = 0

        for item in dsl.filters:
            var_name = f"?f{next_index}"
            next_index += 1
            triple_parts, filter_parts = self._render_filter(item, var_name, prefixes)
            where_lines.extend(triple_parts)
            where_lines.extend(filter_parts)

        expand_clauses = self._render_expand(dsl.expand, prefixes, start=next_index)
        select_vars.extend(expand_clauses.keys())
        where_lines.extend(expand_clauses.values())
        next_index += len(expand_clauses)

        if dsl.participants:
            participant_clauses = self._render_participants(dsl.participants, prefixes, start=next_index)
            select_vars.extend(participant_clauses.keys())
            where_lines.extend(participant_clauses.values())
            next_index += len(participant_clauses)

        if dsl.time_window:
            where_lines.append(self._render_time_window(prefixes))
            where_lines.extend(self._render_time_filters(dsl.time_window))

        # 游标过滤
        if cursor_page.cursor:
            data = CursorPagination.decode_cursor(cursor_page.cursor)
            where_lines.append(CursorPagination.build_cursor_filter(data, sort_key))

        body = self._wrap_graph(where_lines, graph)
        header = self._render_prefix_block(prefixes)

        parts: list[str] = [header, "SELECT DISTINCT ?s", "WHERE {", body, "}"]
        parts.append(f"ORDER BY {sort_key}")
        parts.append(f"LIMIT {max(1, cursor_page.size) + 1}")  # 多取 1 条用于判断 has_more
        return "\n".join(parts)

    # ---- 内部实现 -----------------------------------------------------

    def _build_query(self, dsl: QueryDSL, *, graph: str | None, construct: bool) -> str:
        """
        统一处理 SELECT 与 CONSTRUCT 的构建流程。

        参数:
            dsl: QueryDSL，例如 QueryDSL(type="entity", filters=[...])。
            graph: 命名图 IRI，例如 "http://data.example/graph/c"；None 表示默认图。
            construct: bool，例 True 表示生成 CONSTRUCT，False 表示生成 SELECT。

        返回:
            完整的 SPARQL 查询文本。
        """

        prefixes = self._merge_prefixes(dsl)
        # 基础三元组确保主体、谓词、宾语总是被选出
        where_lines: list[str] = ["?s ?p ?o ."]
        select_vars: list[str] = ["?s", "?p", "?o"]
        # 记录下一个可以使用的变量编号，避免冲突
        next_index = 0

        for item in dsl.filters:
            var_name = f"?f{next_index}"
            next_index += 1
            # 根据过滤条件生成三元组与 FILTER 片段
            triple_parts, filter_parts = self._render_filter(item, var_name, prefixes)
            where_lines.extend(triple_parts)
            where_lines.extend(filter_parts)

        expand_clauses = self._render_expand(dsl.expand, prefixes, start=next_index)
        select_vars.extend(expand_clauses.keys())
        where_lines.extend(expand_clauses.values())
        next_index += len(expand_clauses)

        if dsl.participants:
            participant_clauses = self._render_participants(
                dsl.participants,
                prefixes,
                start=next_index,
            )
            select_vars.extend(participant_clauses.keys())
            where_lines.extend(participant_clauses.values())
            next_index += len(participant_clauses)

        if dsl.time_window:
            # 时间窗口需要先尝试绑定时间，再追加过滤条件
            where_lines.append(self._render_time_window(prefixes))
            where_lines.extend(self._render_time_filters(dsl.time_window))

        # 去重以避免相同变量重复出现在 SELECT 头部
        select_vars = list(dict.fromkeys(select_vars))
        body = self._wrap_graph(where_lines, graph)

        header = self._render_prefix_block(prefixes)
        if construct:
            head = "CONSTRUCT {\n  ?s ?p ?o .\n}"
        else:
            # 若存在聚合定义，则 SELECT 由聚合表达式与分组变量组成
            if hasattr(dsl, "aggregations") and dsl.aggregations:
                agg_exprs = [self._build_aggregation_clause(a) for a in dsl.aggregations]
                group_vars: list[str] = []
                if hasattr(dsl, "group_by") and dsl.group_by:
                    group_vars = [self._normalize_var(v) for v in (dsl.group_by.variables or [])]
                head = f"SELECT {' '.join([*agg_exprs, *group_vars])}".rstrip()
            else:
                head = f"SELECT DISTINCT {' '.join(select_vars)}"

        query_parts = [header, head, "WHERE {", body, "}"]

        order_clause = self._render_order_clause(dsl, select_vars)
        if order_clause:
            query_parts.append(order_clause)
        # GROUP BY / HAVING（仅当存在聚合定义时生成）
        if not construct and hasattr(dsl, "group_by") and dsl.group_by:
            query_parts.append(self._build_group_by_clause(dsl.group_by))
        if not construct and hasattr(dsl, "having") and dsl.having:
            query_parts.append(self._build_having_clause(dsl.having))

        query_parts.append(self._render_limit_clause(dsl))
        offset_clause = self._render_offset_clause(dsl)
        if offset_clause:
            query_parts.append(offset_clause)

        return "\n".join(part for part in query_parts if part)

    # -------------------- 聚合 / HAVING 支持 --------------------

    def _build_aggregation_clause(self, agg: Aggregation) -> str:
        """构建单个聚合表达式。

        参数：
            agg: 聚合定义对象。

        返回：
            可直接出现在 SELECT 子句中的聚合表达式，例如
            "(COUNT(?s) AS ?cnt)" 或 "GROUP_CONCAT(DISTINCT ?label; SEPARATOR=\", \")"
        """

        func = agg.function
        var = self._normalize_var(agg.variable)

        if func == "GROUP_CONCAT":
            distinct_kw = "DISTINCT " if getattr(agg, "distinct", False) else ""
            if getattr(agg, "separator", None) is not None:
                sep = SPARQLSanitizer.escape_literal(agg.separator)  # type: ignore[arg-type]
                expr = f"GROUP_CONCAT({distinct_kw}{var}; SEPARATOR={sep})"
            else:
                expr = f"GROUP_CONCAT({distinct_kw}{var})"
        else:
            inner = f"{func}({var})"
            if getattr(agg, "distinct", False):
                inner = f"{func}(DISTINCT {var})"
            expr = inner

        if getattr(agg, "alias", None):
            alias = self._normalize_var(agg.alias or "")
            expr = f"({expr} AS {alias})"
        return expr

    def _build_group_by_clause(self, group_by: GroupBy) -> str:
        """构建 GROUP BY 子句。"""

        if not group_by or not group_by.variables:
            return ""
        vars_str = " ".join(self._normalize_var(v) for v in group_by.variables)
        return f"GROUP BY {vars_str}"

    def _build_having_clause(self, having: list[Filter]) -> str:
        """构建 HAVING 子句，复用过滤构建逻辑但针对聚合上下文。"""

        if not having:
            return ""
        conditions: list[str] = []
        for f in having:
            field = self._normalize_var(str(f.field))
            op = str(getattr(f, "op"))
            if op in {"=", "!=", ">", ">=", "<", "<="}:
                conditions.append(f"{field} {op} {self._escape_filter_value(f.value)}")
            elif op == "in":
                values = ", ".join(self._escape_filter_value(v) for v in self._to_iterable(f.value))
                conditions.append(f"{field} IN ({values})")
            elif op == "range":
                lower, upper = self._split_range(f.value)
                parts: list[str] = []
                if lower is not None:
                    parts.append(f"{field} >= {self._escape_filter_value(lower)}")
                if upper is not None:
                    parts.append(f"{field} <= {self._escape_filter_value(upper)}")
                if parts:
                    conditions.append(" && ".join(parts))
            elif op == "contains":
                val = self._escape_string(str(f.value))
                conditions.append(f"CONTAINS(LCASE(STR({field})), LCASE(\"{val}\"))")
            elif op == "regex":
                pat = self._escape_string(str(f.value))
                conditions.append(f"REGEX(STR({field}), \"{pat}\", \"i\")")
            elif op == "exists":
                conditions.append(f"BOUND({field})")
            elif op == "isNull":
                conditions.append(f"!BOUND({field})")
            else:
                raise ValueError(f"不支持的 HAVING 操作符: {op}")

        return f"HAVING {' && '.join(conditions)}"

    def _escape_filter_value(self, value: Any) -> str:
        """安全转义 HAVING/过滤中使用的值。"""

        if isinstance(value, str):
            if value.startswith("http://") or value.startswith("https://"):
                return f"<{SPARQLSanitizer.escape_uri(value)}>"
            return SPARQLSanitizer.escape_literal(value)
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        raise ValueError(f"Unsupported filter value type: {type(value)}")

    @staticmethod
    def _normalize_var(var: str) -> str:
        """规范化变量名，确保以“?”作为前缀。"""

        v = var.strip()
        return v if v.startswith("?") else f"?{v}"

    def _merge_prefixes(self, dsl: QueryDSL) -> dict[str, str]:
        """
        合并默认前缀与 DSL 自定义前缀。

        参数:
            dsl: QueryDSL，例如包含 prefixes={"ex": "http://example.org/"}。

        返回:
            合并后的前缀映射字典。
        """

        prefixes = {**self._default_prefixes}
        if dsl.prefixes:
            for pfx, iri in dsl.prefixes.items():
                if not SPARQLSanitizer.validate_prefix(pfx):
                    raise ValueError(f"Invalid prefix name: {pfx}")
                SPARQLSanitizer.escape_uri(iri)
            prefixes.update(dsl.prefixes)
        return prefixes

    def _render_prefix_block(self, prefixes: dict[str, str]) -> str:
        """
        将前缀映射转换为 SPARQL PREFIX 语句块。

        参数:
            prefixes: 形如 {"rdf": "http://www.w3.org/..."} 的字典。

        返回:
            多行字符串，每行一个 PREFIX 声明。
        """

        return "\n".join(
            f"PREFIX {prefix}: <{iri}>" for prefix, iri in sorted(prefixes.items())
        )

    def _render_filter(
        self,
        filter_item: Filter,
        var_name: str,
        prefixes: dict[str, str],
    ) -> tuple[list[str], list[str]]:
        """
        根据单个过滤条件生成三元组与 FILTER 片段。

        参数:
            filter_item: Filter，例如 Filter(field="sf:name", op="=", value="Alice")。
            var_name: 变量名字符串，例如 "?f0"，需要以问号开头。
            prefixes: 前缀映射，例如 {"sf": "http://semanticforge.ai/ontologies/core#"}。

        返回:
            (三元组列表, FILTER 列表) 的二元组，用于拼接 WHERE 体。
        """

        predicate = self._expand_term(filter_item.field, prefixes)
        triple_lines: list[str]
        filter_lines: list[str] = []

        # exists/isNull 依赖 OPTIONAL 和变量绑定状态
        if filter_item.op in {"exists", "isNull"}:
            triple_lines = [f"OPTIONAL {{ ?s {predicate} {var_name} . }}"]
            if filter_item.op == "exists":
                filter_lines.append(f"FILTER(BOUND({var_name}))")
            else:
                filter_lines.append(f"FILTER(!BOUND({var_name}))")
            return triple_lines, filter_lines

        # 其他操作符需要确保三元组被显式匹配
        triple_lines = [f"?s {predicate} {var_name} ."]
        if filter_item.op == "=":
            value = self._format_value(filter_item.value, prefixes)
            filter_lines.append(f"FILTER({var_name} = {value})")
        elif filter_item.op == "!=":
            value = self._format_value(filter_item.value, prefixes)
            filter_lines.append(f"FILTER({var_name} != {value})")
        elif filter_item.op == "in":
            values = [
                self._format_value(v, prefixes)
                for v in self._to_iterable(filter_item.value)
            ]
            filter_lines.append(f"FILTER({var_name} IN ({', '.join(values)}))")
        elif filter_item.op == "range":
            lower, upper = self._split_range(filter_item.value)
            if lower is not None:
                filter_lines.append(
                    f"FILTER({var_name} >= {self._format_value(lower, prefixes)})"
                )
            if upper is not None:
                filter_lines.append(
                    f"FILTER({var_name} <= {self._format_value(upper, prefixes)})"
                )
        elif filter_item.op == "contains":
            value = self._escape_string(str(filter_item.value))
            filter_lines.append(
                f"FILTER(CONTAINS(LCASE(STR({var_name})), LCASE(\"{value}\")))"
            )
        elif filter_item.op == "regex":
            pattern = self._escape_string(str(filter_item.value))
            filter_lines.append(f"FILTER(REGEX(STR({var_name}), \"{pattern}\", \"i\"))")
        else:
            raise ValueError(f"暂不支持的过滤操作符: {filter_item.op}")

        return triple_lines, filter_lines

    def _render_expand(
        self,
        expand: Sequence[str],
        prefixes: dict[str, str],
        *,
        start: int,
    ) -> dict[str, str]:
        """
        处理 expand 字段，生成 OPTIONAL 展开子句。

        参数:
            expand: 序列，例如 ["sf:hasActor as actor"]。
            prefixes: 前缀映射，例如 {"sf": "http://semanticforge.ai/ontologies/core#"}。
            start: 整数起点，例如 0；用于生成 ?e0、?e1 等变量。

        返回:
            变量名到 OPTIONAL 子句字符串的映射。
        """

        clauses: dict[str, str] = {}
        next_index = start
        for item in expand:
            predicate, alias = self._parse_expand_item(item)
            predicate_iri = self._expand_term(predicate, prefixes)
            var_name = alias or f"?e{next_index}"
            if not alias:
                next_index += 1
            # 使用 OPTIONAL 以避免缺失断言导致查询整体失败
            clauses[var_name] = f"OPTIONAL {{ ?s {predicate_iri} {var_name} . }}"
        return clauses

    def _render_participants(
        self,
        participants: Sequence[str],
        prefixes: dict[str, str],
        *,
        start: int,
    ) -> dict[str, str]:
        """
        为参与者过滤生成三元组约束。

        参数:
            participants: 序列，例如 ["sf:Agent/Alice", "sf:Agent/Bob"]。
            prefixes: 前缀映射，例如 {"sf": "http://semanticforge.ai/ontologies/core#"}。
            start: 起始整数，例如 2；用于生成 ?participant2 等变量名。

        返回:
            变量名到匹配与过滤的字符串映射。
        """

        clauses: dict[str, str] = {}
        predicate = self._expand_term(self._PARTICIPANT_PREDICATE, prefixes)
        next_index = start
        for participant in participants:
            var_name = f"?participant{next_index}"
            iri = self._format_value(participant, prefixes)
            clauses[var_name] = f"?s {predicate} {var_name} .\n  FILTER({var_name} = {iri})"
            next_index += 1
        return clauses

    def _render_time_window(self, prefixes: dict[str, str]) -> str:
        """
        生成时间谓词的 OPTIONAL 绑定子句。

        参数:
            prefixes: 前缀映射，例如 {"prov": "http://www.w3.org/ns/prov#"}。

        返回:
            尝试绑定时间变量的 OPTIONAL 语句字符串。
        """

        predicate = self._expand_term(self._TIME_PREDICATE, prefixes)
        return f"OPTIONAL {{ ?s {predicate} ?__time . }}"

    def _render_time_filters(self, time_window: TimeWindow | None) -> list[str]:
        """
        根据时间窗口生成 FILTER 条件。

        参数:
            time_window: TimeWindow，例如 TimeWindow(gte=datetime(2024, 1, 1))。

        返回:
            由字符串组成的列表，每个元素都是 FILTER 片段。
        """

        filters: list[str] = []
        if time_window and time_window.gte:
            filters.append(self._datetime_filter(">=", time_window.gte))
        if time_window and time_window.lte:
            filters.append(self._datetime_filter("<=", time_window.lte))
        return filters

    def _datetime_filter(self, op: str, value: datetime) -> str:
        """
        构造时间比较的 FILTER 子句。

        参数:
            op: 比较操作符字符串，例如 ">=","<="。
            value: datetime，例如 datetime(2024, 1, 1, 0, 0, 0)。

        返回:
            表示时间过滤的字符串，例如
            "FILTER(?__time >= \"2024-01-01T00:00:00Z\"^^xsd:dateTime)"。
        """

        literal = self._format_datetime(value)
        return f"FILTER(?__time {op} {literal})"

    def _render_order_clause(self, dsl: QueryDSL, select_vars: list[str]) -> str:
        """
        依据 DSL 中的排序信息生成 ORDER BY 子句。

        参数:
            dsl: QueryDSL，例如 sort={"by": "__time", "order": "desc"}。
            select_vars: 当前 SELECT 变量列表，例如 ["?s", "?p", "?o"]。

        返回:
            ORDER BY 字符串；如果 DSL 未指定排序，则返回空字符串。
        """

        order_spec = dsl.sort or {}
        order_field = str(order_spec.get("by", "?s"))
        if not order_field.startswith("?"):
            order_field = f"?{order_field}"
        if order_field not in select_vars:
            select_vars.append(order_field)
        direction = order_spec.get("order", "asc").lower()
        func = "DESC" if direction == "desc" else "ASC"
        # 追加 ?s 作为稳定排序的次级键，避免排序结果非确定
        return f"ORDER BY {func}({order_field}) ?s"

    def _render_limit_clause(self, dsl: QueryDSL) -> str:
        """
        依据分页信息生成 LIMIT 子句。

        参数:
            dsl: QueryDSL，其中 page.size 范围通常在 1~1000，示例 100。

        返回:
            LIMIT 字符串，例如 "LIMIT 100"。
        """

        size = max(1, dsl.page.size)
        return f"LIMIT {size}"

    def _render_offset_clause(self, dsl: QueryDSL) -> str:
        """
        依据分页信息生成 OFFSET 子句。

        参数:
            dsl: QueryDSL，其中 page.offset 示例 200；传入 None 或 0 表示不偏移。

        返回:
            OFFSET 字符串或空字符串。
        """

        offset = dsl.page.offset or 0
        if offset <= 0:
            return ""
        return f"OFFSET {offset}"

    def _wrap_graph(self, where_lines: Iterable[str], graph: str | None) -> str:
        """
        为 WHERE 片段增加 GRAPH 包裹（若指定命名图）。

        参数:
            where_lines: 可迭代对象，每个元素是 WHERE 内的一行，例如 ["?s ?p ?o ."]。
            graph: 命名图 IRI，例如 "http://data.example/graph/a"；None 表示默认图。

        返回:
            对应的 WHERE 主体文本，包含正确缩进。
        """

        lines = [line.rstrip() for line in where_lines if line.strip()]
        body = "\n  ".join(lines)
        if graph:
            return f"  GRAPH <{graph}> {{\n  {body}\n  }}"
        return f"  {body}"

    def _expand_term(self, term: str, prefixes: dict[str, str]) -> str:
        """
        将 DSL 中的字段转换为合法的 SPARQL IRI 或前缀形式。

        参数:
            term: 字符串，例如 "sf:participant" 或 "http://example.org/name"。
            prefixes: 前缀映射，例如 {"sf": "http://semanticforge.ai/ontologies/core#"}。

        返回:
            合法的 SPARQL 项，例如 "sf:participant" 或 "<http://example.org/name>"。
        """

        if self._PREFIX_PATTERN.match(term):
            prefix = term.split(":", 1)[0]
            if prefix not in prefixes:
                raise ValueError(f"未注册的前缀: {prefix}")
            return term
        if term.startswith("http://") or term.startswith("https://"):
            return f"<{term}>"
        raise ValueError(f"无法解析的 RDF 标识: {term}")

    def _format_value(self, value: Any, prefixes: dict[str, str]) -> str:
        """
        将任意值格式化为 SPARQL 可用的字面量或 IRI。

        参数:
            value: 任意类型，例如 "Alice"、True、42、datetime.now()。
            prefixes: 前缀映射，供 CURIE 校验使用，例如 {"sf": "http://..."}。

        返回:
            可直接拼入查询的字符串表示。
        """

        if isinstance(value, str):
            # 字符串优先判断是否为已声明的前缀形式
            if self._PREFIX_PATTERN.match(value):
                prefix = value.split(":", 1)[0]
                if prefix not in prefixes:
                    raise ValueError(f"未注册的前缀: {prefix}")
                return value
            if value.startswith("http://") or value.startswith("https://"):
                return f"<{value}>"
            return f"\"{self._escape_string(value)}\""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                raise ValueError("不支持 NaN/Inf 的浮点值")
            return str(value)
        if isinstance(value, datetime):
            return self._format_datetime(value)
        return f"\"{self._escape_string(str(value))}\""

    def _format_datetime(self, value: datetime) -> str:
        """
        将 datetime 转换为 xsd:dateTime 字面量。

        参数:
            value: datetime，例如 datetime(2024, 1, 1, 12, 0, 0)。

        返回:
            字符串，例如 "\"2024-01-01T12:00:00Z\"^^xsd:dateTime"。
        """

        iso = value.isoformat()
        if iso.endswith("+00:00"):
            iso = iso[:-6] + "Z"
        return f"\"{iso}\"^^xsd:dateTime"

    @staticmethod
    def _escape_string(text: str) -> str:
        """
        转义字符串中的反斜杠与引号。

        参数:
            text: 原始文本，例如 "Alice \"Bob\""。

        返回:
            已转义的字符串，例如 Alice \"Bob\"。
        """

        return text.replace("\\", "\\\\").replace("\"", "\\\"")

    @staticmethod
    def _to_iterable(value: Any) -> Iterable[Any]:
        """
        将单值包装为可迭代对象。

        参数:
            value: 任意对象，例如 "Alice" 或 ["Alice", "Bob"]。

        返回:
            可迭代对象，确保调用方总是可以遍历。
        """

        if isinstance(value, (list, tuple, set)):
            return value
        return [value]

    @staticmethod
    def _split_range(value: Any) -> tuple[Any | None, Any | None]:
        """
        解析 range 操作符指定的上下限。

        参数:
            value: 支持两种形式:
                1. 字典，例如 {"gte": 1, "lte": 10} 或 {"min": 5, "max": 9}。
                2. 序列，长度必须为 2，例如 [1, 10]。

        返回:
            (下限, 上限) 二元组，任一端缺失时返回 None。
        """

        if isinstance(value, dict):
            return value.get("gte") or value.get("min"), value.get("lte") or value.get("max")
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return value[0], value[1]
        raise ValueError("range 参数需要 [min, max] 或 {gte,lte} 格式")

    @staticmethod
    def _parse_expand_item(item: str) -> tuple[str, str | None]:
        """
        将 expand 条目解析为谓词与别名。

        参数:
            item: 字符串，例如 "sf:hasActor as actor" 或 "sf:hasObject"。

        返回:
            (谓词, 别名) 二元组；若未指定别名则返回 None。
        """

        if " as " in item:
            predicate, alias = item.split(" as ", 1)
            alias = alias.strip()
            if not alias.startswith("?"):
                alias = f"?{alias}"
            return predicate.strip(), alias
        return item.strip(), None
