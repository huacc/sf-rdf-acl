# 实际服务验证报告 - 2025-10-17

## 配置更新
- projects/sf-common/config/default.yaml：将 RDF 端点改为 http://192.168.0.119:3030，数据集改为 semantic_forge_test，Postgres 改为 postgresql://postgres:123456@192.168.0.119:5432/semantic_forge，Redis 改为 edis://:123456@192.168.0.119:6379/0，Qdrant HTTP/GRPC 改为指向 192.168.0.119。
- projects/sf-common/config/development.yaml、local.yaml、	esting.yaml、stage9_e2e.yaml：同步数据集和 DSN，全部指向上述远程服务。
- projects/sf-common/src/common/config/settings.py：默认连接目标统一改为 192.168.0.119，并删除遗留的非 ASCII 文档字符串以避免编码异常。
- projects/sf-rdf-acl/tests/fixtures/config/*.yaml：测试夹具改为使用远程服务，pytest 会实际连到外部依赖。
- projects/sf-rdf-acl/examples/config/demo.yaml 与 examples/helpers.py：示例配置改为远程 Fuseki/Postgres，并新增 uild_fuseki_client() 供脚本直接访问真实服务。
- projects/sf-rdf-acl/examples/requirements.txt：修正可编辑路径，pip install -r 可正确解析 sf-common 与 sf-rdf-acl。

## 测试执行
- 命令：D:\coding\OntologyGraph\projects\sf-rdf-acl\.venv\Scripts\python.exe -m pytest -vv
  - 结果：44 通过，0 跳过，0 失败，总耗时 1.12 秒。
  - 警告：Pydantic 迁移提示（GenericModel），以及 	ransaction/audit.py 中 datetime.utcnow() 的弃用警告。

## 192.168.0.119 上的示例运行
- un_upsert.py：
  - 通过 Fuseki 将 .../entity/123 与 .../entity/456 写入图 urn:sf:demo:v1:dev。
  - 最近一次响应：pplied=8，statements=2，durationMs≈6656，	xId=defffc72-d575-4a75-a2eb-4646c57023da。
- un_query.py：
  - 生成的 SPARQL 包含 PREFIX sf:，并筛选 df:type sf:Entity 及 sf:status IN ("active","pending")。
  - 返回 9 条绑定，覆盖 sf:relatesTo 边以及两条实体标签。
- manage_graphs.py：
  - create 确认图已存在（status: created）。
  - conditional_clear 在 dry-run 模式下命中 1 条 <...#status> 三元组；将 IRI 用 <...> 包裹后查询成功。
  - snapshot 生成 snapshot-20251017161623 供后续检查。
- project_graph.py：
  - 输出 GraphJSON，含 2 个节点与 1 条 sf:relatesTo 边（.../entity/123 → .../entity/456）。
  - 统计：
odes=2，edges=1，durationMs≈2122。
- write_provenance.py：
  - 为状态断言写入 6 条 RDF* 溯源语句（generatedAtTime、evidence、confidence、source、workflowId、pproved）。

## 数据校验
- urn:sf:demo:v1:dev 内三元组总数：21（SPARQL COUNT(*)）。
- 已验证关系：<http://example.com/entity/123> sf:relatesTo <http://example.com/entity/456> 已存在于 Fuseki。
- 快照存在：urn:sf:demo:v1:dev:snapshot:20251017161623（由 NamedGraphManager.snapshot 创建）。

## 观察与后续建议
- 所有集成路径现均依赖 192.168.0.119 上的真实服务，请确保该地址对 CI 与开发环境持续可达。
- Pydantic 与 datetime.utcnow() 的警告仍在，如需更严格的日志策略建议后续修复。
- NamedGraphManager 会把未包裹的 HTTP IRI 当作带前缀的名称；提供过滤条件时请使用 <...> 包裹或传入 {"type": "uri", "value": "<...>"} 形式。
