from __future__ import annotations
import config as cfg
from agents.base import BaseAgent
from tools.datadog_tool import DatadogTool
from tools.knowledge_tool import KnowledgeTool


class InvestigatorAgent(BaseAgent):
    def __init__(self, datadog_tool: DatadogTool, knowledge_tool: KnowledgeTool) -> None:
        super().__init__(
            agent_id="datadog-investigator",
            config=cfg.AGENTS["datadog-investigator"],
            tools=[datadog_tool, knowledge_tool],
        )
