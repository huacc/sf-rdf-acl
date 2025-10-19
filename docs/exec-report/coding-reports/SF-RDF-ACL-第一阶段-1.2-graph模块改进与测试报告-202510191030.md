# SF-RDF-ACL 第一阶段（P0）1.2 graph 模块改进与测试报告

报告时间：$(Get-Date -Format "yyyy-MM-dd HH:mm")
任务范围：1.2 graph 模块改进（条件清理功能：TriplePattern/ClearCondition/DryRunResult + NamedGraphManager.conditional_clear）

## 一、改进目标与验收对照
- 支持三元组模式删除（多模式拼接）
- 支持主语前缀过滤（STRSTARTS）
- 支持谓词白名单过滤（?p IN (<iri> ... )）
- 支持对象类型过滤（isIRI / isLiteral）
- Dry-Run 正确估算数量（并返回样本，估算时间）
- max_deletes 删除上限生效，超限抛出异常
- 异常处理完整

本次实现对照以上验收项逐项达成，并通过单元与端到端验证。

## 二、核心实现内容

- 新增数据类型（位于 `src/sf_rdf_acl/graph/named_graph.py`）
  - `TriplePattern`：三元组模式定义（subject/predicate/object 均可为空，空则回退变量 ?s/?p/?o；`to_sparql()` 生成一行 `s p o .`）。
  - `ClearCondition`：条件清理定义（`patterns`、`subject_prefix`、`predicate_whitelist`、`object_type`）。
  - `DryRunResult`：Dry-Run 结果（`graph_iri`、`estimated_deletes`、`sample_triples`、`execution_time_estimate_ms`）。

- 扩展/重写 `NamedGraphManager.conditional_clear`（新增同名覆盖，兼容旧接口）
  - 新签名：`conditional_clear(graph, condition=None, *, dry_run=True, trace_id, max_deletes=10000, filters=None)`
    - 保持对旧参数 `filters={subject|predicate|object}` 的兼容，通过 `_condition_from_filters()` 自动构造 `ClearCondition`；
    - Dry-Run：调用 `_estimate_conditional_delete()` 返回 `DryRunResult`；
    - 执行：先估算并核对 `max_deletes`，再执行 `DELETE { GRAPH <g> { ... } } WHERE { GRAPH <g> { ... } }`，返回 `{graph, deleted_count, execution_time_ms, executed}`。
  - 关键私有方法：
    - `_condition_from_filters()`：向后兼容旧接口，支持字面量/IRI/变量表达；
    - `_build_conditional_delete()`：生成 DELETE 与 WHERE 子句，拼入 FILTER（前缀/白名单/类型）；
    - `_estimate_conditional_delete()`：`SELECT (COUNT(*) AS ?count)` 与 `SELECT * ... LIMIT 10` 采样，返回估算结果。
  - 安全与健壮性：
    - 对 IRI/字面量采用最小安全转义；
    - 对删除数上限进行保护，超限即时抛错；
    - 兼容现有 `FusekiClient.select()` 返回结构（顶层 `bindings`）。

- 与现有功能的兼容
  - `tests/test_rdf_end_to_end.py` 原有 E2E 中调用 `conditional_clear(graph, filters=..., dry_run=False, ...)`；本次保持兼容并增加 `executed=True` 字段满足断言。

## 三、涉及文件与代码片段（节选）
- 主要改动文件：
  - `src/sf_rdf_acl/graph/named_graph.py`
    - 新增：`TriplePattern`、`ClearCondition`、`DryRunResult`
    - 新增（覆盖）：`NamedGraphManager.conditional_clear()`（新版接口）
    - 新增：`_condition_from_filters()`、`_build_conditional_delete()`、`_estimate_conditional_delete()`
- 现有辅助方法复用：`_escape_literal()`、`_resolve_graph()` 等

## 四、测试用例与结果

- 单元测试（Stub 客户端模拟数据，但遵循 SPARQL 结构）
  - 文件：`tests/unit/graph/test_conditional_clear.py`
  - 覆盖点：Dry-Run 输出结构、主语前缀过滤、谓词白名单过滤、删除上限限制、真实执行删除后空集校验。

- 端到端测试（真实 Fuseki + 数据集）
  - 复用已有 E2E：`tests/test_rdf_end_to_end.py::test_snapshot_and_conditional_clear`
  - 环境：`projects/sf-common/config/default.yaml` 默认指向 `http://192.168.0.119:3030`（无认证；见 `semantic-forge/deployment/service_deployment_info.md`）。
  - 步骤：插入一条三元组 -> 对图做快照 -> 验证快照包含 -> 执行条件清理（按 subject IRI）-> 再查应为空。

- 执行记录（本地运行）：
  - 命令：`pytest -q`
  - 结果：`20 passed, 2 warnings`（含 query/graph/transaction/projection 等全量测试）

## 五、如何在本地运行

1. 确保服务可用（参见 `semantic-forge/deployment/service_deployment_info.md`）
   - Fuseki: `http://192.168.0.119:3030`（无需认证）
   - PostgreSQL/Redis/Qdrant 同表格（非本用例直接依赖）
2. 根据需要调整 `projects/sf-common/config/*.yaml` 或设置环境变量覆盖（如 `RDF_ENDPOINT`, `RDF_DATASET`）。
3. 安装与运行：
   - 进入仓库根：`cd projects/sf-rdf-acl`
   - 运行测试：`.venv\Scripts\pytest -q`（Windows PowerShell）

## 六、备注与后续建议
- 本次严格对齐 P0-1.2 计划，保持与 E2E 的语义兼容；
- 建议后续对 `NamedGraphManager` 增加更多防护（例如基于白名单的谓词/命名图），并完善错误码；
- 同步在 API 层透出 Dry-Run 能力，便于前端确认删除影响面后再执行。

