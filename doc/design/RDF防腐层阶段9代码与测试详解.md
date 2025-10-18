# RDF防腐层阶段9代码与测试详解

> 参考文档：`docs/design/分阶段设计/一层服务/RDF防腐层深化设计/RDF防腐层深化设计.md`、`docs/design/分阶段设计/一层服务/OMM与RDF防腐层_统一需求说明.md`、`deployment/service_deployment_info.md`。

## 1. 背景与目标
- 本文面向平台研发、测试与运维同学，帮助在阅读源码前快速建立对 RDF 防腐层（ACL）的整体认知。
- 内容覆盖当前 `semantic-forge/backend` 目录下的全部 Python 代码、配置与脚本，逐一说明包/模块/类/函数的职责及调用关系，并结合阶段9新增的 E2E 套件输出测试说明。
- 文档同时回溯设计规范与阶段划分，标注仍需关注的风险（例如 DSL 过滤语义、`datetime.utcnow()` 的弃用警告等），方便后续阶段继续演进。

## 2. 代码结构总览
### 2.1 目录树（后端部分）
```
backend/
├── config/                 # 全局配置 YAML 与阶段专用配置
├── scripts/                # 本地/CI 脚本（lint、test、e2e、migration）
├── src/
│   ├── api/                # FastAPI 入口、依赖注入、路由
│   │   └── routers/v1/     # 版本化 REST 接口（rdf 与 graph）
│   ├── common/             # 配置、异常、日志、观测与 Envelope 模型
│   ├── config/             # 兼容旧调用的配置封装
│   ├── core/services/      # 业务编排（Query/Write/Graph/GraphOps/Provenance）
│   └── infrastructure/rdf/ # 与 RDF/Fuseki 交互的底座实现
└── tests/
    ├── unit/               # 单元测试，按 core/infrastructure 分组
    ├── integration/        # 组合图算法的端到端验证
    └── e2e/                # 阶段9全量场景（写入/查询/图管理/算法）
```

### 2.2 分层映射
| 分层 | 核心目录 | 说明 |
| --- | --- | --- |
| 接入层 | `src/api` | FastAPI 应用、路由、请求/响应模型、依赖注入。|
| 服务层 | `src/core/services` | 聚合配置与基础能力，对外暴露 Query/Write/Graph/GraphOps/Provenance 统一入口。|
| 基础能力层 | `src/infrastructure/rdf` | 实现 Fuseki 客户端、SPARQL DSL、图投影、事务写入等细粒度能力。|
| 通用能力 | `src/common` | SSOT 配置加载、错误码与 Envelope、日志与 Prometheus 指标。|
| 脚本与配置 | `backend/config`、`backend/scripts` | 环境配置、E2E 一键脚本、测试/迁移辅助工具。|

后续小节将逐层解构每个包、文件、类与函数的职责与交互关系。

## 3. 模块与类详解
### 3.1 `src/common` 通用层
| 文件 | 类 / 函数 | 说明 |
| --- | --- | --- |
| `common/config/settings.py` | `AppConfig`（应用名/环境/端口/调试开关）；`CorsConfig`（支持逗号分隔的来源列表，`_split_origins` 在模型验证前拆分字符串）；`CredentialsConfig`；`TimeoutConfig`；`RetryConfig`；`CircuitBreakerConfig`（熔断阈值/恢复时间/是否只统计超时）；`GraphProjectionProfileConfig`/`GraphAlgorithmLimitConfig`/`GraphConfig`（内含允许算法、节点/边上限、默认超时等）；`GraphNamingConfig`（命名图/快照格式模板）；`RDFConfig`（Fuseki 端点、数据集校验 `_validate_dataset`、鉴权、重试、熔断策略）；`PostgresConfig`（DSN、schema 与 `schema` 只读属性）；`RedisConfig`、`QdrantConfig`、`LoggingConfig`、`PaginationConfig`、`ContractConfig`、`SecurityConfig` 与顶层 `Settings`。所有模型通过 Pydantic 约束字段类型与上下限，为 ConfigManager 提供强类型支撑。|
| `common/config/loader.py` | `_backend_root()` 与 `_config_dir()` 负责定位配置根目录；`_load_yaml()` 安全读取 YAML；`_deep_merge()` 递归合并默认配置与环境覆写；`_set_in_mapping()`/`_parse_env_value()`/`_apply_env_overrides()` 将环境变量映射进配置树；`load_config()` 是唯一入口：依次加载 `.env`、默认 YAML、环境 YAML、自定义覆盖与环境变量，最后返回 `Settings`。|
| `common/config/exceptions.py` | `ConfigError`（带 `cause` 的异常基类）。|
| `common/config/registry.py` | `ConfigManager` 单例：懒加载 `Settings`，提供属性访问器（`app`/`rdf`/`postgres` 等）、`load()`/`current()`/`reload()`、`get(path, default)`、`snapshot()`；顶层 `load_settings()` 与阶段兼容函数 `settings_snapshot()`/`get_config_value()` 封装为外部调用提供便捷接口。|
| `common/models/envelope.py` | `PagingMeta`（分页元信息）、`EnvelopeMeta`（含版本号、分页信息，默认从 `ConfigManager` 读取契约版本）、`Envelope`（统一响应结构，提供 `success()`、`from_error()`、`json_ready()`）。所有 API 最终都返回 Envelope，确保 code/message/data/traceId/meta 一致。|
| `common/exceptions/codes.py` | `ErrorCode`（整型枚举覆盖 2000~510x，各类业务/外部错误）、`ErrorSpec`（HTTP 状态+默认消息），以及字典 `ERROR_SPECS` 与默认错误码。|
| `common/exceptions/api.py` | `APIError`（带 `code`、`http_status`、`details` 的基础业务异常）、`ExternalServiceError`（扩展诊断信息）、`ContractViolation`。|
| `common/exceptions/handlers.py` | FastAPI 异常适配器：`_ensure_trace_id()` 与 `_make_response()` 保证 `X-Trace-Id` 透传；`api_error_handler()`/`validation_error_handler()`（已改为 `exc.errors()` 兼容 Pydantic v2）/`http_exception_handler()`/`unhandled_exception_handler()` 统一输出 Envelope 并匹配错误码。`register_exception_handlers()` 在应用启动时统一注册。|
| `common/logging/logger_factory.py` | `JsonFormatter`（按配置输出结构化日志）与 `LoggerFactory`（`create_logger`、`get_default_handler`、`create_default_logger`），默认读取 `Settings.logging` 决定 JSON/Text 格式。|
| `common/observability/metrics.py` | 定义 `sf_fuseki_request_duration_seconds`、`sf_fuseki_requests_total`、`sf_fuseki_request_failures_total`、`sf_fuseki_circuit_breaker_state` 四类指标，并提供 `observe_fuseki_response()`/`observe_fuseki_failure()`/`set_fuseki_circuit_state()` 辅助 FusekiClient 记录性能/熔断状态。|
| `common/utils` | 仅含占位的 `__init__.py`，后续可放通用工具。|

### 3.2 `src/config`
| 文件 | 函数 | 说明 |
| --- | --- | --- |
| `config/config_manager.py` | `load_settings(env=None, override_path=None)`：调用 `ConfigManager.load` 并返回 `Settings`，用于脚本或旧代码兼容；`settings_snapshot()` 返回深拷贝；`get_config_value(path, default)` 透传到 `ConfigManager.current().get`。|

