事务（Transaction）
===================

概览
----

事务相关模块包含四部分：

- Upsert 规划与建模（`upsert`）：`Triple/Provenance/UpsertRequest/UpsertPlanner/UpsertPlan/UpsertStatement`
- 事务执行管理（`manager`）：`TransactionManager.upsert` 执行计划、冲突检查、回滚保护与审计
- 批处理写入（`batch`）：`BatchOperator.apply_template` 用模板化方式高吞吐写入
- 审计日志（`audit`）：`AuditLogger` 记录操作与请求日志（可选）


Upsert 建模与规划（upsert）
---------------------------

主要类型
~~~~~~~~

- `Triple(s: str, p: str, o: str, lang: str | None = None, dtype: str | None = None)`：三元组，支持语言或数据类型
- `Provenance(evidence: str | None = None, confidence: float | None = None, source: str | None = None)`：溯源信息
- `UpsertRequest(graph: GraphRef, triples: list[Triple], upsert_key: Literal["s","s+p","custom"] = "s", custom_key_fields: list[str] | None = None, merge_strategy: Literal["replace","ignore","append"] = "replace", provenance: Provenance | None = None)`
- `UpsertStatement(sparql: str, key: str, strategy: Literal["replace","ignore","append"], triples: list[Triple], requires_snapshot: bool)`
- `UpsertPlan(graph_iri: str, statements: list[UpsertStatement], request_hash: str)`

UpsertPlanner
~~~~~~~~~~~~~

- `plan(request: UpsertRequest) -> UpsertPlan`
  - 按 `upsert_key` 分组并依 `merge_strategy` 生成 UPDATE 语句：
    - `replace`：构造 DELETE/INSERT，以 key 范围内的目标值整体替换
    - `ignore`：仅在不存在完全相同三元组时插入
    - `append`：直接追加 INSERT
  - 返回：包含语句集合与请求哈希（用于审计去重）

示例
~~~~

.. code-block:: python

   from sf_rdf_acl.transaction.upsert import Triple, UpsertRequest, UpsertPlanner
   from sf_rdf_acl.query.dsl import GraphRef

   req = UpsertRequest(
       graph=GraphRef(model="demo", version="v1", env="dev"),
       triples=[Triple(s="<http://ex/e/1>", p="rdf:type", o="sf:Entity")],
       upsert_key="s",
       merge_strategy="replace",
   )
   plan = UpsertPlanner().plan(req)
   for st in plan.statements:
       print(st.strategy, st.sparql[:80])


事务执行管理（manager）
----------------------

TransactionManager
~~~~~~~~~~~~~~~~~~

- `begin() -> str`：开始事务，返回事务 ID
- `commit(tx_id: str) -> None`：提交（当前实现为空操作，预留扩展）
- `rollback(tx_id: str) -> None`：回滚（当前实现为空操作，预留扩展）
- `upsert(request: UpsertRequest, *, trace_id: str, actor: str | None = None) -> dict`
  - 作用：执行 Upsert 计划；对 `ignore` 策略做重复检查；必要时构建回滚快照；支持审计写入
  - 返回：`{"graph": iri, "applied": N, "statements": K, "conflicts": [..], "txId": id, "durationMs": ms, "auditId": id_or_none}`

示例
~~~~

.. code-block:: python

   from sf_rdf_acl.transaction.manager import TransactionManager
   from sf_rdf_acl.transaction.upsert import Triple, UpsertRequest
   from sf_rdf_acl.query.dsl import GraphRef

   mgr = TransactionManager()
   req = UpsertRequest(
       graph=GraphRef(model="demo", version="v1", env="dev"),
       triples=[Triple(s="<http://ex/e/1>", p="rdfs:label", o="示例", lang="zh")],
       upsert_key="s+p",
       merge_strategy="ignore",
   )
   summary = await mgr.upsert(req, trace_id="t-upsert-1", actor="alice")
   print(summary["applied"], len(summary["conflicts"]))


批处理写入（batch）
-------------------

BatchOperator
~~~~~~~~~~~~~

- 构造：`BatchOperator(client: RDFClient, batch_size: int = 1000, max_retries: int = 3)`
- `apply_template(template: BatchTemplate, graph_iri: str, *, trace_id: str, dry_run: bool = False) -> BatchResult`
  - `BatchTemplate(pattern: str, bindings: list[dict[str, str]])`
  - `BatchResult(total: int, success: int, failed: int, failed_items: list[dict], duration_ms: float)`

示例
~~~~

.. code-block:: python

   from sf_rdf_acl.transaction.batch import BatchOperator, BatchTemplate
   from sf_rdf_acl.connection.client import FusekiClient

   template = BatchTemplate(
       pattern="{?s} <http://ex/p> {?o} .",
       bindings=[
           {"?s": "<http://ex/s/1>", "?o": '"v1"'},
           {"?s": "<http://ex/s/2>", "?o": '"v2"'},
       ],
   )

   # client 可复用 FusekiClient
   client = FusekiClient(endpoint="http://127.0.0.1:3030", dataset="acl")
   op = BatchOperator(client, batch_size=1000)
   result = await op.apply_template(template, "http://ex/graph/demo", trace_id="t-batch-1")
   print(result.success, result.failed)


审计日志（audit）
-----------------

AuditLogger（可选能力）
~~~~~~~~~~~~~~~~~~~~~~~

- 构造：`AuditLogger(dsn: str, schema: str)`（内部使用 SQLAlchemy Engine）
- `log_operation_async(...) -> str | None`：写入 `rdf_operation_audit`，返回记录 ID
- `log_operation(...) -> str | None`：同步写入
- `log_request_async(...) -> None`：写入 `request_log`
- `log_request(...) -> None`：同步写入


自动文档（参考）
----------------

.. automodule:: sf_rdf_acl.transaction.manager
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: sf_rdf_acl.transaction.upsert
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: sf_rdf_acl.transaction.batch
   :members:
   :undoc-members:
   :show-inheritance:

