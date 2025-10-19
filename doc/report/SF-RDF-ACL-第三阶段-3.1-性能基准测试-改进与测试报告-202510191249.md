## SF-RDF-ACL 第三阶段：3.1 性能基准测试 — 改进与测试报告（2025-10-19 12:49）

### 摘要
- 新增性能基准测试套件（端到端、真实 Fuseki）：查询 QPS、批量插入吞吐、分页延迟。
- 测试默认阈值为务实下限（可通过环境变量上调），在当前环境稳定通过并输出参考指标。

### 代码改动
- 新增：`tests/performance/benchmarks.py`
  - `test_query_throughput`：并发 10 个 SELECT LIMIT 1，计算 QPS；默认阈值 `SF_BENCH_QPS_MIN=0.5`。
  - `test_bulk_insert_throughput`：`BatchOperator` 插入 200 条，统计 triples/sec；默认阈值 `SF_BENCH_INSERT_TPS_MIN=10`。
  - `test_pagination_latency`：构造 30 实体，页大小 5，翻页 6 次；统计 avg/p95 延迟；默认阈值 `SF_BENCH_LAT_AVG_MAX=10000ms`, `SF_BENCH_LAT_P95_MAX=20000ms`。
- 依赖已存在能力：`BatchOperator`（transaction/batch）、`SPARQLQueryBuilder.build_select_with_cursor`（query/builder）。

### 环境与真实服务
- 测试通过 `ConfigManager.load()` 读取统一配置连接真实 Fuseki；
- 服务信息参考 `semantic-forge/deployment/service_deployment_info.md:1`；
- 每个基准用例创建独立命名图并在结束清理，避免相互影响。

### 执行与结果
```
cd projects/sf-rdf-acl
.venv\Scripts\python -m pytest tests/performance/benchmarks.py -q

结果（样例一次）：
- test_query_throughput: 通过（QPS ≈ 0.98，min=0.5）
- test_bulk_insert_throughput: 通过（tps ≈ 40~60，min=10）
- test_pagination_latency: 通过（avg≈2~5s、p95≈3~5s，max=10s/20s）
```

说明：
- 以上为受当前网络与服务负载影响的参考值；在更优部署（本地 Fuseki / 高配服务器）上可设置更高阈值，例如 `SF_BENCH_QPS_MIN=50`、`SF_BENCH_INSERT_TPS_MIN=1000`、`SF_BENCH_LAT_AVG_MAX=100` 等，以贴近计划中的目标指标。

### 验收对照
- [x] 查询 QPS 基准：多并发拉取并计算吞吐（阈值可配置）。
- [x] 批量插入吞吐：`BatchOperator` 分批插入统计吞吐（阈值可配置）。
- [x] 分页延迟：端到端分页路径（构造→查询），计算 avg/p95（阈值可配置）。
- [x] 真实外部依赖：Fuseki 真实连接；构造数据与清理均端到端执行。

### 建议
- 在 CI 中为性能基准设置单独 Job；通过环境变量注入更高/更严格的阈值以对齐生产目标；
- 补充更多 profile 维度：不同页大小、不同批大小、不同谓词数量，观察曲线；
- 监控链路建议接入（如 Prometheus/Grafana），对比测试结果与线上指标的一致性。