### 3.3 API 层
| 文件 | 类 / 函数 | 说明 |
| --- | --- | --- |
| `api/main.py` | 顶层 FastAPI 应用：加载 `.env` 和 Settings；配置 CORS、注册异常处理、挂载路由；`_current_trace_id()` 中间函数确保请求状态带 `trace_id`；HTTP 中间件 `inject_trace_id` 读取/生成 `X-Trace-Id` 并写回响应；公共健康检查 `/health`、根路径 `/`、`/api/v1/info`、`/metrics`、`/api/v1/status` 提供服务自检、配置快照、Prometheus 抓取等能力。|
| `api/deps.py` | 通过 `@lru_cache` 暴露依赖：`get_audit_logger()`、`get_transaction_manager()`、`get_named_graph_manager()`、`get_write_service()`、`get_graph_service()`、`get_graph_ops_service()`、`get_provenance_service()`——用于 FastAPI 路由按需注入，确保单实例复用。|
| `api/routers/deps.py` | Mock/stub 用途（在 E2E 中被重写）；线上默认引用 `api.deps`。|
| `api/schemas/rdf.py` | Request/Response Pydantic 模型：`QueryRequest/Result/Paging`、`GraphCommandRequest/Result`、`GraphClearRequest`、`GraphResult`、`WriteResult`、`EntityUpsertRequest`、`ProvenanceRequest/Result` 等，所有字段遵循设计文档的命名与校验约束。|
| `api/schemas/graph.py` | 图算法相关模型：`ProjectionProfile`、`AlgorithmExecutionContext`（`_ensure_one_source` 强制 `graph` 与 `dsl` 二选一）、`AlgorithmRequest`、`AlgorithmNativeRequest`、`AlgorithmResult`。|
| `api/routers/v1/rdf/query.py` | `/api/v1/rdf/query`/`construct`/`sparql` 路由：内部持有 `QueryService`，封装 Envelope、分页信息，并通过 `_trace_id()` 复用请求 trace。|
| `api/routers/v1/rdf/graphs.py` | 命名图创建/合并/快照/清理：依赖 `GraphService`，统一记录审计日志，`_handle_graph_command()` 校验动作并构建 `GraphCommandResult`，`_log_request()` 将请求参数哈希写入审计库。|
| `api/routers/v1/rdf/writes.py` | `/entities|relations|events/upsert`：调用 `WriteService`，封装冲突异常，并在 finally 中记录 RequestLog。|
| `api/routers/v1/rdf/provenance.py` | `/provenance/annotate`：调用 `ProvenanceService`，生成 Envelope。|
| `api/routers/v1/graph/algorithms.py` | `/graph/algorithms/run` 与 `/graph/algorithms/native/run`：依赖 `GraphOpsService` 执行投影 + 算法 / 原生 SPARQL，`_context_payload()` 兼容 DSL 与命名图。|

### 3.4 核心服务层 `src/core/services`
| 文件 | 类 / 方法 | 说明 |
| --- | --- | --- |
| `core/services/query_service.py` | `QueryService`：构造函数注入 `ConfigManager`、`SPARQLQueryBuilder`、`ResultMapper`、`RDFClient`。公开方法：`select(dsl, graph, timeout, trace_id)`——对 DSL 进行分页归一化、解析命名图、生成 SELECT SPARQL、通过 `ResultMapper` 转换绑定并拼装分页信息；`construct(...)`——生成 CONSTRUCT 查询并将 Turtle 转换为 GraphJSON；`execute_sparql(sparql, query_type, timeout, trace_id)` 支持原生 SELECT/CONSTRUCT；私有 `_normalize_pagination` 限定 page size、`_compose_paging` 推导 nextOffset、`_resolve_graph` 借助 `resolve_graph_iri`、`_turtle_to_graphjson` 使用 rdflib 构建图节点与边。|
| `core/services/write_service.py` | `WriteService`：依赖 `TransactionManager`、`NamedGraphManager`、`AuditLogger`；对外提供 `upsert_entities/relations/events()`，内部 `_perform_upsert()` 根据返回值判断冲突并抛出 `APIError`；`clear_graph()` 调用 `NamedGraphManager.clear()` 并封装结果；`audit_logger` 属性暴露内置审计记录器；`_resolve_graph()` 负责转换 GraphRef。|
| `core/services/graph_service.py` | 包装命名图操作：`create_graph`/`merge_graph`/`snapshot_graph`/`clear_graph` 分别调用 `NamedGraphManager` 对应方法，并通过 `_log_operation()` 以 `rdf.graph.*` 形式写审计库，哈希 payload 防止重复。|
| `core/services/graph_ops_service.py` | 算法统一入口：构造函数注入 projection/executor/client/mapper/audit；`run_projection()` 返回 GraphJSON；`run_algorithm()` 校验算法白名单与 k-hop 参数，调用 `GraphProjectionBuilder.project()` -> `_enforce_graph_limits()` -> `GraphAlgoExecutor.run()` -> 记录审计；`run_native()` 直接通过 `RDFClient` 执行 SELECT/CONSTRUCT 并封装指标；内部 `_create_client()` 复用 Settings 构建 `FusekiClient`，`_log_audit()` 记录算法执行信息。|
| `core/services/provenance_service.py` | `annotate()` 调用 `NamedGraphManager` + `TransactionManager` (间接) 记录 RDF* 溯源语句并写审计；`fetch_evidence()` 当前返回占位结果，阶段7遗留。|

### 3.5 基础能力层 `src/infrastructure/rdf`
| 子目录/文件 | 核心类 / 方法 | 说明 |
| --- | --- | --- |
| `connection/client.py` | `RDFClient` 协议约定 `select`/`construct`/`update`/`health` 签名；`FusekiClient` 实现 HTTP 交互：`select()`/`construct()`/`update()` 统一委托 `_execute()`，内部处理 trace header、超时、重试、熔断。熔断相关 `_ensure_circuit_allows()`/`_record_failure()`/`_record_success()` 与 `common.observability.metrics` 联动；`_should_retry()` 判断状态码是否重试；`_raise_http_error()` 将 HTTP 错误转换为 `ExternalServiceError`；`_resolve_timeout()` 保证超时值在默认/最大范围内。|
| `query/dsl.py` | `Page`（限制 size/offset）；`TimeWindow`；`Filter`（支持 =/!=/in/range/regex/exists/isNull 等操作符）；`QueryDSL`（包含 filters/expand/page/time_window/participants/sort/prefixes 等字段）；`GraphRef`（命名图定位字段）；`SPARQLRequest`（原生查询）。|
| `query/builder.py` | `SPARQLQueryBuilder`：`build_select()`/`build_construct()` -> `_build_query()`；内部 `_merge_prefixes`、`_render_filter`、`_render_expand`、`_render_participants`、`_render_time_window`、`_render_time_filters`、`_render_order_clause`、`_render_limit_clause`/`_render_offset_clause` 等构建 SPARQL 字符串；`_format_term`、`_expand_term` 解析前缀。|
| `converter/result_mapper.py` | `ResultMapper.map_bindings()` 按列遍历，使用 `_convert_cell()` 和 `_cast_value()` 根据 XSD 类型（整数、浮点、布尔、日期时间）与 RDF 类型转换 Python 值，保留原始值与语言标签。|
| `graph/named_graph.py` | `NamedGraphManager`：`create`/`clear`/`merge`/`snapshot` 直接拼接 SPARQL Update（`CREATE GRAPH`、`CLEAR GRAPH`、`ADD`、`COPY`），并使用 `resolve_graph_iri()` 生成图 IRI；内部 `_compose_snapshot()` 按 `settings.rdf.naming.snapshot_format` 构造快照标识。|
| `graph/projection.py` | `ProjectionPayload`（dataclass，封装 GraphJSON/边列表/统计/配置/图 IRI）；`GraphProjectionBuilder`：构造函数接入 `ConfigManager`、`RDFClient`、`SPARQLQueryBuilder`；`project()`、`to_graphjson()`、`to_edgelist()` 构建投影结果；内部 `_collect()` 执行 SPARQL、过滤边、收集节点类型；`_build_graph_query()` 根据 profile 拼接 GRAPH 查询；`_convert_to_graphjson()` 与 `_expand_to_iri()` 等工具方法提供边/节点转换与前缀展开。|
| `graph/ops.py` | `GraphAlgoExecutor` 接口、`NetworkXExecutor` 默认实现（`run` 分支 `pagerank`/`shortest_path`/`khop`，并提供 `_run_pagerank`、`_run_shortest_path`、`_run_khop`、`_convert_to_networkx` 等辅助方法）。|
| `provenance/provenance.py` | `ProvenanceClient` 抽象与 `ProvenanceService` 底层实现（写 RDF*）。|
| `transaction/upsert.py` | `Triple`/`Provenance` Pydantic 模型；`UpsertRequest`（支持 `upsert_key`=s/s+p/custom、`merge_strategy`=replace/ignore/append）；`UpsertStatement`/`UpsertPlan` 数据类；`UpsertPlanner` 核心方法：`plan()` 生成 `UpsertPlan`，调用 `_group_triples()`、`_compose_key()`、`_build_replace_statement()`（包含 `DELETE`/`INSERT`）、`_build_ignore_statement()`（`FILTER NOT EXISTS`）、`_build_append_statement()`、`_render_triple_block()` 等，最终返回 SPARQL Update 列表与请求哈希。|
| `transaction/manager.py` | `TransactionManager`：`begin()`/`commit()`/`rollback()` 预留扩展；`upsert()` 遍历计划并执行 `FusekiClient.update()`，在冲突时构建回滚栈并自动恢复；还负责调用 `AuditLogger.log_operation_async()` 记录执行统计。|
| `transaction/audit.py` | `AuditLogger`：异步/同步两套接口（`log_operation_async`/`log_operation` 与 `log_request_async`/`log_request`），将操作写入 `rdf_operation_audit`、`request_log` 表，异常时打印告警。|
| `utils.py` | `resolve_graph_iri(graph, settings)`：按 `GraphNamingConfig` 组合模型/版本/环境/场景生成命名图 IRI。|

