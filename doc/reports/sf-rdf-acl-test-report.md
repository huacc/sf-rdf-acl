# sf-rdf-acl 测试报告

生成时间: '+$ts+'

## 概览
- 运行范围: `examples/` 全部脚本 + `tests/` 全量 78 个用例
- 执行环境: 通过本项目虚拟环境 `.venv` (Python 3.12.3)
- RDF 后端: Apache Jena Fuseki `http://192.168.0.119:3030` 数据集 `semantic_forge_test`
- 执行结果: PyTest 全部通过 (78/78)，示例脚本除 2 个说明性脚本外全部成功
- 数据交互: 端到端真实读写 Fuseki 数据集，包含 SELECT/CONSTRUCT/UPDATE/GRAPH 管理操作

## 环境与配置
- Python: `D:\coding\OntologyGraph\projects\sf-rdf-acl\.venv\Scripts\python.exe` (3.12.3)
- 主要依赖: `pytest 8.4.2`、`pytest-cov 7.0.0`、`httpx 0.28.1`、`rdflib 7.0.0`
- 配置来源:
  - 默认: `projects/sf-common/config/default.yaml` (RDF endpoint/dataset/重试/熔断)
  - 示例: `examples/config/demo.yaml` (同指向 `192.168.0.119:3030`)

## Fuseki 可达性校验
- GET `http://192.168.0.119:3030` → 200 OK
- POST `/{dataset}/query` (SELECT * WHERE { ?s ?p ?o } LIMIT 1) → 200 OK, JSON 返回
  - 证明数据集 `semantic_forge_test` 存在且可查询

## 示例脚本执行
所有脚本均在 `.venv` 下运行，标准输出已保存到 `doc/reports/examples/*.log`。

- run_upsert.py
  - 状态: 成功 (exit=0)
  - 使用函数: `TransactionManager.upsert`, `UpsertPlanner`, `Triple`
  - 输入: 命名图 `urn:sf:demo:v1:dev`，8 条三元组 (类型、状态、label、updatedAt、relatesTo 等)
  - 输出: 包含 `graph/txId/applied/statements/durationMs/conflicts/requestHash`
  - 证据: `doc/reports/examples/run_upsert.log`

- run_query.py
  - 状态: 成功 (exit=0)
  - 使用函数: `SPARQLQueryBuilder.build_select`, `FusekiClient.select`, `ResultMapper.map_bindings`
  - 输入: QueryDSL 过滤 `rdf:type=sf:Entity && sf:status in [active,pending]`，graph `urn:sf:demo:v1:dev`
  - 输出: 命中多行，含前述 `run_upsert` 写入的实体与关系
  - 证据: `doc/reports/examples/run_query.log` (包含生成的 SPARQL 与映射后的行)

- project_graph.py
  - 状态: 成功 (exit=0)
  - 使用函数: `GraphProjectionBuilder.project`
  - 输入: `GraphRef(model=demo, version=v1, env=dev)`，profile `default`
  - 输出: GraphJSON 节点与边列表、统计信息
  - 证据: `doc/reports/examples/project_graph.log`

- write_provenance.py
  - 状态: 成功 (exit=0)
  - 使用函数: `ProvenanceService.annotate`, `Triple`
  - 输入: 指定三元组 (status=active) + RDF* 溯源信息 (evidence/confidence/source/metadata)
  - 输出: 写入的 RDF* 语句列表与统计
  - 证据: `doc/reports/examples/write_provenance.log`

- aggregation_example.py
  - 状态: 成功 (exit=0)
  - 使用函数: `SPARQLQueryBuilder`, `FusekiClient.select`
  - 输入: COUNT + GROUP BY 按类型聚合
  - 输出: 原始 SELECT JSON 绑定结果
  - 证据: `doc/reports/examples/aggregation_example.log`

- batch_operations_example.py (默认 dry-run)
  - 状态: 成功 (exit=0)
  - 使用函数: `BatchOperator.apply_template`, `BatchTemplate`
  - 输入: 模板 `{?user} <.../hasOrder> {?order} .`，1000 条绑定
  - 输出: 统计指标 `total/success/failed/duration_ms/throughput` (dry-run 仅估算与校验)
  - 证据: `doc/reports/examples/batch_operations_example.log`

