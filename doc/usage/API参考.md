# RDF 防腐层 API 参考

本文件列出了 `sf-rdf-acl` 对外可直接调用的核心类与函数，补充参数、返回值说明，并给出示例脚本引用路径。示例脚本位于 `examples/` 目录，可配合文档中的说明快速运行。

## 快速导航
- [配置加载](#配置加载)
- [RDF 客户端](#rdf-客户端)
- [查询 DSL 与构建](#查询-dsl-与构建)
- [Upsert 与事务](#upsert-与事务)
- [命名图管理](#命名图管理)
- [图数据投影](#图数据投影)
- [结果映射与格式化](#结果映射与格式化)
- [RDF* 溯源记录](#rdf-溯源记录)

---

## 配置加载

### `common.config.ConfigManager.load(*, env: str | None = None, override_path: str | None = None) -> ConfigManager`
- **作用**：初始化全局配置单例，`sf-rdf-acl` 内部依赖此配置获取 RDF、命名图与审计设置。
- **参数**：
  - `env`：可选环境名（development/testing/production 等），默认读取 `APP_ENV`。
  - `override_path`：额外的 YAML 配置文件路径，后加载并覆盖默认值。
- **返回**：`ConfigManager` 单例，可通过 `.settings` 获得完整的 `Settings`。
- **示例**：`examples/helpers.py` 中的 `load_demo_config()`。

> **提示**：调用任何依赖配置的类前请先执行 `ConfigManager.load(...)`。

---

## RDF 客户端

### `sf_rdf_acl.connection.FusekiClient`
高性能 HTTP 客户端，封装超时、重试、熔断与指标观察逻辑。可直接使用，也可在单元/示例中替换为自定义实现满足 `RDFClient` 协议。

#### 主要方法
| 方法 | 说明 | 返回值 |
| --- | --- | --- |
| `await select(query: str, *, timeout: int | None = 30, trace_id: str | None = None)` | 执行 SPARQL SELECT，返回绑定结果 | `{"vars": [...], "bindings": [...], "stats": {...}}` |
| `await construct(query: str, *, timeout: int | None = 30, trace_id: str | None = None)` | 执行 SPARQL CONSTRUCT，返回 Turtle 字符串 | `{"turtle": str, "stats": {...}}` |
| `await update(update: str, *, timeout: int | None = 30, trace_id: str | None = None)` | 执行 SPARQL UPDATE（INSERT/DELETE 等） | `{"status": int, "durationMs": float}` |
| `await health()` | 返回客户端自检信息 | `{"ok": bool, ...}` |

- **示例**：`examples/run_query.py`、`examples/run_upsert.py` 使用了实现了相同接口的 `DemoFusekiClient` 以便离线演示。

---

## 查询 DSL 与构建

### `sf_rdf_acl.query.dsl.QueryDSL`
- **用途**：声明式描述实体/关系/事件查询条件。
- **关键字段**：
  - `type`: `"entity" | "relation" | "event" | "raw"`
  - `filters`: `list[Filter]`，支持 `=`, `!=`, `in`, `range`, `contains`, `regex`, `exists`, `isNull` 等操作。
  - `time_window`: `TimeWindow(gte, lte)` 控制时间范围。
  - `page`: `Page(size, offset)`。
  - `sort`: `{"by": "?var", "order": "asc" | "desc"}`。
  - `prefixes`: 额外的命名空间映射。

### `sf_rdf_acl.query.dsl.Filter`
- `field`: 谓词（可为前缀形式如 `sf:relatesTo`）。
- `op`: 操作符。
- `value`: 操作对应值，`range` 支持 `{"gte": v1, "lte": v2}`。

### `sf_rdf_acl.query.builder.SPARQLQueryBuilder`
- **方法**：
  - `build_select(dsl: QueryDSL, *, graph: str | None = None) -> str`
  - `build_construct(dsl: QueryDSL, *, graph: str | None = None) -> str`
- **说明**：合并默认前缀、过滤条件、展开字段，输出可执行的 SPARQL。
- **示例**：`examples/run_query.py` 展示将 DSL 转换为查询语句并消费结果。

---

## Upsert 与事务

### `sf_rdf_acl.transaction.upsert.UpsertRequest`
- **字段**：
  - `graph`: `GraphRef`，目标命名图。
  - `triples`: `list[Triple]`，需写入的 RDF 三元组。
  - `upsert_key`: `"s" | "s+p" | "custom"`，控制去重维度。
  - `merge_strategy`: `"replace" | "ignore" | "append"`。
  - `provenance`: 可选 `Provenance` 信息。

### `sf_rdf_acl.transaction.upsert.Triple`
- `s`、`p`、`o`: 主体、谓词、宾语。
- `lang`: 字符串类型时的语言标签。
- `dtype`: 字面量类型 URI。

### `sf_rdf_acl.transaction.Manager.TransactionManager`
- **初始化参数**：
  - `planner`: 可传入自定义 `UpsertPlanner`（默认读取配置）。
  - `client`: 任何实现 `RDFClient` 协议的对象。
  - `audit_logger`: 可选 `AuditLogger`，用于写 PostgreSQL 审计。
- **关键方法**：
  - `await upsert(request: UpsertRequest, *, trace_id: str, actor: str | None = None) -> dict`
    - 返回字段：`{"graph": str, "applied": int, "conflicts": list, "stats": {...}}`
  - `await begin()` / `await commit()` / `await rollback()`：目前为扩展占位。

- **示例**：`examples/run_upsert.py` 通过 `DemoFusekiClient` 演示 replace/append 场景。

### `sf_rdf_acl.transaction.audit.AuditLogger`
- **用途**：将操作写入 PostgreSQL。
- **主要方法**：`log_operation()`、`log_operation_async()`、`log_request()`。
- **示例**：`examples/run_upsert.py` 展示如何以同步方式记录审计信息。

---

## 命名图管理

### `sf_rdf_acl.graph.named_graph.NamedGraphManager`
- **初始化参数**：`client`, `settings` 均可选，默认基于配置创建 FusekiClient。
- **主要方法**：
  - `await create(graph: GraphRef, *, trace_id: str) -> dict`
  - `await clear(graph: GraphRef, *, trace_id: str) -> dict`
  - `await conditional_clear(graph: GraphRef, *, filters: dict | None, dry_run: bool, trace_id: str) -> dict`
  - `await merge(source: GraphRef, target: GraphRef, *, trace_id: str) -> dict`
  - `await snapshot(graph: GraphRef, *, trace_id: str) -> dict`
- **GraphRef 字段**：`name` 或 `model`+`version`+`env`+`scenario_id`。
- **示例**：`examples/manage_graphs.py` 展示创建、清理与快照操作。

---

## 图数据投影

### `sf_rdf_acl.graph.projection.GraphProjectionBuilder`
- **初始化参数**：
  - `client`: `RDFClient`，用于读取节点与边。
  - `builder`: 可选 `SPARQLQueryBuilder`。
  - `settings`: 可选 `Settings`。
- **主要方法**：
  - `await project(source: QueryDSL | GraphRef, profile: str, *, config: dict | None = None, trace_id: str | None = None) -> ProjectionPayload`
  - `await to_graphjson(...) -> dict`
  - `await to_edgelist(...) -> list[tuple[str, str, dict]]`
- **ProjectionPayload 字段**：`graph`、`edgelist`、`stats`、`profile`、`config`、`graph_iri`。
- **示例**：`examples/project_graph.py` 输出 GraphJSON 与边列表，可直接传给上层算法服务。

---

## 结果映射与格式化

### `sf_rdf_acl.converter.result_mapper.ResultMapper`
- `map_bindings(vars: list[str], bindings: list[dict]) -> list[dict]`
  - 将 SPARQL JSON 结果转换为携带 typed value 的字典序列。
  - 自动处理整数/浮点/布尔/日期时间等类型。
- **示例**：`examples/run_query.py` 展示映射后的数据结构。

### `sf_rdf_acl.converter.graph_formatter.GraphFormatter`
- `to_turtle(graph_ttl: str) -> str`
  - 当前实现原样返回，用于占位扩展。
- **备注**：可在本类新增 `to_jsonld`、`to_graphjson` 等方法，满足特定输出需求。

---

## RDF* 溯源记录

### `sf_rdf_acl.provenance.provenance.ProvenanceService`
- **初始化参数**：与其他服务一致，可注入自定义 `RDFClient` 与 `Settings`。
- **主要方法**：
  - `await annotate(graph: GraphRef, triples: list[Triple], provenance: Provenance, *, trace_id: str | None = None, metadata: dict | None = None) -> dict`
    - 返回写入目标图、语句列表与数量。
- **Provenance 字段**：`evidence`, `confidence`, `source`。
- **示例**：`examples/write_provenance.py` 构造 RDF* 语句并打印最终写入内容。

---

## 相关类型索引

| 类型 | 说明 | 所在路径 |
| --- | --- | --- |
| `GraphRef` | 命名图引用（名称或 model/version/env） | `sf_rdf_acl.query.dsl` |
| `Page` / `TimeWindow` | 查询分页与时间窗口结构 | `sf_rdf_acl.query.dsl` |
| `ProjectionPayload` | 图投影结果数据类 | `sf_rdf_acl.graph.projection` |
| `Provenance` | Upsert 溯源元信息 | `sf_rdf_acl.transaction.upsert` |
| `Triple` | RDF 三元组定义 | `sf_rdf_acl.transaction.upsert` |

---

## 更多资源
- 示例脚本目录：`examples/`
- 示例运行说明：参见仓库 `README.md - 示例快速开始` 章节。
- 设计背景：`doc/design/RDF防腐层深化设计.md`

如在扩展或调用中遇到问题，可在示例脚本基础上构建最小可复现场景进行调试。
