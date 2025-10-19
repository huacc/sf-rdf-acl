# RDF 防腐层深化设计 v2

> 适用范围：SemanticForge 平台后端 `sf-rdf-acl` 库。该库提供 RDF 防腐层能力，供上层 API 服务、算法服务等调用；不再直接承担 REST API 或图算法执行职责。

## 1. 设计目标与定位

- **唯一入口**：对上层系统屏蔽 Fuseki/SPARQL 细节，提供统一的查询、写入、命名图管理、图数据投影与 RDF* 溯源能力。
- **稳定抽象**：通过 DSL、规划器、格式化器确保调用侧只关注业务语义，底层 RDF 存储、认证、超时、熔断策略由本库托管。
- **轻量依赖**：面向库模式交付，依赖 `sf-common` 提供的配置、日志、异常与观测能力，可嵌入任意上层服务。
- **扩展预留**：保留对外部算法服务、API Schemas 的集成点，但实现与部署由独立项目负责。

## 2. 模块结构

源代码根目录：`src/sf_rdf_acl`

| 模块 | 主要职责 |
| --- | --- |
| `connection/` | `FusekiClient` 封装 HTTP 调用、重试、熔断、指标上报能力。 |
| `query/` | `QueryDSL`、`SPARQLQueryBuilder` 将业务查询 DSL 转换为 SPARQL。 |
| `transaction/` | `UpsertPlanner`、`TransactionManager` 负责 upsert 规划、冲突检测与回滚。`audit.py` 提供 PostgreSQL 审计记录封装。 |
| `converter/` | `ResultMapper` 将绑定结果统一为 JSON；`GraphFormatter` 负责图结果格式化（当前支持 Turtle 透传，预留扩展点）。 |
| `graph/` | `NamedGraphManager` 执行命名图 create/clear/merge/snapshot；`GraphProjectionBuilder` 将 GraphRef/QueryDSL 投影为 GraphJSON/边列表。 |
| `provenance/` | `ProvenanceService` 处理 RDF* 溯源片段生成与写入。 |
| `utils/` | 通用工具，如基于配置的图 IRI 解析。 |
| `__init__.py` | 汇总公共出口，便于上层 `from sf_rdf_acl import ...` 方式调用。 |

## 3. 核心能力

### 3.1 查询 DSL 与执行
- `QueryDSL` 支持实体/关系/事件/原始查询、过滤条件（包含 exists/isNull/range/regex 等）与时间窗、分页、排序。
- `SPARQLQueryBuilder` 自动补全前缀、构造 SELECT/CONSTRUCT 语句，支持 expand 字段、参与者过滤、时间戳筛选。
- `FusekiClient.select/construct` 统一处理 trace 透传、超时、重试、熔断与指标打点（来自 `common.observability`）。

### 3.2 写入与 Upsert
- `UpsertPlanner` 按 `upsert_key` (`s`/`s+p`/`custom`) 分桶并生成 SPARQL Update，包括 replace/ignore/append 策略。
- `TransactionManager` 负责执行计划、调用 Fuseki 更新、处理冲突（ignore 模式查询存在性）、必要时构建 rollback snapshot。
- 可选 `AuditLogger` 将操作写入 PostgreSQL `rdf_operation_audit` 与 `request_log`，用于合规追踪。

### 3.3 命名图生命周期
- 通过 `NamedGraphManager` 提供 `create` / `clear` / `conditional_clear` / `merge` / `snapshot`，并在 dry-run 模式下返回预估影响。
- 图 IRI 解析统一走配置模板（model/version/env/scenario）。

### 3.4 图数据投影
- `GraphProjectionBuilder.project` 支持以 GraphRef 或 QueryDSL 作为数据源，结合配置化的投影 profile 输出 GraphJSON 与边列表。
- Profile 中的 edgePredicates、includeLiterals、limit 等参数与 `sf-common` 的 `GraphConfig` 对齐。
- 与图算法执行的集成点通过返回的 edgelist/graphJSON 暴露，上层算法服务（`graph-algorithm-service`）负责后续处理。

### 3.5 结果映射与格式化
- `ResultMapper` 将 SPARQL 绑定值转为携带类型/原始值的结构，支持 int/decimal/bool/dateTime 等常见类型转换。
- `GraphFormatter` 当前保持 Turtle 透传；如需 JSON-LD/GraphJSON 格式，可在此扩展实现。

### 3.6 RDF* 溯源
- `ProvenanceService` 基于 RDF* 语法生成 `<<s p o>> prov:...` 片段，支持 evidence/confidence/source 及外部 metadata。
- 自动追加 `prov:generatedAtTime`（UTC）并写入指定命名图。

## 4. 外部依赖与边界

- **配置与基础设施**：依赖 `sf-common` 提供的 `ConfigManager`、`Settings`、异常体系、日志工厂与观测指标定义，上层需确保加载对应 YAML（位于 `projects/sf-common/config`）。
- **算法能力**：图算法执行已迁移至 `graph-algorithm-service`，本库仅负责提供规范化的图数据输入。
- **API 合约**：REST 接口层迁移至新的 API 服务（引用 `sf-api-schemas`），本库作为依赖以库方式注入。
- **监控指标**：使用 `prometheus_client` 组合 `common.observability.metrics`，由消费方暴露。

## 5. 配置与运行要求

1. 上层服务需在启动前通过 `ConfigManager.load(<path>)` 载入配置，至少包含 `default.yaml` / 环境覆盖；关键字段：
   - `rdf.endpoint` / `rdf.dataset` / `rdf.auth`；
   - `rdf.timeout` / `rdf.retries` / `rdf.circuitBreaker`；
   - `graph.projectionProfiles`、`graph.algorithm`；
   - `postgres`（如启用审计）。
2. 依赖声明：`sf-rdf-acl` 自身依赖 `sf-common`、`httpx`、`rdflib`、`SPARQLWrapper` 等；上层服务应同时安装 `fastapi`、`sqlalchemy`、`prometheus_client` 等 `sf-common` 间接需求。
3. 推荐运行环境：Python 3.12+，虚拟环境隔离（例如 `.venv`）。

## 6. 非目标与限制

- 不再包含 REST Router、OpenAPI 定义或 FastAPI App 初始化（由 API 服务仓库负责）。
- 不直接执行图算法、不维护算法配置；只提供原始/投影数据接口。
- 不负责 OMM 目录/模型资源的持久化管理，上层可按需组合。
- `GraphFormatter` 仅做透传，若需更多格式需在消费方或后续迭代中实现。
- Fuseki 是默认后端，其他 RDF Store 的适配需扩展 `RDFClient` 协议。

## 7. 质量与测试

- 单元测试位于 `tests/`，覆盖查询构建、Fuseki 客户端熔断、Upsert 冲突与回滚、命名图操作、图投影、溯源写入等核心逻辑。
- 执行方式：`python -m pytest -q`（示例：在 `.venv` 中运行）。
- 关键依赖通过 `pytest-asyncio` 驱动异步测试，确保客户端行为符合预期。
- 推荐在 CI 中收集覆盖率与 Prometheus 指标模拟。

## 8. 版本记录

- **2025-10-17**
  - 更新定位为「库模式 RDF 防腐层」，移除图算法执行、REST Router 等已迁移内容。
  - 补充与 `sf-common`、`graph-algorithm-service`、`sf-api-schemas` 的边界说明。
  - 调整模块结构表与核心能力章节，使其与现有代码一致。

