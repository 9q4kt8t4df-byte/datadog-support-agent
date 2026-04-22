from __future__ import annotations
import anthropic
import config as cfg


class BaseAgent:
    """
    Base agent class. Runs a Claude tool-use loop until the model returns end_turn.
    Subclasses receive tool instances via __init__ and do not need to override run().
    """

    def __init__(self, agent_id: str, config: dict, tools: list) -> None:
        self.agent_id = agent_id
        self.config = config
        self.client = anthropic.AsyncAnthropic(api_key=cfg.ANTHROPIC_API_KEY)
        self.tool_map: dict = {}

        all_tool_defs = []
        for tool in tools:
            for tool_def in tool.as_tools():
                all_tool_defs.append(tool_def)
                self.tool_map[tool_def["name"]] = tool

        self.tool_definitions = all_tool_defs

    async def run(self, messages: list) -> tuple[str, list[str]]:
        """Run the tool-use loop. Returns (response_text, tools_used)."""
        tools_used: list[str] = []
        current_messages = list(messages)

        while True:
            kwargs = dict(
                model=self.config["model"],
                max_tokens=self.config["max_tokens"],
                system=self.config["system_prompt"],
                messages=current_messages,
                temperature=self.config.get("temperature", 0.3),
            )
            if self.tool_definitions:
                kwargs["tools"] = self.tool_definitions
            response = await self.client.messages.create(**kwargs)

            if response.stop_reason == "end_turn":
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text, tools_used
                return "", tools_used

            elif response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        tools_used.append(block.name)
                        if block.name in self.tool_map:
                            result = await self.tool_map[block.name].call(
                                block.name, block.input
                            )
                        else:
                            result = f"Tool not found: {block.name}"
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result),
                        })

                if tool_results:
                    current_messages = current_messages + [
                        {"role": "assistant", "content": response.content},
                        {"role": "user", "content": tool_results},
                    ]
                else:
                    return "", tools_used
            else:
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text, tools_used
                return f"[Agent stopped: {response.stop_reason}]", tools_used
