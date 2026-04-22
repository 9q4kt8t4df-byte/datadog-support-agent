from __future__ import annotations
import config as cfg
from agents.base import BaseAgent
from tools.datadog_tool import DatadogTool
from tools.cross_tenant import CrossTenantTool


class SmokeDetectorAgent(BaseAgent):
    def __init__(self, datadog_tool: DatadogTool, cross_tenant_tool: CrossTenantTool) -> None:
        super().__init__(
            agent_id="smoke-detector",
            config=cfg.AGENTS["smoke-detector"],
            tools=[datadog_tool, cross_tenant_tool],
        )