### 3.6 脚本与配置
| 文件 | 说明 |
| --- | --- |
| `config/stage9_e2e.yaml` | 阶段9 E2E 执行专用配置：指定远端 Fuseki(`http://192.168.0.119:3030`)、数据集 `semantic_forge_test`、Postgres DSN、Redis/Qdrant 地址，确保测试脚本无散落配置。|
| `scripts/e2e_run.sh` / `.ps1` | 阶段9新增一键脚本：支持 `--config` 覆盖配置、`--junit` 输出 XML、`--no-junit` 关闭报告；自动设置 `APP_ENV`/`APP_CONFIG_PATH`，执行 `pytest backend/tests/e2e --maxfail=1`，完成后将 `_artifacts/stage9_results.json` 复制到 `out/e2e/`。非零退出码被原样返回，方便 CI 识别失败。|
| 其他脚本 | 现有 `lint.sh/.ps1`、`test_all.sh/.ps1`、迁移脚本保持不变，此处不再赘述。|

## 4. 调用流程与时序
### 4.1 查询 DSL 场景（`POST /api/v1/rdf/query`）
1. FastAPI 路由 `post_query()` 解析 `QueryRequest`，调用 `_trace_id()` 获取追踪号。
2. `QueryService.select()`
   - `_normalize_pagination()` 依据契约限制 page；
   - `_resolve_graph()` 调 `resolve_graph_iri()` 生成 IRI；
   - `SPARQLQueryBuilder.build_select()` 将 DSL 转成 SPARQL；
   - `FusekiClient.select()` 执行 HTTP 请求（含重试/熔断/指标）；
   - `ResultMapper.map_bindings()` 转换返回值；
   - `_compose_paging()` 生成分页元数据。
3. 路由包装 `Envelope` + `PagingMeta` 返回，`X-Trace-Id` 中间件补入响应头。

### 4.2 写入 Upsert 场景（`POST /api/v1/rdf/entities/upsert`）
```
客户端
  → FastAPI 路由 writes.post_entities_upsert
    → WriteService.upsert_entities
      → TransactionManager.upsert
        → UpsertPlanner.plan ⟶ 生成 SPARQL UPDATE 列表
        → FusekiClient.update ⟶ 执行 INSERT/DELETE
        → 遇到冲突则抛出 APIError(ErrorCode.IDEMPOTENCY_CONFLICT)
      → AuditLogger.log_operation_async 记录 rdf_operation_audit
    ← Envelope.success(data=WriteResult)
  ← 客户端收到 upserted/冲突信息 + trace 头
```

### 4.3 图算法场景（`POST /api/v1/graph/algorithms/run`）
1. 路由读取 `AlgorithmRequest`，检查 `GraphRef` 或 DSL。
2. `GraphOpsService.run_algorithm()`
   - `GraphProjectionBuilder.project()`：下发 CONSTRUCT SPARQL、根据 profile 过滤边，统计节点/边数。
   - `_enforce_graph_limits()`：基于 `settings.graph.algorithm` 判断是否超限。
   - `NetworkXExecutor.run()`：执行 `pagerank/shortest_path/khop` 并返回节点/指标。
   - `_log_audit()`：记录算法类型、参数、耗时等。
3. 最终 Envelope 带回 metrics，包括 `graphNodes`、`graphEdges`、算法结果等。

### 4.4 溯源写入（`POST /api/v1/rdf/provenance/annotate`）
- `ProvenanceService.annotate()` 组合命名图、RDF* 三元组与 `Provenance` 元数据，调用底层客户端写入并生成审计记录；当前 `fetch_evidence()` 为阶段7占位实现。

## 5. 测试用例详解
### 5.1 E2E 测试（`backend/tests/e2e/test_stage9_full_regression.py`）
| 用例 | 场景与输入 | 核心断言 |
| --- | --- | --- |
| `test_stage9_entity_lifecycle` | 通过 API 写入两条实体 + 类型声明，构造 DSL 过滤，随后原生 SPARQL 验证并清理命名图。 | `upserted=3`、`sparql_rows=1`；DSL 目前返回 0 行（已在阶段报告中记录需进一步排查）。|
| `test_stage9_graph_management` | 先写入源图，再执行 `create`、`snapshot`、`merge`，最后分别清空三张图。 | 三个动作均返回 `completed`，`snapshotId` 存在，合并后目标图可查询到新增关系。|
| `test_stage9_algorithm_khop` | 构造三节点链路，运行 `k-hop(k=2)`。 | `reachable=3`、`graphNodes=3`，验证算法路径包含两跳邻居。|
| `test_stage9_algorithm_rejects_unknown` | 提交未列入白名单的 `random_walk`。 | FastAPI 校验返回 `code=4001` 与 “请求参数校验失败”。|

辅助设施：`conftest.py` 加载 `stage9_e2e.yaml`、Stub `prometheus_client` 与 `api.routers.deps`，并提供 `ScenarioRecorder` 将所有输入/期望/实际保存在 `_artifacts/stage9_results.json`（阶段9执行报告引用该文件）。

### 5.2 集成测试（`tests/integration/test_graph_algorithms_end_to_end.py`）
| 用例 | 场景 | 核心断言 |
| --- | --- | --- |
| `test_pagerank_scores_expected_nodes` | 使用内存 Fuseki 构造样例图，运行 pagerank。 | 最高节点为 `http://example.com/Alice`，得分约 0.283170；`graphNodes=5`、`graphEdges=6`。|
| `test_shortest_path_returns_route` | 求最短路径 Alice→Dave。 | 节点顺序 Alice→Bob→Dave；`distance≈2`、`hops=2`。|
| `test_khop_returns_reachable_subgraph` | K-hop (k=2)。 | 距离字典符合预期，`reachable=5`。|

### 5.3 单元测试
| 文件 | 场景 | 核心断言 |
| --- | --- | --- |
| `unit/core/services/test_query_service.py` | Stub Fuseki + QueryService | LIMIT 与命名图解析正确；construct 返回 GraphJSON。|
| `unit/core/services/test_graph_ops_service.py` | Stub 投影/执行器 | run_algorithm 触发 executor + 审计；超过节点上限抛 `APIError`；`run_native` 返回 SELECT 行。|
| `unit/core/services/test_graph_service_extended.py` | GraphService + Stub NamedGraphManager | create_graph 返回 status 并记录审计。|
| `unit/core/services/test_provenance_service.py` | ProvenanceService annotate/fetch | 返回 RDF* 语句与 `auditId`；`fetch_evidence` 保持占位返回哈希。|
| `unit/core/services/test_write_service_extended.py` | WriteService upsert | 成功写入返回 `auditId`；冲突抛 `APIError`。|
| `unit/infrastructure/rdf/test_fuseki_client_resilience.py` | 熔断/指标 | 连续 503 导致熔断开启，Prometheus 指标置 1；恢复后 gauge 回 0；失败计数自增。|
| `unit/infrastructure/rdf/test_graph_projection_builder_async.py` | GraphProjectionBuilder | profile 过滤谓词；超出 limit 抛 `APIError`。|
| `unit/infrastructure/rdf/test_query_builder.py` | SPARQLQueryBuilder | SELECT 支持 filters+expand；时间窗口生成正确；CONSTRUCT 头部正确。|
| `unit/infrastructure/rdf/test_result_mapper.py` | ResultMapper | 数值/空单元/缺失单元转换正确。|
| `unit/infrastructure/rdf/test_transaction_manager.py` | TransactionManager | Append 策略会执行 UPDATE，结果包含 `audit-id`。|
| `unit/infrastructure/rdf/test_upsert_planner_extended.py` | UpsertPlanner | 针对 s+p upsert 生成单条语句并保留 key。|

## 6. 阶段9验证与产物
- `python -m pytest tests/e2e`（2025-10-16）全量通过，耗时约 51s；产生 14 条警告，均为 `datetime.utcnow()` 的弃用提示。
- `_artifacts/stage9_results.json` 记录了所有场景输入/期望/实际，阶段报告与测试报告已引用：
  - 状态均为 `passed`；`test_stage9_entity_lifecycle` 的 DSL 行为需要后续深入分析。
- `docs/design/分阶段设计/一层服务/RDF防腐层深化设计/reports/rdf-acl_stage9_execution_report.md` 与 `.../e2e测试报告/rdf-acl_stage9_e2e_report.md` 已同步记录执行情况与测试数据。

## 7. 风险与后续建议
1. **DSL 等值过滤**：现阶段 DSL 查询 IRI 时返回 0 行，建议检查 `SPARQLQueryBuilder._render_filter()` 对 `=` 与 IRI 的拼接，必要时在 `QueryService` 或 DSL 层面补充自动包裹 `<IRI>`。
2. **时间 API 弃用**：`AuditLogger`、`NamedGraphManager` 等仍使用 `datetime.utcnow()`，需在后续阶段统一替换为 `datetime.now(datetime.UTC)`，以避免 Python 3.12+ 的弃用告警。
3. **溯源查询能力**：阶段7遗留的 `fetch_evidence` 仍为占位实现，应结合业务场景补齐查询 SPARQL 与返回结构。
4. **远端依赖**：E2E 依赖外部 Fuseki/Postgres/Redis/Qdrant，建议在 CI/CD 中增加可用性探测或提供容器化 stub，确保自动回归稳定。
5. **配置 BOM**：部分源码（如路由模块）仍带 UTF-8 BOM，虽不影响运行，但建议通过 `scripts/lint` 或 IDE 统一移除，以便静态分析工具正常工作。

---
如需进一步追踪某个模块的执行细节，可结合本文件的模块说明与阶段设计原文中的 Mermaid 图，按照“路由 ➜ 服务 ➜ 基础能力 ➜ Fuseki/数据库”的链路逐层定位。欢迎在后续阶段补充新的测试或文档章节。
