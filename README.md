# sf-rdf-acl (RDF Anti-Corruption Layer)

`sf-rdf-acl` 是 SemanticForge 平台的 RDF 防腐层库，为上层 API/算法/业务服务提供统一的 Fuseki 访问、查询构建、数据写入、命名图管理与 RDF* 溯源能力。

## 仓库概览
- `src/sf_rdf_acl/`：核心库代码（客户端、查询 DSL、事务、图工具、溯源等）。
- `tests/`：单元测试，覆盖主要功能路径。
- `doc/design/`：设计背景与架构文档。
- `doc/usage/API参考.md`：对外功能/函数说明与输入输出示例。
- `examples/`：可直接运行的示例脚本与配置。

## 公共接口
完整的函数与类说明请查看 **[API 参考文档](doc/usage/API参考.md)**，覆盖下列核心能力：
- `FusekiClient` / `RDFClient` 协议
- `QueryDSL` & `SPARQLQueryBuilder`
- `TransactionManager` / `UpsertPlanner`
- `NamedGraphManager`
- `GraphProjectionBuilder`
- `ResultMapper`、`GraphFormatter`
- `ProvenanceService`

## 示例快速开始
1. 创建虚拟环境并安装依赖：
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -U pip
   .\.venv\Scripts\pip install -r examples\requirements.txt
   ```
2. 运行任意示例脚本（均位于 `examples/`）：
   ```powershell
   .\.venv\Scripts\python.exe examples\run_query.py
   .\.venv\Scripts\python.exe examples\run_upsert.py
   .\.venv\Scripts\python.exe examples\manage_graphs.py
   .\.venv\Scripts\python.exe examples\project_graph.py
   .\.venv\Scripts\python.exe examples\write_provenance.py
   ```
   示例使用 `examples/config/demo.yaml` 与 `DemoFusekiClient` 演示调用流程，方便离线体验；替换为真实 Fuseki 客户端即可接入生产环境。

## 开发与测试
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\pip install -e . -e ../sf-common
.\.venv\Scripts\pip install pytest pytest-cov pytest-asyncio
.\.venv\Scripts\python.exe -m pytest -q
```

- 默认配置位于 `projects/sf-common/config/`，可通过 `ConfigManager.load(override_path=...)` 加载额外 YAML。
- 详细设计请参考 `doc/design/RDF防腐层深化设计.md`。

## 变更记录
- 2025-10-17：更新定位为库模式；补充公共接口文档与示例脚本。
