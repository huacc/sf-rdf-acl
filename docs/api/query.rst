查询（Query）
=============

概览
----

查询相关模块包括：

- DSL 建模（`sf_rdf_acl.query.dsl`）：`QueryDSL`/`GraphRef` 等结构化入参
- 查询构建（`sf_rdf_acl.query.builder`）：由 DSL 生成 SELECT/CONSTRUCT 语句
- 分页工具（`sf_rdf_acl.query.pagination`）：基于游标的分页编码/解码与过滤构造


查询 DSL（dsl）
---------------

主要模型
~~~~~~~~

- `Page(size=100, offset=None)`：分页参数
- `TimeWindow(gte: datetime | None, lte: datetime | None)`：时间窗
- `Filter(field: str, operator: Literal["=","!=",">",">=","<","<=","in","range","contains","regex","exists","isNull"], value: Any)`
- `Aggregation(function: Literal["COUNT","SUM","AVG","MIN","MAX","GROUP_CONCAT"], variable: str, alias: str | None, distinct: bool=False, separator: str | None=None)`
- `GroupBy(variables: list[str])`
- `QueryDSL(type: Literal["entity","relation","event","raw"], filters: list[Filter]=[], expand: list[str]=[], time_window: TimeWindow|None=None, participants: list[str]=[], scenario_id: str|None=None, include_subgraph: bool=False, page: Page=Page(), sort: dict|None=None, prefixes: dict[str,str]|None=None, aggregations: list[Aggregation]|None=None, group_by: GroupBy|None=None, having: list[Filter]|None=None)`
- `GraphRef(name: str|None=None, model: str|None=None, version: str|None=None, env: Literal["dev","test","prod"]|None=None, scenario_id: str|None=None)`
- `SPARQLRequest(sparql: str, type: Literal["select","construct"] = "select", timeout: int | None = 30)`

用法示例
~~~~~~~~

.. code-block:: python

   from sf_rdf_acl.query.dsl import QueryDSL, Filter, TimeWindow
   from datetime import datetime

   dsl = QueryDSL(
       type="entity",
       filters=[Filter(field="rdfs:label", operator="contains", value="示例")],
       time_window=TimeWindow(gte=datetime(2024, 1, 1)),
       prefixes={"sf": "http://semanticforge.ai/ontologies/core#"},
   )


查询构建（builder）
-------------------

SPARQLQueryBuilder
~~~~~~~~~~~~~~~~~~

- `build_select(dsl: QueryDSL, *, graph: str | None = None) -> str`
  - 用途：由 DSL 生成 SELECT 查询。
- `build_construct(dsl: QueryDSL, *, graph: str | None = None) -> str`
  - 用途：由 DSL 生成 CONSTRUCT 查询。
- `build_select_with_cursor(dsl: QueryDSL, cursor_page: CursorPage, sort_key: str = "?s", *, graph: str | None = None) -> str`
  - 用途：生成带游标分页的 SELECT 查询。

SPARQLSanitizer（辅助）
~~~~~~~~~~~~~~~~~~~~~~

- `escape_uri(uri: str) -> str`：校验并转义 IRI
- `escape_literal(value: str, datatype: str | None=None) -> str`：转义字面量
- `validate_prefix(prefix: str) -> bool`：校验前缀名

示例（构建与执行）
~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from sf_rdf_acl.query.builder import SPARQLQueryBuilder
   from sf_rdf_acl.query.dsl import QueryDSL
   from sf_rdf_acl.connection.client import FusekiClient

   builder = SPARQLQueryBuilder()
   sparql = builder.build_select(QueryDSL(type="raw"))

   client = FusekiClient(endpoint="http://127.0.0.1:3030", dataset="acl")
   res = await client.select(sparql, trace_id="t-q-1")
   print(res["vars"], len(res["bindings"]))


游标分页（pagination）
----------------------

主要类型
~~~~~~~~

- `CursorPage(cursor: str | None = None, size: int = 100)`：分页入参
- `PageResult(results: list[dict], next_cursor: str | None, has_more: bool, total_estimate: int | None = None)`：分页结果承载
- `CursorPagination.encode_cursor(last_item: dict, sort_key: str) -> str`：生成下一页游标
- `CursorPagination.decode_cursor(cursor: str) -> dict`：解析游标
- `CursorPagination.build_cursor_filter(cursor_data: dict, sort_key: str) -> str`：构造 FILTER 片段

示例
~~~~

.. code-block:: python

   from sf_rdf_acl.query.pagination import CursorPagination, CursorPage
   from sf_rdf_acl.query.builder import SPARQLQueryBuilder
   from sf_rdf_acl.query.dsl import QueryDSL

   # 首次无游标
   page = CursorPage(cursor=None, size=100)
   q1 = SPARQLQueryBuilder().build_select_with_cursor(QueryDSL(type="raw"), page, sort_key="?s")

   # 根据上一页最后一条记录生成游标
   cursor = CursorPagination.encode_cursor({"s": {"type": "uri", "value": "http://ex/e/100"}}, sort_key="?s")
   page2 = CursorPage(cursor=cursor, size=100)
   q2 = SPARQLQueryBuilder().build_select_with_cursor(QueryDSL(type="raw"), page2, sort_key="?s")


自动文档（参考）
----------------

.. automodule:: sf_rdf_acl.query.dsl
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: sf_rdf_acl.query.builder
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: sf_rdf_acl.query.pagination
   :members:
   :undoc-members:
   :show-inheritance:

