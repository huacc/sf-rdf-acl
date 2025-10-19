转换（Converter）
=================

概览
----

本模块提供两类“结果转换”能力：

- 图数据格式化（`GraphFormatter`）：将 CONSTRUCT 结果的 Turtle 文本转换为 `turtle`、`json-ld`、`simplified-json` 等输出。
- 绑定结果映射（`ResultMapper`）：将 Fuseki 返回的 `results.bindings` 规范化为平台统一结构，内置常见 XSD 类型转换。


GraphFormatter
--------------

用途
~~~~

- 将 Turtle 文本转换为不同目标格式：
  - `"turtle"`：原样透传
  - `"json-ld"`：使用 rdflib 序列化，支持传入自定义 `@context`
  - `"simplified-json"`：便于前端可视化的简化结构（`nodes/edges/stats`）

公共方法
~~~~~~~~

- `format_graph(turtle_data, *, format_type="turtle", context=None) -> str | dict`
  - 参数：
    - `turtle_data` Turtle 格式字符串
    - `format_type` 取值 `"turtle" | "json-ld" | "simplified-json"`
    - `context` 当 `format_type="json-ld"` 时可选的 `@context` 映射
  - 返回：按目标类型返回 `str` 或 `dict`

- `to_turtle(graph_ttl) -> str`
  - 参数：`graph_ttl` Turtle 字符串
  - 返回：原样返回（历史兼容）

使用示例
~~~~~~~~

.. code-block:: python

   from sf_rdf_acl.connection.client import FusekiClient
   from sf_rdf_acl.converter.graph_formatter import GraphFormatter

   client = FusekiClient(endpoint="http://127.0.0.1:3030", dataset="acl")
   formatter = GraphFormatter()

   data = await client.construct("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o } LIMIT 50")
   turtle = data["turtle"]

   # 转为 JSON-LD
   jsonld = formatter.format_graph(turtle, format_type="json-ld", context={
       "sf": "http://semanticforge.ai/ontologies/core#"
   })

   # 转为简化 JSON
   simple = formatter.format_graph(turtle, format_type="simplified-json")
   print(simple["stats"])  # {"node_count": ..., "edge_count": ...}


ResultMapper
------------

用途
~~~~

- 将 `head.vars` 与 `results.bindings` 转换为统一结构，自动处理常见 XSD 数据类型：
  - 整数类（`xsd:int`/`integer` 等）→ `int`
  - 浮点/小数（`xsd:decimal`/`double`/`float`）→ `float`
  - 布尔（`xsd:boolean`）→ `bool`
  - 日期时间（`xsd:dateTime`）→ 规范化 ISO 字符串

公共方法
~~~~~~~~

- `map_bindings(vars: list[str], bindings: list[dict]) -> list[dict]`
  - 参数：
    - `vars` 变量名列表，例如 `["s", "label"]`
    - `bindings` Fuseki 的 `results.bindings`
  - 返回：行列表，每行形如：
    `{"s": {"value": "...", "raw": "...", "type": "uri"}, "label": {"value": "示例", "raw": "示例", "type": "literal", "lang": "zh"}}`

示例
~~~~

.. code-block:: python

   from sf_rdf_acl.converter.result_mapper import ResultMapper

   fuseki_raw = {
       "head": {"vars": ["s", "label", "count"]},
       "results": {
           "bindings": [
               {
                   "s": {"type": "uri", "value": "http://ex/e/1"},
                   "label": {"type": "literal", "value": "示例", "xml:lang": "zh"},
                   "count": {"type": "literal", "datatype": "http://www.w3.org/2001/XMLSchema#integer", "value": "42"}
               }
           ]
       }
   }

   rows = ResultMapper().map_bindings(fuseki_raw["head"]["vars"], fuseki_raw["results"]["bindings"])
   # rows[0]["count"]["value"] == 42 (int)


自动文档（参考）
----------------

.. automodule:: sf_rdf_acl.converter.graph_formatter
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: sf_rdf_acl.converter.result_mapper
   :members:
   :undoc-members:
   :show-inheritance:

