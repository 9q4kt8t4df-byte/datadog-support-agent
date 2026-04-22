from __future__ import annotations
import config as cfg
from agents.base import BaseAgent
from tools.datadog_tool import DatadogTool
from tools.knowledge_tool import KnowledgeTool
from tools.workato_tool import WorkatoTool


class DelegateTool:
    """Internal tool that lets the supervisor delegate to a sub-agent."""

    def __init__(self, supervisor: SupervisorAgent) -> None:
        self._supervisor = supervisor

    def as_tools(self) -> list:
        agent_ids = list(self._supervisor.sub_agents.keys())
        return [
            {
                "name": "delegate_to_agent",
                "description": (
                    "Delegate a sub-task to a specialist agent. "
                    f"Available agents: {', '.join(agent_ids)}. "
                    "datadog-investigator: deep trace and log analysis for one tenant. "
                    "smoke-detector: cross-tenant pattern detection."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "enum": agent_ids,
                            "description": "ID of the agent to delegate to",
                        },
                        "task": {
                            "type": "string",
                            "description": "Full task description for the sub-agent, including tenant_id, symptom, and time range",
                        },
                    },
                    "required": ["agent_id", "task"],
                },
            }
        ]

    async def call(self, tool_name: str, tool_input: dict) -> str:
        if tool_name == "delegate_to_agent":
            return await self._supervisor._delegate(tool_input["agent_id"], tool_input["task"])
        return f"Unknown tool: {tool_name}"


class SupervisorAgent(BaseAgent):
    def __init__(
        self,
        datadog_tool: DatadogTool,
        knowledge_tool: KnowledgeTool,
        workato_tool: WorkatoTool,
        sub_agents: dict,
    ) -> None:
        self.sub_agents = sub_agents
        delegate_tool = DelegateTool(supervisor=self)
        super().__init__(
            agent_id="support-supervisor",
            config=cfg.AGENTS["support-supervisor"],
            tools=[datadog_tool, workato_tool, knowledge_tool, delegate_tool],
        )

    async def _delegate(self, agent_id: str, task: str) -> str:
        """Run a sub-agent with a fresh conversation for the given task."""
        if agent_id not in self.sub_agents:
            return f"Delegation failed: agent '{agent_id}' not found. Available: {list(self.sub_agents.keys())}"
        sub_agent = self.sub_agents[agent_id]
        result, _ = await sub_agent.run([{"role": "user", "content": task}])
        return result
