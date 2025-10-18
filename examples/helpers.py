"""示例脚本复用的工具：加载演示配置与简易 FusekiClient。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from common.config import ConfigManager
from sf_rdf_acl import FusekiClient


def load_demo_config() -> None:
    """加载 examples/config/demo.yaml，供示例脚本直接使用。"""

    config_path = Path(__file__).resolve().parent / "config" / "demo.yaml"
    ConfigManager.load(override_path=str(config_path))


@dataclass
class DemoResponse:
    """用于注入示例客户端返回值。"""

    vars: List[str]
    bindings: List[Dict[str, Any]]
    turtle: str = ""
    status: int = 200


class DemoFusekiClient:
    """满足 RDFClient 协议的轻量实现，便于离线演示。"""

    def __init__(
        self,
        *,
        select: Optional[DemoResponse] = None,
        construct: Optional[str] = None,
        update_status: int = 200,
    ) -> None:
        self._select = select or DemoResponse(
            vars=["s", "p", "o"],
            bindings=[],
            turtle="",
            status=200,
        )
        self._construct = construct if construct is not None else ""
        self._update_status = update_status
        self.performed_updates: list[str] = []

    async def select(self, query: str, *, timeout: int | None = 30, trace_id: str | None = None) -> dict[str, Any]:
        print("[DemoFusekiClient] SELECT", query.replace("\n", " "))
        return {
            "vars": list(self._select.vars),
            "bindings": list(self._select.bindings),
            "stats": {"status": self._select.status, "durationMs": 1.0},
        }

    async def construct(self, query: str, *, timeout: int | None = 30, trace_id: str | None = None) -> dict[str, Any]:
        print("[DemoFusekiClient] CONSTRUCT", query.replace("\n", " "))
        return {
            "turtle": self._construct or "",
            "stats": {"status": 200, "durationMs": 1.0},
        }

    async def update(self, update: str, *, timeout: int | None = 30, trace_id: str | None = None) -> dict[str, Any]:
        print("[DemoFusekiClient] UPDATE", update.replace("\n", " "))
        self.performed_updates.append(update)
        return {"status": self._update_status, "durationMs": 1.0}

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "backend": "demo", "dataset": "sf_demo"}

def build_fuseki_client() -> FusekiClient:
    """Create a FusekiClient wired to the loaded configuration."""

    manager = ConfigManager.current()
    rdf_cfg = manager.rdf
    security_cfg = manager.security
    auth = None
    if getattr(rdf_cfg, "auth", None) and rdf_cfg.auth.username and rdf_cfg.auth.password:
        auth = (rdf_cfg.auth.username, rdf_cfg.auth.password)

    retry_policy = (
        rdf_cfg.retries.model_dump()
        if hasattr(rdf_cfg.retries, "model_dump")
        else dict(rdf_cfg.retries)
    )
    circuit_breaker = (
        rdf_cfg.circuit_breaker.model_dump(by_alias=True)
        if hasattr(rdf_cfg.circuit_breaker, "model_dump")
        else dict(rdf_cfg.circuit_breaker)
    )

    return FusekiClient(
        endpoint=str(rdf_cfg.endpoint),
        dataset=rdf_cfg.dataset,
        auth=auth,
        trace_header=security_cfg.trace_header,
        default_timeout=rdf_cfg.timeout.default,
        max_timeout=rdf_cfg.timeout.max,
        retry_policy=retry_policy,
        circuit_breaker=circuit_breaker,
    )

