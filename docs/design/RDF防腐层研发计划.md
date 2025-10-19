# RDF 防腐层（ACL）研发计划（详版 P0-P1，类/函数级）

参考与约束

- 设计基线：docs/design/分阶段设计/一层服务/RDF防腐层深化设计/RDF防腐层深化设计.md
- 统一需求：docs/design/分阶段设计/一层服务/OMM与RDF防腐层统一需求说明.md
- 部署依赖：semantic-forge/deployment/service_deployment_info.md（E2E 真实依赖以此为准）
- 全局约束（刚性）：
  - 全局一致性：任何改动前执行“上下文与依赖扫描 + 影响清单 + 验证计划”，禁止“只改一处”。
  - 配置单一来源（SSOT）：仅通过 ConfigManager 读取配置，禁止多入口/散落默认值/硬编码。
  - E2E 真流量门禁：提供一键脚本，真实依赖与真实数据，E2E 全量通过才可推进（严禁 mock）。
  - 缺陷修复协议：改前影响分析；改后“变更点 UT + 全量回归 + E2E”，并更新变更说明与回滚预案。
  - 错误码分段（全局统一）：400x 客户端、401x 鉴权、403x 权限、404x 资源；420x 业务冲突/幂等；421x 契约不符；430x 外部依赖；500x 内部错误；510x 后端存储（Fuseki/PG）。

里程碑

- M1 接口协议+表结构
- M2 工程与类骨架
- M3 查询最小闭环
- M4 写入/图管理闭环
- M5 溯源/投影/算法最小版
- M6 异常治理与可观测
- M7 E2E 全绿
- M8 架构评审与发布准备

阶段化计划（每阶段含：目标/输入/上下文与依赖/主要任务/受影响组件/产出物/检查DoD/回退与注意事项/下一步触发）

阶段0：范围基线与上下文扫描

- 目标：统一 ACL 职责边界与上下文依赖，识别风险与优先级，冻结术语与命名规范。
- 输入：两份设计文档、当前仓库、deployment/service_deployment_info.md。
- 上下文与依赖：OMM（TBox/制品只读）；Fuseki（RDF/SPARQL）；Postgres（登记/审计/算法运行日志）；脚本与配置入口。
- 主要任务：
  1) 枚举现有/计划中的接口路由与契约点；
  2) `rg` 扫描配置读取点/默认值/硬编码，列“多入口/散落默认值”风险；
  3) 收敛命名：命名图、环境、数据集、错误码前缀、表命名；
  4) 形成依赖拓扑（API→Service→Infra→外部）；
  5) 列出高风险与整改序。
- 受影响组件：docs/*、scripts/*、config/*、所有 API/Service/Infra 目录。
- 产出物：
  - docs/review/rdf-acl_phase0_context_scan.md（依赖拓扑、术语/命名、风险与整改清单）
  - docs/review/rdf-acl_impact_register.csv（影响登记表）
- 检查DoD：风险清单确认；无高阻碍项；命名规范冻结。
- 回退与注意：不改代码，仅产出评审材料。
- 下一步触发：批准后进入阶段1。

阶段1：接口协议 V1 与错误码规范（先协议后实现）

- 目标：冻结对外契约与错误码映射，作为实现与测试基准。
- 输入：阶段0 扫描报告；设计文档。
- 上下文与依赖：OMM 只读接口约束；统一错误码与 Envelope；分页/超时/幂等键策略；traceId 贯穿。
- 主要任务：
  1) 定义路由：
     - /api/v1/rdf/query（POST：DSL/SELECT）
     - /api/v1/rdf/construct（POST：DSL/CONSTRUCT）
     - /api/v1/rdf/sparql（POST：原生 SPARQL）
     - /api/v1/rdf/graphs（POST create/DELETE clear/POST merge/POST snapshot）
     - /api/v1/rdf/{entities|relations|events}/upsert（POST）
     - /api/v1/rdf/provenance/annotate（POST）
     - /api/v1/graph/algorithms/run（POST）/native/run（POST）
  2) Envelope：{code,message,data,traceId,meta?{version,paging}}；分页（page.size/offset）、timeout、幂等键（s/s+p/custom）。
  3) 错误码表（含可重试标记）与 HTTP Status 映射；
  4) OpenAPI/JSON-Schema + 契约测试用例清单（正/逆/边界）。
- 受影响组件：docs/api/*、tests/contract/*、api/routers/v1/*（仅路由占位可选）。
- 产出物：docs/api/rdf-acl-v1.md、docs/api/rdf-acl-v1.yaml、tests/contract/用例骨架。
- 检查DoD：契约审阅通过；破坏性变更识别规则清晰；错误码与映射冻结。
- 回退与注意：禁止实现代码；仅文档/契约。
- 下一步触发：接口文档签字后进入阶段2。

阶段2：数据库表设计与迁移脚本

- 目标：提供审计/登记/算法运行最小支撑，并具备快照/回溯能力。
- 输入：阶段1 协议；设计文档；命名规范。
- 上下文与依赖：PG 版本；备份/回滚策略；保留周期；写入量与索引策略。
- 主要任务：
  1) 表设计（建议）：
     - named_graph_registry(id, env, graph_iri, dataset, model, version, status, created_at, updated_at)
     - graph_snapshot(id, graph_iri, snapshot_id, snapshot_time, snapshot_type, storage_url, checksum, created_by)
     - rdf_operation_audit(id, op_type, actor, graph_iri, tx_id, request_hash, result_status, latency_ms, error_code, created_at)
     - request_log(id, trace_id, route, method, status_code, duration_ms, client_ip, user_id, params_hash, created_at)
     - provenance_evidence(id, triple_hash, source_uri, evidence_text, confidence, created_at)
     - algo_run_log(id, algo_name, params_json, input_graph, output_graph, run_status, metrics_json, duration_ms, created_at)
  2) 索引：graph_iri、trace_id、tx_id、created_at；
  3) 迁移与回滚脚本；
  4) 数据保留与归档策略草案。
- 受影响组件：docs/design/db/*、migrations/*、scripts/db_migrate.*。
- 产出物：docs/design/db/rdf-acl-ddl.md、migrations/xxxx_init_rdf_acl.sql（含 down）。
- 检查DoD：迁移与回滚在本地/CI 可执行；索引命名规范通过评审。
- 回退与注意：避免破坏性 DDL；提供 down 脚本与快照策略。
- 下一步触发：DB 方案签字后进入阶段3。

阶段3：工程与配置骨架（SSOT）

- 目标：建立统一目录与配置入口，固化脚本基线，避免“多入口/散落配置”。
- 输入：阶段0 扫描报告；命名规范；阶段1/2 产物。
- 上下文与依赖：CI/Lint/Format；部署环境变量映射至配置。
- 主要任务：
  1) 目录：
     - src/infrastructure/rdf/{connection,query,transaction,converter,graph,provenance}/
     - src/api/routers/v1/{rdf,graph}/
     - src/core/services/{query_service.py,write_service.py,graph_service.py,provenance_service.py,graph_ops_service.py}
     - src/config/config_manager.*；config/{default,development,testing,production}.yaml + local.yaml
     - tests/{unit,integration,contract,e2e}/；tests/resources/
     - scripts/{test_all,e2e_run,lint,db_migrate}.(sh|ps1)
  2) ConfigManager（唯一入口）：load()→层级合并；get(section,key,default?)；snapshot()；
  3) LoggerFactory、ErrorCatalog 占位；
  4) 初始化 CI、Lint、Format 基线。
- 受影响组件：上述目录与脚本；.env/.yaml 映射。
- 产出物：目录与配置骨架；示例配置；CI/Lint/Format 基线。
- 检查DoD：仓库内任何代码仅经 ConfigManager 读配置；空测试可运行。
- 回退与注意：不绑定具体实现；禁止散落默认值。
- 下一步触发：骨架通过检查进入阶段4。

阶段4：类与服务骨架（空实现，可编译运行）

- 目标：固化类/函数签名与层间依赖，便于并行实现与测试桩搭建。
- 输入：阶段3 骨架；阶段1 协议。
- 上下文与依赖：依赖指向内向；避免环依赖。
- 主要任务（类/函数签名）：
  1) 连接
     - class ConfigManager: load(), get(section,key,default=None), snapshot()
     - class RDFClient: select(query:str, timeout:int|None=30)->dict; construct(query:str, timeout:int|None=30)->str; update(update:str, timeout:int|None=30)->dict
     - class FusekiClient(RDFClient)
  2) 查询
     - class QueryDSL: Page, Filter, TimeWindow, QueryDSL
     - class SPARQLQueryBuilder: build_select(dsl:QueryDSL)->str; build_construct(dsl:QueryDSL)->str
     - class ResultMapper: map_bindings(rows:list[dict])->list[dict]; cast_xsd(val:str, xsd_type:str)->any
  3) 事务/写入
     - class UpsertPlanner: plan(req:UpsertRequest)->list[str]
     - class TransactionManager: begin()->str; exec_updates(updates:list[str])->dict; commit(tx_id:str)->None; rollback(tx_id:str)->None
  4) 图与算法
     - class NamedGraphManager: create(iri:str), clear(iri:str), merge(src:str,target:str), snapshot(iri:str,opts:dict)->str
     - class GraphProjectionBuilder: project(graph_iri:str, profile:str)->dict|str
     - class GraphAlgoExecutor: run(algo:str, input_graph:str, params:dict)->dict
  5) 溯源
     - class ProvenanceService: annotate(triples:list[tuple], prov:dict)->list[str]
  6) 服务层
     - class QueryService: select(dsl:QueryDSL)->dict; construct(dsl:QueryDSL)->str
     - class WriteService: upsert(req:UpsertRequest)->dict
     - class GraphService: manage_graph(op:str, payload:dict)->dict
     - class GraphOpsService: run_projection(inp:dict)->dict; run_algorithm(inp:dict)->dict
  7) 路由骨架
     - rdf/query.py, rdf/graphs.py, rdf/writes.py, rdf/provenance.py；graph/algorithms.py
- 受影响组件：src/*、tests/unit/*。
- 产出物：空实现代码、类图/职责说明、UT 桩。
- 检查DoD：编译通过；UT 桩可运行；无循环依赖。
- 回退与注意：仅定义签名，不写业务逻辑。
- 下一步触发：进入最小闭环实现。

阶段5：查询最小闭环（SELECT/CONSTRUCT）

- 目标：打通查询路径，支持分页/超时与基础类型映射，形成可验证的主路径。
- 输入：阶段4 骨架；阶段1 协议。
- 上下文与依赖：Fuseki 真实依赖（按 deployment/service_deployment_info.md）。
- 主要任务：
  1) 实现 SPARQLQueryBuilder.build_select/construct（filters/sorts/page/timeWindow）
  2) 实现 RDFClient.select/construct（timeout 与 traceId 透传）
  3) 实现 ResultMapper.map_bindings/cast_xsd（xsd:string|int|decimal|dateTime）
  4) QueryService 接好链路；路由返回 Envelope
  5) 单元/集成/契约测试：正向/逆向/边界
- 受影响组件：infrastructure/rdf/query/*, connection/*, converter/*, core/services/query_service.py, api/routers/v1/rdf/query.py
- 产出物：查询实现代码；UT 覆盖>85%；IT（最小真实依赖）；契约样例通过。
- 检查DoD：小数据 E2E 查询场景跑通。
- 回退与注意：错误码映射（400x/430x/510x）到位；分页上限/超时默认从 SSOT。
- 下一步触发：进入写入闭环。

阶段6：写入与事务闭环（Upsert + Named Graph）

- 目标：实现 Upsert 事务控制与命名图管理，完成写读闭环。
- 输入：阶段4 骨架；阶段1 协议；阶段2 DDL。
- 上下文与依赖：幂等策略（s/s+p/custom）；事务回滚；审计写入 PG。
- 主要任务：
  1) UpsertPlanner.plan 生成 DELETE/INSERT WHERE …
  2) TransactionManager：begin/exec_updates/commit/rollback
  3) NamedGraphManager：create/clear/merge/snapshot
  4) WriteService：响应 stats；冲突映射错误码 4201
  5) 审计：rdf_operation_audit 与 request_log 写入
  6) UT/IT/契约/E2E：写入-查询回读
- 受影响组件：infrastructure/rdf/transaction/*, graph/named_graph.py, core/services/write_service.py, api/routers/v1/rdf/writes.py, graphs.py, migrations/*
- 产出物：写入/图管理实现；测试与审计落库
- 检查DoD：E2E 写入-回读/回滚通过；冲突/异常路径测试通过。
- 回退与注意：失败时确保回滚；命名图命名规范遵循阶段0 冻结。
- 下一步触发：进入溯源/投影/算法。

阶段7：溯源/投影/算法（最小版）

- 目标：补齐最小可用的 Provenance/Projection/Algorithm 能力。
- 输入：阶段4 骨架；阶段1 协议。
- 上下文与依赖：RDF* 片段；投影 profile；networkx 执行器。
- 主要任务：
  1) ProvenanceService.annotate 生成 RDF* 片段并写入
  2) GraphProjectionBuilder.project 实现最小 profile → JSON/表格
  3) GraphAlgoExecutor.run 支持 pagerank/shortest_path/khop（networkx）
  4) GraphOpsService + 路由连通
  5) UT/IT/E2E 覆盖图操作与算法主路径
- 受影响组件：infrastructure/rdf/provenance/*, graph/projection.py, graph/ops.py, core/services/graph_ops_service.py, api/routers/v1/graph/algorithms.py
- 产出物：最小能力代码与测试；示例 E2E 场景
- 检查DoD：E2E 覆盖上述能力主路径。
- 回退与注意：长耗时算法限制/超时从 SSOT。
- 下一步触发：进入治理与可观测。

阶段8：异常治理与可观测性

- 目标：建立稳定性与观测护栏，便于问题定位与自愈。
- 输入：阶段5-7 产物；阶段2 表。
- 上下文与依赖：日志/指标/追踪设施；重试/超时/限流/熔断策略。
- 主要任务：
  1) FusekiClient：重试/超时/熔断钩子；指标埋点（QPS、错误率、P95、后端延迟）
  2) Service 层：错误码映射表；审计入库；traceId 透传
  3) 结构化日志格式与字段规范
  4) 可观测面板清单（文档）
  5) UT/IT 对异常流覆盖
- 受影响组件：connection/client.py, core/services/*, converter/*, scripts/*, docs/review/*
- 产出物：治理钩子与配置、指标与日志规范、观测面板清单
- 检查DoD：异常路径测试覆盖；关键指标可观测。
- 回退与注意：策略全走 SSOT；默认关闭可风险降低。
- 下一步触发：进入 E2E 全量回归。

阶段9：E2E 一键脚本与全量回归

- 目标：以真实依赖/数据的一键脚本跑通所有主干与异常场景。
- 输入：deployment/service_deployment_info.md；阶段5-8 产物。
- 上下文与依赖：Fuseki/PG/其他依赖实际部署；测试数据准备与装载。
- 主要任务：
  1) scripts/e2e_run.(sh|ps1) 按部署信息请求服务；
  2) 准备 tests/e2e/ 场景（查询/写入/图/溯源/算法/异常）；
  3) 产出报告与失败分类；
  4) 必要的数据装载/清理脚本。
- 受影响组件：scripts/e2e_run.*、tests/e2e/*、tests/resources/*
- 产出物：E2E 报告、失败清单与修复建议
- 检查DoD：E2E 全绿为唯一放行条件。
- 回退与注意：不得使用 mock；失败优先修复致命项。
- 下一步触发：进入评审与发布准备。

阶段10：架构评审与发布准备

- 目标：完成架构评审、发布/灰度/回滚脚本与演练。
- 输入：阶段0-9 产物；E2E 报告。
- 上下文与依赖：组织级门禁/流程；变更管理策略。
- 主要任务：
  1) 评审清单：分层边界/依赖、契约/兼容、配置 SSOT 合规、性能/容量、异常治理、数据与备份、回滚预案；
  2) 发布/灰度/回滚脚本与一次演练；
  3) 风险与兜底责任人。
- 受影响组件：docs/review/*、scripts/deploy/*、scripts/rollback/*
- 产出物：评审报告；发布与回滚脚本；演练记录
- 检查DoD：回滚演练通过；高风险有兜底方案。
- 回退与注意：发布窗口与监控在岗确认。
- 下一步触发：进入文档与沉淀。

阶段11：文档与知识沉淀

- 目标：沉淀可复用知识，缩短后续迭代上手成本。
- 输入：阶段 0-10 产物。
- 上下文与依赖：最佳实践与 ADR。
- 主要任务：
  1) README、API 文档、运维与排障指引；
  2) ADR：关键决策记录与权衡；
  3) 测试基线/覆盖率报告；
  4) 常见问题与故障案例复盘。
- 受影响组件：docs/*、tests/baseline/*
- 产出物：文档集与基线报告
- 检查DoD：新人按文档可独立跑通 E2E。
- 回退与注意：持续更新与版本化。

变更影响扫描（每阶段进入前的必做清单）

- 搜索范围：src/*、tests/*、docs/*、config/*、scripts/*
- 关注项：配置读取点、DTO/Schema、接口路由、错误码映射、事务边界、命名图命名规范、审计写入点、脚本入口
- 要求：列出影响列表、验证动作（UT/IT/Contract/E2E 哪些需更新）、回滚方案

附：错误码对照（初稿，可全局统一）

- 2000 成功
- 4001 参数缺失/非法；4011 未认证；4031 无权限；4041 资源不存在
- 4201 幂等键冲突；4202 版本冲突；4211 契约校验失败
- 4301 后端依赖超时；4302 后端依赖返回错误
- 5001 未处理异常；5101 Fuseki 更新失败；5102 Fuseki 查询失败；5103 PG 访问失败
