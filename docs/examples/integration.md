# 系统集成

本节给出与平台其他组件集成时的注意事项与示例。

## 与配置中心（sf-common）
- 使用 `common.config.ConfigManager.load()` 读取默认配置，无需手工拼接端点与鉴权。
- 测试或本地可以通过 `override_path` 指向自定义 yaml（例如 `examples/config/demo.yaml`）。

## 与可观测性
- 本库内置指标上报钩子（`common.observability.metrics`），集成 Prometheus 时可直接采集。

## 与 API 服务
- 作为后端服务的内部 SDK 使用，建议封装仓储层并统一注入 `trace_id` 与 `actor`。

