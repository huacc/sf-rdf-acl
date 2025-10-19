# 快速开始

本指南帮助你在本地或 CI 环境下快速使用 SF-RDF-ACL 进行查询与写入。

## 环境准备
- Python 3.12+
- 已可访问的 Apache Jena Fuseki 服务（默认：`http://192.168.0.119:3030`，数据集：`semantic_forge_test`）
- 可选：PostgreSQL/Redis/Qdrant（与本库无强关联，仅在更广泛系统中使用）

```powershell
# 建议在项目目录下创建虚拟环境
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\pip install -e . -e ..\sf-common
```

## 读取示例（SELECT）
```python
from sf_rdf_acl import FusekiClient

client = FusekiClient(endpoint="http://192.168.0.119:3030", dataset="semantic_forge_test")
query = "SELECT * WHERE { ?s ?p ?o } LIMIT 1"
result = await client.select(query, trace_id="quickstart-select-001")
print(result["vars"], result["bindings"])
```

## 写入示例（UPDATE）
```python
from sf_rdf_acl import TransactionManager, UpsertRequest, Triple
from sf_rdf_acl.query.dsl import GraphRef

manager = TransactionManager()
ref = GraphRef(model="demo", version="v1", env="dev")
req = UpsertRequest(
    graph=ref,
    triples=[Triple(s="http://ex.com/a", p="http://ex.com/name", o="Alice")],
    upsert_key="s",
    merge_strategy="replace",
)
await manager.upsert(req, trace_id="quickstart-upsert-001", actor="demo")
```

## 清理示例（命名图）
```python
from sf_rdf_acl import NamedGraphManager
from sf_rdf_acl.query.dsl import GraphRef

m = NamedGraphManager()
ref = GraphRef(model="demo", version="v1", env="dev")
await m.clear(ref, trace_id="quickstart-clear-001")
```

## 常见参数说明
- `trace_id`：链路追踪 ID，便于日志与排障。
- `timeout`：超时时间（秒），默认 30，可在 `sf-common/config/default.yaml` 中集中配置。
- 命名图格式：`urn:sf:{model}:{version}:{env}`（可在配置中修改）。

```text
完成以上内容，你已经可以在真实 Fuseki 上进行端到端读写。
```