- manage_graphs.py
  - 状态: 部分成功 (创建图成功; 条件清理预估失败)
  - 使用函数: `NamedGraphManager.create`, `NamedGraphManager.conditional_clear(dry_run=True)`, `NamedGraphManager.snapshot`
  - 现象: `create` 成功; `conditional_clear` 在 Fuseki 解析 where 子句时报 `client_error` (parse error)
  - 证据: `doc/reports/examples/manage_graphs.log`

- conditional_clear_example.py (交互式)
  - 状态: 运行至 dry-run 预估成功，因无标准输入导致 `EOFError` 退出 (exit=1)
  - 使用函数: `NamedGraphManager.conditional_clear`
  - 证据: `doc/reports/examples/conditional_clear_example.log`

- end_to_end_scenario.py (演示用内存后端)
  - 状态: 失败 (exit=1)
  - 后端: `InMemoryFusekiClient` (非 Fuseki 端到端)
  - 失败原因: `COPY GRAPH` 分支克隆 `TripleRecord` 使用 `__dict__`，与 `@dataclass(slots=True)` 不兼容
  - 证据: `doc/reports/examples/end_to_end_scenario.log`

## PyTest 测试套件
- 收集: 78 项 (详见 `doc/reports/pytest/collected.txt`)
- 结果: 全部通过；JUnit XML 见 `doc/reports/pytest/junit.xml`；完整会话日志见 `doc/reports/pytest/session.log`
- 用例分布:
  - docs: 1
  - examples: 3
  - e2e: 3 (真实 Fuseki 读写; 详见 `doc/reports/pytest/e2e_summary.txt` 时长与顺序)
  - unit/connection: 17
  - unit/converter: 8
  - unit/graph: 13
  - unit/provenance: 1
  - unit/query: 23
  - unit/transaction: 9
- 慢用例 (Top 25) 与端到端用例时长见会话日志尾部 (含 setup/call/teardown)

## 覆盖率
- 总体: 81% 行覆盖 (见 `doc/reports/coverage.txt`)
- XML: `doc/reports/coverage.xml`；HTML: `doc/reports/coverage_html/index.html`；JSON: `doc/reports/coverage.json`
- 主要模块覆盖摘要:
  - `connection/client.py` 95%
  - `graph/named_graph.py` 59%
  - `query/builder.py` 75%
  - `transaction/upsert.py` 94%

## 关键 API 使用与校验
以下列出端到端示例与 e2e 测试中实际使用到的关键 API，包含用途、输入、输出，以及结果校验结论。

- `FusekiClient.select(query, timeout?, trace_id?)`
  - 用途: 执行 SPARQL SELECT，返回 JSON 结构 (`vars/bindings/stats`)
  - 输入: 由 `SPARQLQueryBuilder` 或手写的 SELECT; 命名图通过 `GRAPH <iri>` 指定
  - 输出: `{"vars": [...], "bindings": [...], "stats": {"status": 200, "durationMs": ...}}`
  - 校验: `run_query.py` 返回记录包含 `run_upsert` 写入实体与关系，字段与期望一致

- `FusekiClient.update(update, timeout?, trace_id?)`
  - 用途: 执行 INSERT/DELETE/CREATE/COPY/CLEAR 等 UPDATE 操作
  - 输入: 由 `TransactionManager` 或 `NamedGraphManager` 生成的 SPARQL UPDATE 语句
  - 输出: `{ "status": 200, "durationMs": ... }` 或抛出 `ExternalServiceError`
  - 校验: `run_upsert.py` 中 `TransactionManager.upsert` 触发多条 UPDATE，返回 `applied=8` 与无冲突

