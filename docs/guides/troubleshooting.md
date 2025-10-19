# 故障排查

本节汇总常见问题与定位思路。

## 连接失败（Fuseki）
- 现象：`ExternalServiceError: FUSEKI_CONNECT_ERROR`。
- 排查：
  - 检查 `sf-common/config/default.yaml` 中 `rdf.endpoint` 是否可达（如 `http://192.168.0.119:3030`）。
  - 检查数据集名称 `dataset` 是否存在，权限是否开放。
  - 若网络抖动频繁，调大 `retries.max_attempts` 与 `timeout.default`。

## 频繁熔断
- 现象：短时间大量失败后 `FusekiClient` 拒绝请求。
- 排查：
  - 查看告警指标 `observe_fuseki_failure/response`，确认失败原因是否为 5xx/超时。
  - 调整 `circuitBreaker.failureThreshold/recoveryTimeout`。

## 查询语法错误
- 现象：`400 Bad Request`，错误中包含 Fuseki 的解析报错信息。
- 排查：
  - 使用 `SPARQLQueryBuilder` 渐进构造查询，避免手写错误。
  - 检查前缀与变量命名是否符合规范。

## 清理误删
- 现象：执行清理后数据量异常下降。
- 排查：
  - 始终先执行 `dry_run=True` 获取 `estimated_deletes` 与 `sample_triples`。
  - 设置 `max_deletes`，超过阈值自动阻断删除。

## 性能退化
- 现象：端到端用时显著提升。
- 排查：
  - 使用批量写入（`BatchOperator`）避免单条吞吐瓶颈。
  - 投影/构造查询加上合理 `LIMIT`，并使用精确前缀过滤范围。

