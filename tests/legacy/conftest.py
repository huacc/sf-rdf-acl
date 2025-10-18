import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure config is loaded from test fixtures to avoid coupling to repo layout
try:
    from common.config import ConfigManager  # type: ignore

    _CFG = Path(__file__).resolve().parent / "fixtures" / "config" / "testing.yaml"
    if _CFG.exists():
        ConfigManager.load(override_path=str(_CFG))
except Exception:
    pass

# 为避免核心包导入 demo 依赖失败，注入最小化的 stub 模块
stub_modules = {
    "semantic_forge": types.ModuleType("semantic_forge"),
    "semantic_forge.backend": types.ModuleType("semantic_forge.backend"),
    "semantic_forge.backend.demo": types.ModuleType("semantic_forge.backend.demo"),
    "semantic_forge.backend.demo.rdfrag_v2": types.ModuleType("semantic_forge.backend.demo.rdfrag_v2"),
    "semantic_forge.backend.demo.rdfrag_v2.src": types.ModuleType("semantic_forge.backend.demo.rdfrag_v2.src"),
    "semantic_forge.backend.demo.rdfrag_v2.src.core": types.ModuleType("semantic_forge.backend.demo.rdfrag_v2.src.core"),
}
for name, module in stub_modules.items():
    sys.modules.setdefault(name, module)

if "prometheus_client" not in sys.modules:
    class _Metric:
        def __call__(self, *args, **kwargs):  # pragma: no cover - simple stub
            return self

        def labels(self, *args, **kwargs):  # pragma: no cover - simple stub
            return self

        def inc(self, *args, **kwargs):  # pragma: no cover - simple stub
            return None

        def observe(self, *args, **kwargs):  # pragma: no cover - simple stub
            return None

        def set(self, *args, **kwargs):  # pragma: no cover - simple stub
            return None

    metric_stub = _Metric()
    prom_stub = types.SimpleNamespace(
        CONTENT_TYPE_LATEST="text/plain; version=0.0.4; charset=utf-8",
        generate_latest=lambda: b"prometheus client stub",
        Counter=lambda *args, **kwargs: metric_stub,
        Gauge=lambda *args, **kwargs: metric_stub,
        Histogram=lambda *args, **kwargs: metric_stub,
        REGISTRY=types.SimpleNamespace(get_sample_value=lambda name, labels: 0.0),
    )
    sys.modules.setdefault("prometheus_client", prom_stub)

config_stub = types.ModuleType("semantic_forge.backend.demo.rdfrag_v2.src.core.config")
config_stub.Config = type("Config", (), {})
config_stub.FusekiConfig = type("FusekiConfig", (), {})
config_stub.LLMConfig = type("LLMConfig", (), {})
config_stub.get_config = lambda *args, **kwargs: None
sys.modules.setdefault(config_stub.__name__, config_stub)

fuseki_stub = types.ModuleType("semantic_forge.backend.demo.rdfrag_v2.src.core.fuseki_connector")
fuseki_stub.FusekiConnector = type("FusekiConnector", (), {})
sys.modules.setdefault(fuseki_stub.__name__, fuseki_stub)

llm_stub = types.ModuleType("semantic_forge.backend.demo.rdfrag_v2.src.core.llm_client")
llm_stub.LLMClient = type("LLMClient", (), {})
sys.modules.setdefault(llm_stub.__name__, llm_stub)

models_stub = types.ModuleType("semantic_forge.backend.demo.rdfrag_v2.src.core.models")
models_stub.Domain = type("Domain", (), {})
sys.modules.setdefault(models_stub.__name__, models_stub)


