# RDF ACL 端到端验证报告（2025-10-18 17:06）

## 环境
- 配置来源：`projects/sf-common/config/default.yaml`（Fuseki `http://192.168.0.119:3030`，数据集 `semantic_forge_test`）
- 虚拟环境：`projects/sf-rdf-acl/.venv`

## Pytest 套件
- 执行命令：`.venv\Scripts\python.exe -m pytest`
- 结果：3 项通过（提示：pydantic 泛型迁移告警；`datetime.utcnow()` 在快照辅助方法中已被标记为未来弃用）
- 覆盖范围：
  - `test_upsert_and_projection_roundtrip`：调用 TransactionManager 写入真实 Fuseki，并通过 GraphProjectionBuilder 校验投影结果（命名图示例 `urn:sf:e2e:{uuid}:dev`）。
  - `test_snapshot_and_conditional_clear`：对命名图执行 snapshot、conditional_clear，并再次查询确认数据被删除。
  - `test_provenance_annotation`：使用 ProvenanceService 写入 RDF* 溯源语句，并通过 CONSTRUCT 查询验证写入内容。

## 示例脚本
- `run_query.py`：针对 `urn:sf:demo:v1:dev` 生成 SPARQL；目前示例数据为空，返回结果集为空。
- `run_upsert.py`：向 `urn:sf:demo:v1:dev` 写入 8 条三元组（事务 ID `3971c854-3e49-427f-8130-f3160c05bac7`，耗时约 7.16 秒）。
- `manage_graphs.py`：创建 demo 命名图，dry-run 条件清理命中 2 条 `sf:status` 三元组，并生成快照 `snapshot-20251018090554`。
- `project_graph.py`：投影结果包含 2 个节点与 1 条 `sf:relatesTo` 边。
- `write_provenance.py`：写入 6 条 RDF* 语句（generatedAtTime、evidence、confidence、wasDerivedFrom、workflowId、approved）。

## 结论与观察
- 实际 Fuseki 服务对 SELECT / CONSTRUCT / UPDATE 请求均响应该预期。
- 示例查询未命中数据，若需演示可考虑预置 demo 数据。
- `NamedGraphManager.snapshot` 仍使用 `datetime.utcnow()`，后续建议改为 `datetime.now(datetime.UTC)` 以消除弃用告警。

