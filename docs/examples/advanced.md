# 进阶用法

## 聚合查询（COUNT + GROUP BY）
```python
from sf_rdf_acl import SPARQLQueryBuilder
from sf_rdf_acl.query.dsl import QueryDSL, Aggregation, GroupBy

builder = SPARQLQueryBuilder()
dsl = QueryDSL(
    type="entity",
    aggregations=[Aggregation(function="COUNT", variable="?s", alias="?count")],
    group_by=GroupBy(variables=["?type"]),
)
sparql = builder.build_select(dsl)
print(sparql)
```

## 条件清理（Dry-Run + 执行）
详见示例脚本 `examples/conditional_clear_example.py`，支持 dry-run 评估与阈值保护。

## 批处理写入（模板驱动）
详见示例脚本 `examples/batch_operations_example.py`，支持批次提交 + 单条重试策略。

