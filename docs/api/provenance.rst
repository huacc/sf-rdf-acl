溯源（Provenance）
=================

概览
----

`ProvenanceService` 将业务侧三元组与溯源信息转换为 RDF* 语句，通过 SPARQL UPDATE
写入到目标命名图。支持附带业务元数据、自动生成 UTC 时间戳等。


ProvenanceService
-----------------

公共方法
~~~~~~~~

- `annotate(graph: GraphRef, triples: list[Triple], provenance: Provenance, *, trace_id: str | None = None, metadata: dict | None = None) -> dict`
  - 用途：将三元组写入命名图，并为每条三元组附加 RDF* 溯源断言。
  - 参数：
    - `graph` 目标命名图引用（`GraphRef`）
    - `triples` 三元组列表（`Triple(s, p, o, lang?, dtype?)`），不能为空
    - `provenance` 溯源信息（`Provenance(evidence?, confidence?, source?)`）
    - `trace_id` 可选追踪 ID
    - `metadata` 业务扩展字段（将映射为额外谓词，如 `sf:operator` 等）
  - 返回：`{"graph": iri, "statements": ["<<s p o>> ..."], "count": N}`
  - 异常：`ValueError` 当 `triples` 为空或无法解析图 IRI


使用示例
~~~~~~~~

.. code-block:: python

   from sf_rdf_acl.provenance.provenance import ProvenanceService
   from sf_rdf_acl.transaction.upsert import Triple, Provenance
   from sf_rdf_acl.query.dsl import GraphRef

   svc = ProvenanceService()
   triples = [
       Triple(s="<http://ex/e/1>", p="rdf:type", o="sf:Entity"),
       Triple(s="<http://ex/e/1>", p="rdfs:label", o="示例", lang="zh"),
   ]
   prov = Provenance(evidence="import", confidence=0.98, source="http://job/123")

   result = await svc.annotate(
       GraphRef(model="demo", version="v1", env="dev"),
       triples,
       prov,
       trace_id="t-prov-1",
       metadata={"operator": "alice", "batchId": "20251018"},
   )
   print(result["count"])  # 写入的 RDF* 片段条数


自动文档（参考）
----------------

.. automodule:: sf_rdf_acl.provenance.provenance
   :members:
   :undoc-members:
   :show-inheritance:

