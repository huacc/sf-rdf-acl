图（Graph）
===========

概览
----

本模块包含两类能力：

- 命名图管理（`NamedGraphManager`）：创建、清空、条件删除、合并、快照等。
- 图投影（`GraphProjectionBuilder`）：将查询结果投影为 GraphJSON 与边列表。


命名图管理（NamedGraphManager）
------------------------------

用途
~~~~

- 基于平台配置将 `GraphRef` 解析为具体命名图 IRI，并对该命名图执行管理操作。

公共方法
~~~~~~~~

- `create(graph: GraphRef, *, trace_id: str) -> dict`
  - 作用：创建命名图（若已存在返回 `status="exists"`）。
  - 返回：`{"graph": iri, "status": "created|exists"}`

- `clear(graph: GraphRef, *, trace_id: str) -> dict`
  - 作用：清空命名图所有三元组。
  - 返回：`{"graph": iri}`

- `conditional_clear(graph: GraphRef, condition: ClearCondition | None = None, *, dry_run: bool = True, trace_id: str, max_deletes: int = 10000, filters: dict | None = None) -> DryRunResult | dict`
  - 作用：按三元组模式与过滤器预估或执行删除；兼容 `filters={...}` 旧入参。
  - 入参说明：
    - `condition.patterns`: 至少一个三元组模式 `TriplePattern(subject, predicate, object)`，可包含变量如 `?s`, `?p`, `?o`
    - `condition.subject_prefix`: 主语 IRI 前缀过滤
    - `condition.predicate_whitelist`: 谓词白名单（IRI 或 CURIE）
    - `condition.object_type`: `"IRI"` 或 `"Literal"`
    - `dry_run`: True 仅估算和采样；False 执行删除（内含上限保护）
    - `max_deletes`: 非 dry-run 时的最大删除阈值
    - `filters`: 旧版兼容（`subject|predicate|object` 或 `s|p|o`）
  - 返回：
    - `dry_run=True`：`DryRunResult(graph_iri, estimated_deletes, sample_triples, execution_time_estimate_ms)`
    - `dry_run=False`：`{"graph": iri, "deleted_count": n, "execution_time_ms": x, "executed": true}`

- `merge(source: GraphRef, target: GraphRef, *, trace_id: str) -> dict`
  - 作用：`ADD GRAPH <source> TO GRAPH <target>`，将源图数据追加到目标图。
  - 返回：`{"source": iri, "target": iri}`

- `snapshot(graph: GraphRef, *, trace_id: str) -> dict`
  - 作用：对命名图做一次 `COPY GRAPH` 快照；快照 IRI 会基于配置模板与时间戳生成。
  - 返回：`{"graph": iri, "snapshotId": id, "snapshotGraph": iri}`

数据结构
~~~~~~~~

- `TriplePattern(subject: str | None, predicate: str | None, object: str | None)`：
  - `subject/predicate/object` 可为变量（如 `?s`）或 IRI/CURIE；`object` 可为字面量表达式（`"text"@zh`/`"2024"^^<xsd:int>`）。

- `ClearCondition(patterns: list[TriplePattern], subject_prefix: str | None = None, predicate_whitelist: list[str] | None = None, object_type: str | None = None)`

- `DryRunResult(graph_iri: str, estimated_deletes: int, sample_triples: list[dict], execution_time_estimate_ms: float)`

示例
~~~~

Dry-Run 预估删除
^^^^^^^^^^^^^^^^

.. code-block:: python

   from sf_rdf_acl.graph.named_graph import NamedGraphManager, TriplePattern, ClearCondition
   from sf_rdf_acl.query.dsl import GraphRef

   mgr = NamedGraphManager()
   cond = ClearCondition(patterns=[TriplePattern(subject="?s", predicate="rdf:type", object="sf:Deprecated")])
   dry = await mgr.conditional_clear(GraphRef(model="demo", version="v1", env="dev"), cond, trace_id="t-cc-1")
   print(dry.estimated_deletes, len(dry.sample_triples))

执行删除（含上限保护）
^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   done = await mgr.conditional_clear(
       GraphRef(model="demo", version="v1", env="dev"),
       cond,
       dry_run=False,
       max_deletes=5000,
       trace_id="t-cc-2",
   )
   print(done["deleted_count"])  # <= 5000，否则抛出 ValueError


图投影（GraphProjectionBuilder）
-------------------------------

用途
~~~~

- 将 `QueryDSL` 或 `GraphRef` 指定的数据源构造成 GraphJSON 与边列表。
- 支持 profile 覆盖（如 `limit`、`includeLiterals`、`edgePredicates`）。

公共方法
~~~~~~~~

- `project(source: QueryDSL | GraphRef, profile: str, *, config: dict | None = None, trace_id: str | None = None) -> ProjectionPayload`
  - 返回：`ProjectionPayload(graph, edgelist, stats, profile, config, graph_iri)`

- `to_graphjson(source: QueryDSL | GraphRef, *, profile: str, config: dict | None = None, trace_id: str | None = None) -> dict`
  - 返回：GraphJSON 字典，包含 `nodes/edges/directed/meta/stats` 等。

示例
~~~~

.. code-block:: python

   from sf_rdf_acl.graph.projection import GraphProjectionBuilder
   from sf_rdf_acl.query.dsl import GraphRef

   builder = GraphProjectionBuilder()
   payload = await builder.project(GraphRef(model="demo", version="v1", env="dev"), profile="default")
   print(payload.graph["nodes"], payload.stats)


自动文档（参考）
----------------

.. automodule:: sf_rdf_acl.graph.named_graph
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: sf_rdf_acl.graph.projection
   :members:
   :undoc-members:
   :show-inheritance:

