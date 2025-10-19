连接（Connection）
==================

概览
----

本模块封装了与 Jena Fuseki/RDF HTTP 接口的交互逻辑，提供统一的客户端协议
`RDFClient` 以及默认实现 `FusekiClient`，支持常用的 SPARQL 操作：

- SELECT 查询（`select`）
- CONSTRUCT 查询（`construct`）
- UPDATE 更新（`update`）
- 健康检查（`health`）

同时内置了请求超时、指数退避重试、熔断器、指标上报与 trace id 透传能力。


接口一览
--------

RDFClient（协议）
~~~~~~~~~~~~~~~~~

- 方法 `select(query, *, timeout=30, trace_id=None) -> dict`
  - 用途：执行 SPARQL SELECT 查询，返回 `vars/bindings/stats` 字段。
  - 参数：
    - `query` 完整 SELECT 语句字符串
    - `timeout` 可选超时（秒），None 使用默认
    - `trace_id` 可选链路 ID
  - 返回：`{"vars": [...], "bindings": [...], "stats": {"status": 200, "durationMs": 12.3}}`

- 方法 `construct(query, *, timeout=30, trace_id=None) -> dict`
  - 用途：执行 SPARQL CONSTRUCT 查询，返回 Turtle 文本。
  - 返回：`{"turtle": "...turtle...", "stats": {"status": 200, "durationMs": 8.6}}`

- 方法 `update(update, *, timeout=30, trace_id=None) -> dict`
  - 用途：执行 SPARQL UPDATE（INSERT/DELETE/CREATE/CLEAR 等）。
  - 返回：`{"status": 200, "durationMs": 5.4}`

- 方法 `health() -> dict`
  - 用途：快速健康检查（不发起重负载请求）。
  - 返回：`{"ok": true, "backend": "fuseki", "dataset": "..."}`


FusekiClient（实现）
~~~~~~~~~~~~~~~~~~~~

构造函数
^^^^^^^^

`FusekiClient(endpoint, dataset, *, auth=None, trace_header="X-Trace-Id", default_timeout=30, max_timeout=120, retry_policy=None, circuit_breaker=None)`

- 用途：创建与 Fuseki 的 HTTP 客户端，所有请求通过 POST 完成。
- 参数：
  - `endpoint` Fuseki 服务地址，例如 `"http://127.0.0.1:3030"`
  - `dataset` 目标数据集名称，例如 `"acl"`
  - `auth` 可选 BasicAuth 凭据 `(username, password)`
  - `trace_header` 用于透传 trace id 的请求头名称
  - `default_timeout` 默认超时秒数
  - `max_timeout` 超时上限秒数
  - `retry_policy` 可选重试策略字典：
    - `max_attempts` 最大重试次数（默认 3）
    - `backoff_seconds` 首次退避（默认 0.5）
    - `backoff_multiplier` 指数乘子（默认 2.0）
    - `jitter_seconds` 抖动秒数（默认 0.1）
    - `retryable_status_codes` 自定义可重试状态码集合
  - `circuit_breaker` 熔断配置字典：
    - `failureThreshold` 连续失败阈值（默认 5）
    - `recoveryTimeout` 熔断休眠时长（秒，默认 30）
    - `recordTimeoutOnly` 是否仅统计超时为失败

公共方法
^^^^^^^^

- `select(query, *, timeout=30, trace_id=None) -> dict`
- `construct(query, *, timeout=30, trace_id=None) -> dict`
- `update(update, *, timeout=30, trace_id=None) -> dict`
- `health() -> dict`

错误与异常
^^^^^^^^^^

- 当 HTTP 状态码异常或网络错误，抛出 `common.exceptions.ExternalServiceError`：
  - 可能的 `ErrorCode`：`BAD_REQUEST`/`NOT_FOUND`/`UNAUTHENTICATED`/`FORBIDDEN`/
    `FUSEKI_QUERY_ERROR`/`FUSEKI_CONNECT_ERROR`/`FUSEKI_CIRCUIT_OPEN` 等。


使用示例
--------

基础查询
~~~~~~~~

.. code-block:: python

   from sf_rdf_acl.connection.client import FusekiClient

   client = FusekiClient(
       endpoint="http://127.0.0.1:3030",
       dataset="acl",
       auth=("user", "pass"),
   )

   # SELECT
   res = await client.select("SELECT * WHERE { ?s ?p ?o } LIMIT 10", trace_id="t-1")
   print(res["vars"], len(res["bindings"]))

   # CONSTRUCT
   g = await client.construct("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o } LIMIT 100")
   print(g["turtle"][:200])

   # UPDATE
   await client.update("CREATE GRAPH <http://example.org/g/demo>")

   # 健康检查
   await client.health()


自动文档（参考）
----------------

.. automodule:: sf_rdf_acl.connection.client
   :members:
   :undoc-members:
   :show-inheritance:

