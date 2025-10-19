# 基础用法

本节涵盖最常用的读取、写入、命名图操作。

## 读取一个三元组样例
```python
from sf_rdf_acl import FusekiClient

client = FusekiClient(endpoint="http://192.168.0.119:3030", dataset="semantic_forge_test")
sparql = "SELECT * WHERE { ?s ?p ?o } LIMIT 5"
result = await client.select(sparql, trace_id="ex-basic-001")
for row in result["bindings"]:
    print(row)
```

## 写入一个属性
```python
from sf_rdf_acl import TransactionManager, UpsertRequest, Triple
from sf_rdf_acl.query.dsl import GraphRef

m = TransactionManager()
ref = GraphRef(model="demo", version="v1", env="dev")
await m.upsert(
    UpsertRequest(
        graph=ref,
        triples=[Triple(s="http://ex.com/a", p="http://ex.com/name", o="Alice")],
        upsert_key="s",
        merge_strategy="replace",
    ),
    trace_id="ex-basic-002",
    actor="example",
)
```

## 创建并清空命名图
```python
from sf_rdf_acl import NamedGraphManager
from sf_rdf_acl.query.dsl import GraphRef

mgr = NamedGraphManager()
ref = GraphRef(model="demo", version="v1", env="dev")
await mgr.create(ref, trace_id="ex-basic-003")
await mgr.clear(ref, trace_id="ex-basic-004")
```

