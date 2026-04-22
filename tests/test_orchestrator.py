import pytest
from unittest.mock import AsyncMock, MagicMock
from orchestrator.orchestrator import AgentOrchestrator


@pytest.fixture
def orchestrator(tmp_path):
    db_path = f"sqlite:///{tmp_path}/test.db"
    mock_supervisor = AsyncMock()
    mock_supervisor.run = AsyncMock(return_value=("Root cause: MS throttling on sync-worker.", ["query_traces", "delegate_to_agent"]))
    mock_workato = AsyncMock()
    mock_workato.send_teams_alert = AsyncMock(return_value="[Teams alert sent]")
    return AgentOrchestrator(
        supervisor=mock_supervisor,
        workato_tool=mock_workato,
        db_url=db_path,
    )


@pytest.mark.asyncio
async def test_chat_creates_conversation(orchestrator):
    response = await orchestrator.chat(message="Customer Acme has 500 errors")
    assert response.conversation_id is not None
    assert len(response.response) > 0


@pytest.mark.asyncio
async def test_chat_continues_existing_conversation(orchestrator):
    first = await orchestrator.chat(message="Check tenant Acme")
    second = await orchestrator.chat(
        message="Can you also check tenant Beta?",
        conversation_id=first.conversation_id,
    )
    assert second.conversation_id == first.conversation_id


@pytest.mark.asyncio
async def test_chat_unknown_conversation_id_raises(orchestrator):
    with pytest.raises(ValueError, match="Conversation not found"):
        await orchestrator.chat(
            message="Follow up",
            conversation_id="nonexistent-id-xyz",
        )


@pytest.mark.asyncio
async def test_get_messages_returns_history(orchestrator):
    response = await orchestrator.chat(message="Check errors for tenant X")
    messages = orchestrator.get_messages(response.conversation_id)
    assert len(messages) >= 2
    assert messages[0].role == "user"
    assert messages[-1].role == "assistant"


@pytest.mark.asyncio
async def test_tools_used_included_in_response(orchestrator):
    response = await orchestrator.chat(message="Investigate")
    assert "query_traces" in response.tools_used


@pytest.mark.asyncio
async def test_chat_prepends_case_id_to_stored_message(orchestrator):
    response = await orchestrator.chat(
        message="Customer cannot log in",
        case_id="SF-99999",
    )
    messages = orchestrator.get_messages(response.conversation_id)
    user_message = next(m for m in messages if m.role == "user")
    assert "SF-99999" in user_message.content
    assert "[Salesforce case_id: SF-99999]" in user_message.content


@pytest.mark.asyncio
async def test_chat_without_case_id_no_prefix(orchestrator):
    response = await orchestrator.chat(message="Check tenant Acme")
    messages = orchestrator.get_messages(response.conversation_id)
    user_message = next(m for m in messages if m.role == "user")
    assert "[Salesforce case_id:" not in user_message.content
    assert user_message.content == "Check tenant Acme"


@pytest.mark.asyncio
async def test_chat_sends_teams_alert_on_platform_wide_incident(tmp_path):
    smoke_json = (
        '{"alert_type": "platform_wide_incident", '
        '"pattern": "MS throttling — sync-worker", '
        '"affected_tenant_count": 14, '
        '"affected_tenant_ids": ["tenant-a", "tenant-b"], '
        '"earliest_occurrence_utc": "2026-04-22T09:14:00Z", '
        '"pattern_confidence": "high", '
        '"recommended_priority": "P1"}'
    )
    mock_supervisor = AsyncMock()
    mock_supervisor.run = AsyncMock(return_value=(f"Platform incident confirmed. <smoke_alert>{smoke_json}</smoke_alert>", []))
    mock_workato = AsyncMock()
    mock_workato.send_teams_alert = AsyncMock(return_value="[Teams alert sent]")
    orch = AgentOrchestrator(
        supervisor=mock_supervisor,
        workato_tool=mock_workato,
        db_url=f"sqlite:///{tmp_path}/test.db",
    )
    await orch.chat(message="Check tenant X", case_id="SF-99")
    mock_workato.send_teams_alert.assert_called_once()
    call_kwargs = mock_workato.send_teams_alert.call_args.kwargs
    assert call_kwargs["case_id"] == "SF-99"
    assert call_kwargs["affected_tenant_count"] == 14
    assert call_kwargs["pattern_confidence"] == "high"
    assert "/api/conversations/" in call_kwargs["conversation_url"]


@pytest.mark.asyncio
async def test_chat_does_not_send_teams_alert_for_isolated_incident(tmp_path):
    mock_supervisor = AsyncMock()
    mock_supervisor.run = AsyncMock(return_value=("Isolated issue found. No platform-wide incident.", []))
    mock_workato = AsyncMock()
    mock_workato.send_teams_alert = AsyncMock(return_value="ok")
    orch = AgentOrchestrator(
        supervisor=mock_supervisor,
        workato_tool=mock_workato,
        db_url=f"sqlite:///{tmp_path}/test.db",
    )
    await orch.chat(message="Check tenant X")
    mock_workato.send_teams_alert.assert_not_called()