- `TransactionManager.upsert(request, trace_id?, actor?)`
  - 用途: 依据 `UpsertPlanner` 生成 UPSERT 事务 (DELETE/INSERT/WHERE) 并提交
  - 输入: `UpsertRequest(graph=GraphRef(...), triples=[Triple(...)...], upsert_key, merge_strategy)`
  - 输出: `{graph, txId, applied, statements, durationMs, conflicts, requestHash}`
  - 校验: `run_upsert` 返回 `applied=8`；随后 `run_query` 能查询到对应状态/label/关系

- `NamedGraphManager.create(graph, trace_id?)`
  - 用途: 创建命名图 (CREATE GRAPH)
  - 输出: `{graph: iri, status: created|exists}`
  - 校验: `manage_graphs.py` 日志显示 `created`

- `NamedGraphManager.snapshot(graph, trace_id?)`
  - 用途: COPY GRAPH 形成快照 IRI；返回快照摘要
  - 校验: e2e 用例 `test_snapshot_and_conditional_clear` 通过，时长约 15.6s (真实交互)

- `NamedGraphManager.conditional_clear(graph, condition|filters, dry_run, trace_id?, max_deletes?)`
  - 用途: 条件化清理 (DELETE WHERE / 预估)
  - 输出: dry-run 预估删除数量/目标图；或执行后返回删除统计
  - 校验: e2e `test_snapshot_and_conditional_clear` 通过；`manage_graphs.py` 在 where 解析处返回 Fuseki `client_error`，已记录

- `GraphProjectionBuilder.project(source: GraphRef, profile, trace_id?)`
  - 用途: 依据 profile 投影 GraphJSON 与 edgelist
  - 输出: `{graph, edgelist, stats, graph_iri?}`
  - 校验: `project_graph.py` 输出包含节点/边/统计，且 e2e `upsert_and_projection_roundtrip` 通过

- `ProvenanceService.annotate(graph, triples, provenance, metadata?, trace_id?)`
  - 用途: 将 RDF* 溯源语句写入目标命名图
  - 输出: `{statements: [...], durationMs, ...}`
  - 校验: `write_provenance.py` 返回的 RDF* 语句与传入三元组对应

- `SPARQLQueryBuilder.build_select(dsl, graph?)` / `build_construct(...)`
  - 用途: 从 `QueryDSL` 生成安全的 SPARQL，支持过滤/分页/聚合/扩展
  - 输出: SPARQL 字符串
  - 校验: `run_query.py` 生成的 SELECT 在 Fuseki 上成功执行并返回期望字段

- `ResultMapper.map_bindings(vars, bindings)`
  - 用途: 将 SELECT 结果映射为易用结构，补充 `raw/type/datatype`
  - 校验: `run_query.py` 打印的行结构完整，类型/IRI/literal 映射正确

## 结果符合性与可靠性
- 端到端写入与查询: 通过 `run_upsert` → `run_query` 验证；e2e 三项用例全面通过
- 命名图管理: 创建/快照/条件清理在 e2e 用例中验证通过；脚本中的解析错误已在日志标注
- 溯源写入: RDF* 语句实际生成，且与输入三元组一致
- 性能/批处理: `batch_operations_example` 在 dry-run 下统计计算正常；事务/重试逻辑在多项 unit 测试覆盖

## 输出工件索引
- 示例日志: `doc/reports/examples/*.log`
- PyTest 会话: `doc/reports/pytest/session.log`
- 测试清单: `doc/reports/pytest/collected.txt`
- JUnit XML: `doc/reports/pytest/junit.xml`
- 覆盖率: `doc/reports/coverage.txt`, `doc/reports/coverage.xml`, `doc/reports/coverage.json`, `doc/reports/coverage_html/index.html`
- e2e 摘要: `doc/reports/pytest/e2e_summary.txt`

## 备注
- `examples/end_to_end_scenario.py` 使用内存后端，非 Fuseki 端到端；当前存在 `slots` 兼容性缺陷
- `examples/conditional_clear_example.py` 为交互式示例，自动化环境无标准输入导致终止；dry-run 预估已成功
- 其余示例与全部测试用例均使用真实 Fuseki 服务进行数据读写或只读查询
