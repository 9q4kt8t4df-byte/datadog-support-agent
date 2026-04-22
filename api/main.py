from __future__ import annotations
from fastapi import FastAPI, HTTPException
from api.models import ChatRequest, ChatResponse, MessageRecord
import config as cfg
from orchestrator.orchestrator import AgentOrchestrator
from agents.supervisor import SupervisorAgent
from agents.investigator import InvestigatorAgent
from agents.smoke_detector import SmokeDetectorAgent
from tools.datadog_tool import DatadogTool
from tools.knowledge_tool import KnowledgeTool
from tools.workato_tool import WorkatoTool
from tools.cross_tenant import CrossTenantTool


def build_orchestrator() -> AgentOrchestrator:
    datadog = DatadogTool(
        api_key=cfg.DD_API_KEY,
        app_key=cfg.DD_APP_KEY,
        site=cfg.DD_SITE,
    )
    knowledge = KnowledgeTool()
    workato = WorkatoTool()
    cross_tenant = CrossTenantTool(datadog_tool=datadog)

    investigator = InvestigatorAgent(datadog_tool=datadog, knowledge_tool=knowledge)
    smoke_det = SmokeDetectorAgent(datadog_tool=datadog, cross_tenant_tool=cross_tenant)
    supervisor = SupervisorAgent(
        datadog_tool=datadog,
        knowledge_tool=knowledge,
        workato_tool=workato,
        sub_agents={
            "datadog-investigator": investigator,
            "smoke-detector": smoke_det,
        },
    )
    return AgentOrchestrator(supervisor=supervisor, workato_tool=workato)


def create_app(orchestrator: AgentOrchestrator | None = None) -> FastAPI:
    app = FastAPI(title="Datadog Support Agent", version="1.0.0")
    _orchestrator = orchestrator if orchestrator is not None else build_orchestrator()

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
        try:
            return await _orchestrator.chat(
                message=request.message,
                case_id=request.case_id,
                conversation_id=request.conversation_id,
            )
        except ValueError as e:
            msg = str(e)
            status = 404 if "not found" in msg.lower() else 422
            raise HTTPException(status_code=status, detail=msg)

    @app.get("/api/conversations/{conversation_id}/messages", response_model=list[MessageRecord])
    def get_messages(conversation_id: str):
        if _orchestrator.store.get_conversation(conversation_id) is None:
            raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
        return _orchestrator.get_messages(conversation_id)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
