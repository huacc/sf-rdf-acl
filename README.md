SF‑RDF‑ACL（RDF Anti‑Corruption Layer）
=====================================

SF‑RDF‑ACL 是 SemanticForge 平台的 RDF 反腐层（library）。面向上层 API、算法与业务服务，提供一致、可观测、可扩展的 RDF 访问能力：Fuseki 连接与熔断重试、查询 DSL 与 SPARQL 构建、命名图管理、事务式 Upsert、批处理、图投影、结果转换与 RDF* 溯源写入等。

特性一览
--------

- 稳健连接：超时控制、指数退避重试、熔断器、trace 透传与指标上报（`FusekiClient`）
- 查询构建：结构化 DSL 到 SELECT/CONSTRUCT，游标分页（`QueryDSL`、`SPARQLQueryBuilder`、`CursorPagination`）
- 命名图管理：创建、清空、条件删除、合并与快照（`NamedGraphManager`）
- 事务 Upsert：s / s+p / 自定义键分组，replace/ignore/append 策略，冲突检测与可回滚（`UpsertPlanner`、`TransactionManager`）
- 批处理写入：模板化 INSERT DATA，分批与单条自动重试（`BatchOperator`）
- 图投影：GraphJSON 与边列表输出，适配可视化与图算法（`GraphProjectionBuilder`）
- 结果转换：CONSTRUCT/Turtle → JSON‑LD/简化 JSON；SELECT 绑定结果标准化（`GraphFormatter`、`ResultMapper`）
- 溯源写入：RDF* 断言与业务元数据注入（`ProvenanceService`）

目录结构
--------

- `src/sf_rdf_acl/` 核心库代码（connection、query、transaction、graph、converter、provenance、utils）
- `docs/` Sphinx 文档（指南、示例、API 参考）
- `tests/` 单元与集成测试
- `examples/` 可直接运行的示例脚本
- `pyproject.toml` 构建与依赖配置（Python ≥ 3.12）

环境要求
--------

- Python 3.12+
- Jena Fuseki 4.x（兼容标准 HTTP/SPARQL 接口）
- 可选：PostgreSQL（启用审计 `AuditLogger` 时）

安装与开发
----------

本地开发（推荐可编辑安装）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\pip install -e .

# 若同时开发 sf-common，可并行安装
# .\.venv\Scripts\pip install -e ..\sf-common
```

运行测试：

```powershell
.\.venv\Scripts\pip install pytest pytest-cov pytest-asyncio
.\.venv\Scripts\python -m pytest -q
```

快速开始（代码示例）
------------------

1) 连接与查询

```python
from sf_rdf_acl.connection.client import FusekiClient

client = FusekiClient(endpoint="http://127.0.0.1:3030", dataset="acl")
res = await client.select("SELECT * WHERE { ?s ?p ?o } LIMIT 10", trace_id="t-1")
print(res["vars"], len(res["bindings"]))

graph = await client.construct("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o } LIMIT 100")
print(graph["turtle"][:200])
```

2) DSL 构建与分页

```python
from sf_rdf_acl.query.dsl import QueryDSL, Filter
from sf_rdf_acl.query.builder import SPARQLQueryBuilder
from sf_rdf_acl.query.pagination import CursorPage, CursorPagination

dsl = QueryDSL(type="raw", filters=[Filter(field="rdfs:label", operator="contains", value="示例")])
sparql = SPARQLQueryBuilder().build_select(dsl)

page1 = CursorPage(cursor=None, size=100)
q1 = SPARQLQueryBuilder().build_select_with_cursor(dsl, page1, sort_key="?s")
# 执行 q1 后拿到最后一条，生成下一页游标
cursor = CursorPagination.encode_cursor({"s": {"type": "uri", "value": "http://ex/e/100"}}, sort_key="?s")
page2 = CursorPage(cursor=cursor, size=100)
q2 = SPARQLQueryBuilder().build_select_with_cursor(dsl, page2, sort_key="?s")
```

3) 命名图管理

```python
from sf_rdf_acl.graph.named_graph import NamedGraphManager
from sf_rdf_acl.query.dsl import GraphRef

mgr = NamedGraphManager()
await mgr.create(GraphRef(model="demo", version="v1", env="dev"), trace_id="t-create")
await mgr.clear(GraphRef(model="demo", version="v1", env="dev"), trace_id="t-clear")
snap = await mgr.snapshot(GraphRef(model="demo", version="v1", env="dev"), trace_id="t-snap")
```

4) 事务 Upsert

```python
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
summary = await mgr.upsert(req, trace_id="t-upsert", actor="alice")
print(summary)
```

5) 图投影与结果转换

```python
from sf_rdf_acl.graph.projection import GraphProjectionBuilder
from sf_rdf_acl.converter.graph_formatter import GraphFormatter
from sf_rdf_acl.query.dsl import GraphRef

payload = await GraphProjectionBuilder().project(GraphRef(model="demo", version="v1", env="dev"), profile="default")
graphjson = payload.graph

formatter = GraphFormatter()
jsonld = formatter.format_graph((await client.construct("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"))["turtle"],
                                format_type="json-ld",
                                context={"sf": "http://semanticforge.ai/ontologies/core#"})
```

6) RDF* 溯源写入

```python
from sf_rdf_acl.provenance.provenance import ProvenanceService
from sf_rdf_acl.transaction.upsert import Triple, Provenance
from sf_rdf_acl.query.dsl import GraphRef

svc = ProvenanceService()
triples = [
    Triple(s="<http://ex/e/1>", p="rdf:type", o="sf:Entity"),
    Triple(s="<http://ex/e/1>", p="rdfs:label", o="示例", lang="zh"),
]
prov = Provenance(evidence="import", confidence=0.98, source="http://job/123")
result = await svc.annotate(GraphRef(model="demo", version="v1", env="dev"), triples, prov, trace_id="t-prov")
print(result["count"])
```

配置（Settings）
---------------

库默认通过 `common.config.ConfigManager` 读取平台配置（YAML/环境变量）。典型字段：

```yaml
rdf:
  endpoint: http://127.0.0.1:3030
  dataset: acl
  timeout: { default: 30, max: 120 }
  retries: { max_attempts: 3, backoff_seconds: 0.5, backoff_multiplier: 2.0, jitter_seconds: 0.1 }
  circuit_breaker: { failureThreshold: 5, recoveryTimeout: 30, recordTimeoutOnly: false }
  auth: { username: "", password: "" }
security:
  trace_header: X-Trace-Id
graph:
  projection_profiles:
    default: { limit: 1000, includeLiterals: false, directed: true, edgePredicates: ["rdf:type"] }
```

文档与示例
----------

- 指南与示例：`docs/guides/*`、`docs/examples/*`
- API 参考：`docs/api/*`（Sphinx 自动与手工补充混合）
- 本地构建文档：

```powershell
# 若已安装 sphinx
sphinx-build -b html docs _build/html
```

测试与质量
----------

- 测试：`pytest -q`
- 建议：Conventional Commits，PEP8/Black/Flake8/MyPy（按平台统一规范）

许可与合规
----------

- License：Proprietary（见 `pyproject.toml`）
- 存储与安全：不在仓库提交密钥；支持 trace id 透传；错误码与异常统一于 `common.exceptions`

反馈与贡献
----------

- Issue / PR：欢迎基于小步变更提交，附带动机、影响范围与验证方法
- 代码与文档变更建议一并附测试或示例
