# 最佳实践

本文总结使用 SF-RDF-ACL 进行 RDF 查询/写入时的建议做法。

## 追踪与可观测性
- 固定为每次调用设置 `trace_id`，便于日志与熔断统计定位问题。
- 使用小批量 + 重试的写入策略（见 `BatchOperator`），降低失败重试的放大效应。

## 查询安全
- 通过 `SPARQLSanitizer` 构造外部输入（IRI/文本）避免注入。
- 按需限制前缀与变量名规则，遵从 XML NCName 规范。

## 命名图管理
- 遵从统一命名规范 `urn:sf:{model}:{version}:{env}`，并在环境迁移时使用 `merge/snapshot`。
- 进行清理操作前先执行 `dry_run` 评估影响范围，设置 `max_deletes` 安全阈值。

## 事务与写入
- 使用 `UpsertPlanner` 选择合适的 `upsert_key` 和 `merge_strategy`。
- 生产环境开启审计（`audit_logger`）并保留 `request_hash` 以支持幂等与重放排障。

## 数据导出与展示
- `GraphFormatter` 输出 `json-ld` 时可自定义 `@context`，保持前端/第三方系统可读性。
- 图可视化建议使用 `GraphProjectionBuilder` 的 profile 控制节点类型与边谓词集合。

