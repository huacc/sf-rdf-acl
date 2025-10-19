# sf-rdf-acl 测试报告（修复版）

时间: '+(Get-Date -Format 'yyyy-MM-dd HH:mm')+'

## 修复概览
- 修复 `NamedGraphManager.conditional_clear` 过滤器 `{predicate: {type: uri, value: "<...>"}}` 解析为字典文本导致的 SPARQL 语法错误（Jena 报 Parse error）。
  - 变更：`_condition_from_filters` 支持字典形式的 subject/predicate，并统一格式化为 IRI。
- 修复 `InMemoryFusekiClient` 在 `COPY GRAPH` 分支对 `@dataclass(slots=True)` 使用 `__dict__` 导致异常。
  - 变更：显式逐字段复制 `TripleRecord`。
- 将 `examples/end_to_end_scenario.py` 切换为真实 Fuseki 客户端并使用 CONSTRUCT 导出 Turtle，移除导致 SPARQL* 冲突的额外时间元数据键值。
- 重写 `examples/conditional_clear_example.py`，在无 stdin 的自动化环境中跳过交互而不报错。

## 端到端执行
- Fuseki 可达：`http://192.168.0.119:3030`（数据集 `semantic_forge_test`）
- 示例脚本（全部成功，均对 Fuseki 进行真实读写或只读查询）
  - run_upsert.py → 写入 8 条三元组；日志：examples/run_upsert.log
  - run_query.py → 返回与写入一致的记录；日志：examples/run_query.log
  - project_graph.py → GraphJSON/edgelist 投影；日志：examples/project_graph.log
  - write_provenance.py → RDF* 溯源写入；日志：examples/write_provenance.log
  - aggregation_example.py → COUNT/GROUP BY 聚合；日志：examples/aggregation_example.log
  - batch_operations_example.py → 模板批处理（dry-run 统计）；日志：examples/batch_operations_example.log
  - manage_graphs.py → create/dry-run 预估/snapshot 均成功；日志：examples/manage_graphs.log
  - conditional_clear_example.py → dry-run 成功，非交互环境跳过执行；日志：examples/conditional_clear_example.log
  - end_to_end_scenario.py → 真实 Fuseki 端到端（创建、写入、溯源、投影、CONSTRUCT 导出、快照）；日志：examples/end_to_end_scenario.log

- PyTest 测试（78/78 通过）
  - e2e 用例 3 项：真实读写 Fuseki（见 pytest/e2e_summary.txt）
  - 会话日志：pytest/session_rerun.log；JUnit：pytest/junit.xml

## 覆盖率
- 总体：81% 行覆盖（coverage.txt）
- 关键模块：connection/client.py 95%，transaction/upsert.py 94%，graph/named_graph.py 59%，query/builder.py 75%

## 关键 API 使用与验证（节选）
- `FusekiClient.select/construct/update`：用于 SELECT/CONSTRUCT/UPDATE；所有示例与 e2e 用例均返回期望结构
- `TransactionManager.upsert`：生成并执行 UPSERT；返回 `applied` 与无冲突
- `NamedGraphManager.create/snapshot/conditional_clear`：命名图管理/快照/条件清理；e2e 与示例均成功
- `GraphProjectionBuilder.project`：投影出节点/边与统计信息
- `ProvenanceService.annotate`：写入 RDF* 片段（包含 evidence/confidence/source/扩展键）

## 产出工件
- 报告（本文件）与先前报告：doc/reports
- 示例日志：doc/reports/examples/*.log
- PyTest：doc/reports/pytest/
- 覆盖率：doc/reports/coverage.* 与 coverage_html/

