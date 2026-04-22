from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    case_id: Optional[str] = None
    conversation_id: Optional[str] = None


class SmokeAlert(BaseModel):
    alert_type: str
    pattern: str
    affected_tenant_count: int
    affected_tenant_ids: list[str]
    earliest_occurrence_utc: str
    pattern_confidence: str
    recommended_priority: str


class ChatResponse(BaseModel):
    conversation_id: str
    response: str
    tools_used: list[str]
    smoke_alert: Optional[SmokeAlert] = None


class MessageRecord(BaseModel):
    role: str
    content: str
    created_at: str
