浜嬪姟锛圱ransaction锛?===================

姒傝
----

浜嬪姟鐩稿叧妯″潡鍖呭惈涓夐儴鍒嗭細

- Upsert 瑙勫垝涓庡缓妯★紙`upsert`锛夛細`Triple/Provenance/UpsertRequest/UpsertPlanner/UpsertPlan/UpsertStatement`
- 浜嬪姟鎵ц绠＄悊锛坄manager`锛夛細`TransactionManager.upsert` 鎵ц璁″垝銆佸啿绐佹鏌ャ€佸洖婊氫繚鎶や笌瀹¤
- 鎵瑰鐞嗗啓鍏ワ紙`batch`锛夛細`BatchOperator.apply_template` 鐢ㄦā鏉垮寲鏂瑰紡楂樺悶鍚愬啓鍏?- 瀹¤鏃ュ織锛坄audit`锛夛細`AuditLogger` 璁板綍鎿嶄綔涓庤姹傛棩蹇楋紙鍙€夛級


Upsert 寤烘ā涓庤鍒掞紙upsert锛?---------------------------

涓昏绫诲瀷
~~~~~~~~

- `Triple(s: str, p: str, o: str, lang: str | None = None, dtype: str | None = None)`锛氫笁鍏冪粍锛屾敮鎸佽瑷€鎴栨暟鎹被鍨?- `Provenance(evidence: str | None = None, confidence: float | None = None, source: str | None = None)`锛氭函婧愪俊鎭?- `UpsertRequest(graph: GraphRef, triples: list[Triple], upsert_key: Literal["s","s+p","custom"] = "s", custom_key_fields: list[str] | None = None, merge_strategy: Literal["replace","ignore","append"] = "replace", provenance: Provenance | None = None)`
- `UpsertStatement(sparql: str, key: str, strategy: Literal["replace","ignore","append"], triples: list[Triple], requires_snapshot: bool)`
- `UpsertPlan(graph_iri: str, statements: list[UpsertStatement], request_hash: str)`

UpsertPlanner
~~~~~~~~~~~~~

- `plan(request: UpsertRequest) -> UpsertPlan`
  - 鎸?`upsert_key` 鍒嗙粍骞朵緷 `merge_strategy` 鐢熸垚 UPDATE 璇彞锛?    - `replace`锛氭瀯閫?DELETE/INSERT锛屼互 key 鑼冨洿鍐呯殑鐩爣鍊兼暣浣撴浛鎹?    - `ignore`锛氫粎鍦ㄤ笉瀛樺湪瀹屽叏鐩稿悓涓夊厓缁勬椂鎻掑叆
    - `append`锛氱洿鎺ヨ拷鍔?INSERT
  - 杩斿洖锛氬寘鍚鍙ラ泦鍚堜笌璇锋眰鍝堝笇锛堢敤浜庡璁″幓閲嶏級

绀轰緥
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


浜嬪姟鎵ц绠＄悊锛坢anager锛?----------------------

TransactionManager
~~~~~~~~~~~~~~~~~~

- `begin() -> str`锛氬紑濮嬩簨鍔★紝杩斿洖浜嬪姟 ID
- `commit(tx_id: str) -> None`锛氭彁浜わ紙褰撳墠瀹炵幇涓虹┖鎿嶄綔锛岄鐣欐墿灞曪級
- `rollback(tx_id: str) -> None`锛氬洖婊氾紙褰撳墠瀹炵幇涓虹┖鎿嶄綔锛岄鐣欐墿灞曪級
- `upsert(request: UpsertRequest, *, trace_id: str, actor: str | None = None) -> dict`
  - 浣滅敤锛氭墽琛?Upsert 璁″垝锛涘 `ignore` 绛栫暐鍋氶噸澶嶆鏌ワ紱蹇呰鏃舵瀯寤哄洖婊氬揩鐓э紱鏀寔瀹¤鍐欏叆
  - 杩斿洖锛?    `{"graph": iri, "applied": N, "statements": K, "conflicts": [..], "txId": id, "durationMs": ms, "auditId": id_or_none}`

绀轰緥
~~~~

.. code-block:: python

   from sf_rdf_acl.transaction.manager import TransactionManager
   from sf_rdf_acl.transaction.upsert import Triple, UpsertRequest
   from sf_rdf_acl.query.dsl import GraphRef

   mgr = TransactionManager()
   req = UpsertRequest(
       graph=GraphRef(model="demo", version="v1", env="dev"),
       triples=[Triple(s="<http://ex/e/1>", p="rdfs:label", o="绀轰緥", lang="zh")],
       upsert_key="s+p",
       merge_strategy="ignore",
   )
   summary = await mgr.upsert(req, trace_id="t-upsert-1", actor="alice")
   print(summary["applied"], len(summary["conflicts"]))


鎵瑰鐞嗗啓鍏ワ紙batch锛?-------------------

BatchOperator
~~~~~~~~~~~~~

- 鏋勯€狅細`BatchOperator(client: RDFClient, batch_size: int = 1000, max_retries: int = 3)`
- `apply_template(template: BatchTemplate, graph_iri: str, *, trace_id: str, dry_run: bool = False) -> BatchResult`
  - `BatchTemplate(pattern: str, bindings: list[dict[str, str]])`
  - `BatchResult(total: int, success: int, failed: int, failed_items: list[dict], duration_ms: float)`

绀轰緥
~~~~

.. code-block:: python

   from sf_rdf_acl.transaction.batch import BatchOperator, BatchTemplate

   template = BatchTemplate(
       pattern="{?s} <http://ex/p> {?o} .",
       bindings=[
           {"?s": "<http://ex/s/1>", "?o": '"v1"'},
           {"?s": "<http://ex/s/2>", "?o": '"v2"'},
       ],
   )

   # client 鍙鐢?FusekiClient
from sf_rdf_acl.connection.client import FusekiClient
   client = FusekiClient(endpoint="http://127.0.0.1:3030", dataset="acl")
   op = BatchOperator(client, batch_size=1000)
   result = await op.apply_template(template, "http://ex/graph/demo", trace_id="t-batch-1")
   print(result.success, result.failed)


瀹¤鏃ュ織锛坅udit锛?-----------------

AuditLogger锛堝彲閫夎兘鍔涳級
~~~~~~~~~~~~~~~~~~~~~~~

- 鏋勯€狅細`AuditLogger(dsn: str, schema: str)`锛堝唴閮ㄤ娇鐢?SQLAlchemy Engine锛?- `log_operation_async(...) -> str | None`锛氬啓鍏?`rdf_operation_audit`锛岃繑鍥炶褰?ID
- `log_operation(...) -> str | None`锛氬悓姝ュ啓鍏?- `log_request_async(...) -> None`锛氬啓鍏?`request_log`
- `log_request(...) -> None`锛氬悓姝ュ啓鍏?

鑷姩鏂囨。锛堝弬鑰冿級
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

