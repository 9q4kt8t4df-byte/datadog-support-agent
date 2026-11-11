# Datadog Support Agent

A chat service for support engineers. A supervisor agent (Claude, via the Anthropic SDK) investigates a customer issue using Datadog APM traces and logs, checks whether the same error is hitting several tenants, and drafts an escalation. It is a FastAPI app.

## How it works

Three agents are defined in `config.py` (all use `claude-sonnet-4-6`):

| Agent | Tools | Job |
|---|---|---|
| `support-supervisor` | Datadog tools, Workato tools, knowledge tools, `delegate_to_agent` | Takes the chat message, reads the Salesforce case if a case ID is given, delegates to the two sub-agents, and writes the summary |
| `datadog-investigator` | Datadog tools, knowledge tools | Single-tenant analysis: error rate, error spans, one full trace, correlated logs, known issues |
| `smoke-detector` | Datadog tools, `find_pattern_across_tenants` | Normalises an error signature and counts affected tenants |

Tools, by name:

- Datadog (`tools/datadog_tool.py`): `query_traces`, `get_trace_detail`, `query_logs`, `get_service_error_rate`. These call the Datadog REST API and expect a `tenant_id` tag on spans and logs.
- Cross-tenant (`tools/cross_tenant.py`): `find_pattern_across_tenants`, a spans aggregate grouped by `@tenant_id`.
- Knowledge (`tools/knowledge_tool.py`): `search_known_issues` (keyword search over every markdown file under `knowledge/`, including `knowledge/runbooks/`) and `get_runbook`.
- Workato (`tools/workato_tool.py`): `read_salesforce_case`, `update_salesforce_case_priority`, `create_tfs_ticket`. The orchestrator also calls a Teams notification webhook (not a model tool) when a smoke alert is found.

Behaviour set by the supervisor's system prompt:

- It is told to read the Salesforce case first when a case ID is present, and to show the draft TFS ticket to the engineer and get confirmation before creating it.
- It is told to treat a smoke-detector result of at least `SMOKE_THRESHOLD` errors across 4 or more tenants as a P1 platform-wide incident.
- For a platform-wide incident it is told to end its reply with a `<smoke_alert>` JSON block. The orchestrator parses that block into the `smoke_alert` field of the response.

## Prerequisites

- Python 3. The repo does not pin a version. Tested with Python 3.13.
- An Anthropic API key.
- A Datadog API key and application key.

## Setup

```bash
git clone https://github.com/9q4kt8t4df-byte/datadog-support-agent.git
cd datadog-support-agent
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`. `config.py` reads these variables:

| Variable | Status | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Required | none | Anthropic API access. The app fails at import time if it is missing. |
| `DD_API_KEY` | Required | none | Datadog API key. The app fails at import time if it is missing. |
| `DD_APP_KEY` | Required | none | Datadog application key. The app fails at import time if it is missing. |
| `DD_SITE` | Optional | `datadoghq.com` | Datadog site; requests go to `https://api.<DD_SITE>`. |
| `SMOKE_THRESHOLD` | Optional | `100` | Integer; used in the supervisor's system prompt. A non-integer value raises an error at startup. |
| `CHAT_BASE_URL` | Optional | `http://localhost:8000` | Base URL used to build the conversation link sent in Teams alerts. |
| `WORKATO_API_KEY` | Optional | empty | Sent as the `x-api-key` header on every Workato call. |
| `WORKATO_WEBHOOK_SF_READ` | Optional | empty | Enables `read_salesforce_case`. |
| `WORKATO_WEBHOOK_SF_UPDATE` | Optional | empty | Enables `update_salesforce_case_priority`. |
| `WORKATO_WEBHOOK_TFS_WRITE` | Optional | empty | Enables `create_tfs_ticket`. |
| `WORKATO_WEBHOOK_TEAMS_NOTIFY` | Optional | empty | Enables the Teams alert sent when a smoke alert is found. |

## Run

```bash
uvicorn api.main:app --reload --port 8000
```

Endpoints (`api/main.py`):

- `POST /api/chat`
- `GET /api/conversations/{conversation_id}/messages`
- `GET /health` returns `{"status": "ok"}`

## Example requests

The request body is `message` (required), `case_id` (optional), and `conversation_id` (optional), as in `api/models.py`.

```bash
# Start a conversation
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Customer Acme is getting 500s on /api/sync since 14:00 UTC"}'

# Include a Salesforce case ID
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Investigate this case", "case_id": "SF-12345"}'

# Continue a conversation
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Check if other tenants are seeing this too", "conversation_id": "<id from previous response>"}'

# Read the stored messages
curl http://localhost:8000/api/conversations/<id>/messages
```

The chat response has `conversation_id`, `response` (the agent's text), `tools_used` (tool names called by the supervisor), and `smoke_alert` (null unless a platform-wide incident was reported). The messages endpoint returns a list of `role`, `content` and `created_at`. An unknown `conversation_id` returns 404.

## Without the Workato variables

The Workato variables are optional. If a webhook URL is empty, the matching function does not fail. It returns a bracketed message to the agent instead:

- `read_salesforce_case`: "Workato not configured", so no case details are available.
- `update_salesforce_case_priority`: says the case was not updated and to set the priority manually.
- `create_tfs_ticket`: says no ticket was created and returns the title, priority, case ID and ticket body so it can be created by hand.
- Teams alert: says no alert was sent and manual notification is required.

If a webhook is set but the call fails, the function returns a bracketed HTTP error or "unreachable" message. Datadog calls are handled the same way.

## Where conversations are stored

`orchestrator/conversation.py` stores conversations and messages in SQLite with SQLModel. The default is `sqlite:///conversations.db`, a relative path, so the file `conversations.db` is created in the directory the server is started from. It is listed in `.gitignore`.

## Tests

```bash
pytest
```

`pytest.ini` sets `testpaths = tests` and `asyncio_mode = auto`. `tests/conftest.py` sets dummy values for `ANTHROPIC_API_KEY`, `DD_API_KEY`, `DD_APP_KEY` and `DD_SITE`, so no `.env` is needed. The tests do not call Anthropic or Datadog. Last run: 79 passed on Python 3.13.

## Repo map

- `api/` : FastAPI app (`main.py`) and request/response models (`models.py`)
- `orchestrator/` : `orchestrator.py` (chat flow, smoke alert parsing, Teams alert) and `conversation.py` (SQLite store)
- `agents/` : `base.py` (Claude tool-use loop), `supervisor.py`, `investigator.py`, `smoke_detector.py`
- `tools/` : `datadog_tool.py`, `cross_tenant.py`, `knowledge_tool.py`, `workato_tool.py`
- `knowledge/` : markdown known issues and runbooks searched by the knowledge tools
- `config.py` : environment variables and agent definitions
- `tests/` : pytest suite
