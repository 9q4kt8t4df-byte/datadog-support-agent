from __future__ import annotations
import json
import re
from typing import Optional
from pydantic import ValidationError
from api.models import ChatResponse, MessageRecord, SmokeAlert
from orchestrator.conversation import ConversationStore
from agents.supervisor import SupervisorAgent
from tools.workato_tool import WorkatoTool
import config as cfg


class AgentOrchestrator:
    def __init__(
        self,
        supervisor: SupervisorAgent,
        workato_tool: WorkatoTool,
        db_url: str = "sqlite:///conversations.db",
    ) -> None:
        self.supervisor = supervisor
        self.workato = workato_tool
        self.store = ConversationStore(db_url=db_url)

    async def chat(
        self,
        message: str,
        case_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> ChatResponse:
        if conversation_id:
            conv = self.store.get_conversation(conversation_id)
            if conv is None:
                raise ValueError(f"Conversation not found: {conversation_id}")
        else:
            conv = self.store.create_conversation()

        full_message = f"[Salesforce case_id: {case_id}]\n\n{message}" if case_id else message
        self.store.add_message(conv.id, role="user", content=full_message)

        history = self._build_history(conv.id)
        response_text, tools_used = await self.supervisor.run(history)

        self.store.add_message(conv.id, role="assistant", content=response_text)

        smoke_alert = self._extract_smoke_alert(response_text)

        if smoke_alert:
            conversation_url = (
                f"{cfg.CHAT_BASE_URL}/api/conversations/{conv.id}/messages"
            )
            await self.workato.send_teams_alert(
                case_id=case_id or "",
                root_cause=smoke_alert.pattern,
                affected_tenant_count=smoke_alert.affected_tenant_count,
                affected_tenant_ids=smoke_alert.affected_tenant_ids,
                earliest_occurrence_utc=smoke_alert.earliest_occurrence_utc,
                pattern_confidence=smoke_alert.pattern_confidence,
                conversation_url=conversation_url,
            )

        return ChatResponse(
            conversation_id=conv.id,
            response=response_text,
            tools_used=tools_used,
            smoke_alert=smoke_alert,
        )

    def get_messages(self, conversation_id: str) -> list:
        messages = self.store.get_messages(conversation_id)
        return [
            MessageRecord(
                role=m.role,
                content=m.content,
                created_at=m.created_at.isoformat(),
            )
            for m in messages
        ]

    def _build_history(self, conversation_id: str) -> list:
        messages = self.store.get_messages(conversation_id)
        return [{"role": m.role, "content": m.content} for m in messages]

    def _extract_smoke_alert(self, response_text: str) -> Optional[SmokeAlert]:
        """Parse smoke alert from <smoke_alert>...</smoke_alert> XML tags in response text."""
        m = re.search(r"<smoke_alert>(.*?)</smoke_alert>", response_text, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(1).strip())
            if data.get("alert_type") == "platform_wide_incident":
                return SmokeAlert(**data)
        except (json.JSONDecodeError, KeyError, TypeError, ValidationError):
            pass
        return None
