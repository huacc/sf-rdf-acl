# SF-RDF-ACL 第一阶段（P0）1.1 query 模块改进与测试报告

报告时间：$((Get-Date).ToString('yyyy-MM-dd HH:mm'))
任务范围：1.1 query 模块改进（含 1.1.1 参数安全与 1.1.2 聚合查询支持）

## 改进内容概述

- 参数安全与防注入（任务1.1.1）
  - 新增 `SPARQLSanitizer` 安全工具类：
    - `escape_uri(uri)`：仅允许 http/https IRI，拒绝包含 `< > " { } | \ ^ `` 等危险字符；
    - `escape_literal(value, datatype)`：转义反斜杠与双引号，支持可选 xsd 数据类型；
    - `validate_prefix(prefix)`：前缀名 NCName 合法性校验。
  - 在 `SPARQLQueryBuilder` 中接入前缀校验与值安全转义：
    - 自定义前缀合并时进行前缀名与 IRI 校验；
    - 新增 `_escape_filter_value` 用于 HAVING/过滤场景的安全值拼接。

- 聚合查询支持（任务1.1.2）
  - DSL 新增：
    - `Aggregation` 与 `GroupBy`（dataclass）；
    - `QueryDSL` 扩展字段：`aggregations`、`group_by`、`having`；
    - `Filter` 支持 `operator` 别名与比较操作符 `> >= < <=`。
  - 构造器新增能力（`SPARQLQueryBuilder`）：
    - `SELECT` 生成聚合表达式（支持 `COUNT/SUM/AVG/MIN/MAX/GROUP_CONCAT`，含 `DISTINCT` 与 `SEPARATOR`）；
    - 生成 `GROUP BY` 与 `HAVING` 子句（HAVING 复用过滤表达式构建逻辑）。

## 变更文件

- 代码：
  - `src/sf_rdf_acl/query/builder.py`（新增 `SPARQLSanitizer`、聚合/HAVING 构建、前缀校验、中文注释）
  - `src/sf_rdf_acl/query/dsl.py`（重写：加入 Aggregation/GroupBy，扩展 QueryDSL 与 Filter，中文注释）
- 测试：
  - `tests/unit/query/test_aggregation.py`（现有，已通过）
  - `tests/unit/query/test_sparql_sanitizer.py`（新增，覆盖安全转义与恶意输入）

## 验收标准对应与结果

- 任务1.1.1（参数安全）
  - [x] SPARQLSanitizer 类实现完善
  - [x] 特殊字符正确转义/拦截（URI/字面量）
  - [x] 注入攻击测试通过（多组恶意输入均抛出异常）
  - [x] 类型提示完整
  - [x] 中文 Docstring 与参数说明

- 任务1.1.2（聚合能力）
  - [x] 支持 COUNT/SUM/AVG/MIN/MAX/GROUP_CONCAT
  - [x] 支持 DISTINCT 聚合
  - [x] 支持多变量 GROUP BY（变量自动补 `?` 前缀）
  - [x] 支持 HAVING 过滤（比较/IN/RANGE/正则/包含/BOUND）
  - [x] 生成的 SPARQL 片段语法正确（通过字符串断言与组合检测）
  - [x] 类型提示与中文注释

## 测试执行与结果

- 执行命令（建议）：
  - 仅运行本任务相关单元：`pytest tests/unit/query -q`
  - 运行全部测试：`pytest -q`

- 本地执行结果（本次提交前已验证）：
  - `tests/unit/query` 目录：12 通过，0 失败（含聚合用例与安全用例）
  - `tests/unit/graph/test_conditional_clear.py`：该文件验证 1.2 条件清理功能，非本次任务范围，当前仓库尚未实现对应功能，整仓运行时会因缺少 `ClearCondition` 等定义而失败；待 1.2 实施时修复。
  - `tests/test_rdf_end_to_end.py`：为端到端用例，依赖真实 Fuseki/Postgres 环境。由于环境差异，本地无法联通默认地址（192.168.0.119）。在用户自有环境中，如服务可用，建议执行完整用例进行验证。

- 端到端环境准备（如需验证 E2E）：
  - 设置环境变量或配置（projects/sf-common/config）：
    - RDF_ENDPOINT：指向可访问的 Fuseki（如 `http://<host>:3030`）
    - RDF_DATASET：确保存在对应数据集（如 `semantic_forge_test`）
    - POSTGRES_DSN：指向可访问的数据库（用于其他模块）
  - 确保账号权限、网络连通、数据集已创建。

## 注意与后续建议

- 本次严格按 1.1 改进计划落地，未触及 1.2/1.3 的实现；
- 建议下一阶段优先完成 1.2 条件清理（NamedGraphManager.conditional_clear），仓库已提供针对 1.2 的单元测试骨架，可在 StubFusekiClient 基础上开发并通过所有断言；
- 为保障安全，建议后续增加 `graph`、`transaction` 相关接口的输入校验与审计日志测试覆盖。

## 附录：关键接口注释（摘录）

- `SPARQLSanitizer.escape_uri(uri: str) -> str`
  - 功能：校验并返回 IRI（要求 http/https 且无危险字符）；
  - 入参：`uri`（非空 http/https IRI）；
  - 返回：原始 IRI 字符串；
  - 异常：非法 IRI 或包含危险字符将抛出 `ValueError`。

- `SPARQLSanitizer.escape_literal(value: str, datatype: str | None = None) -> str`
  - 功能：将字符串转为安全的 SPARQL 字面量表达式；
  - 入参：`value`（任意字符串）、`datatype`（可选 xsd IRI）；
  - 返回：`"..."` 或 `"..."^^<datatype>` 形式。

- `SPARQLQueryBuilder.build_select(dsl: QueryDSL, graph: str | None) -> str`
  - 功能：根据扩展 DSL 生成 SELECT 查询；
  - 说明：当 `dsl.aggregations` 非空时，SELECT 自动由聚合表达式与分组变量组成，并追加 GROUP BY/HAVING。

