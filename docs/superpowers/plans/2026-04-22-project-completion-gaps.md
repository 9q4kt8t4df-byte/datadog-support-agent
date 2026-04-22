# Project Completion Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three remaining gaps before merging `mcp-integration` → `main`: write README.md, write `knowledge/datadog-apm-reference.md`, and open the final PR.

**Architecture:** Each gap is independent. README documents the finished system. The APM reference enriches agent knowledge. The PR merges the complete feature branch.

**Tech Stack:** GitHub CLI (`gh`), Markdown, Python 3.10+, Datadog MCP, FastAPI, pytest

---

### File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `README.md` | Project overview, setup, config, API, tests |
| Create | `knowledge/datadog-apm-reference.md` | Agent-facing APM reference (MCP tools, filter syntax, DDSQL, common tags) |
| PR | `mcp-integration` → `main` | Merge complete feature branch |

---

### Task 1: Write README.md

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README.md**

```markdown
# Datadog Support Agent

Multi-agent AI system for Datadog-integrated support automation. A Supervisor agent orchestrates two specialized sub-agents (Investigator and Smoke Detector) via the Anthropic API, using the Datadog MCP server for APM and log queries.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI (api/main.py)                    │
│                  POST /v1/support-cases/chat                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   Orchestrator (orchestrator/)               │
│          Parses <smoke_alert> tags → Workato webhook         │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                 SupervisorAgent (agents/supervisor.py)       │
│  Tools: query_traces, query_logs, delegate_to_agent,        │
│         read_salesforce_case, create_tfs_ticket,            │
│         update_salesforce_case_priority                     │
└─────────────┬────────────────────────────┬──────────────────┘
              │                            │
┌─────────────▼──────────┐  ┌─────────────▼──────────────────┐
│  InvestigatorAgent     │  │  SmokeDetectorAgent             │
│  (agents/investigator) │  │  (agents/smoke_detector.py)     │
│  Tools:                │  │  Tools:                         │
│    query_traces        │  │    find_pattern_across_tenants  │
│    get_trace_detail    │  │    query_traces                 │
│    query_logs          │  │    query_logs                   │
│    get_service_        │  │    get_service_error_rate       │
│      error_rate        │  │                                 │
│    search_known_issues │  │                                 │
└────────────────────────┘  └─────────────────────────────────┘
              │                            │
┌─────────────▼────────────────────────────▼──────────────────┐
│              Datadog MCP Server                              │
│   search_datadog_spans  · get_datadog_trace                  │
│   search_datadog_logs   · analyze_datadog_logs               │
│   ddsql_run_query                                            │
└─────────────────────────────────────────────────────────────┘
```

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Datadog account with APM enabled
- Anthropic API key

## Setup

```bash
# Clone and enter the project
git clone https://github.com/9q4kt8t4df-byte/datadog-support-agent
cd datadog-support-agent

# Create virtualenv with Python 3.10+
uv venv --python 3.10 .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your actual keys
```

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude |
| `DD_API_KEY` | Yes | Datadog API key |
| `DD_APP_KEY` | Yes | Datadog Application key |
| `DD_SITE` | No | Datadog site (default: `datadoghq.com`) |
| `DD_MCP_URL` | No | MCP server URL (default: `https://mcp.{DD_SITE}`) |
| `WORKATO_WEBHOOK_URL` | No | Workato webhook for Teams smoke alerts |
| `SMOKE_THRESHOLD` | No | Tenant count to trigger smoke alert (default: `3`) |

### Datadog MCP Transport

The tool supports two MCP transports:

**Streamable HTTP (recommended for server deployment):**
Set `DD_MCP_URL=https://mcp.datadoghq.com`. Authentication uses `DD_API_KEY` and `DD_APP_KEY` headers automatically.

**stdio (developer workstation):**
Leave `DD_MCP_URL` empty. The tool invokes the `datadog_mcp_cli` binary, which uses OAuth via browser. Install it from the Datadog docs.

## Running the API

```bash
uvicorn api.main:app --reload --port 8000
```

### API Endpoints

**POST /v1/support-cases/chat**

```json
{
  "case_id": "SF-12345",
  "tenant_id": "tenant-acme",
  "message": "Users are seeing ThrottlingException errors in sync-worker",
  "start_utc": "2026-04-21T13:00:00Z",
  "end_utc": "2026-04-21T15:00:00Z"
}
```

Response:
```json
{
  "case_id": "SF-12345",
  "response": "Investigation complete. Root cause: MS throttling...",
  "tools_used": ["query_traces", "search_known_issues"],
  "smoke_alert": null
}
```

If the Supervisor detects a cross-tenant pattern above `SMOKE_THRESHOLD`, `smoke_alert` will contain the structured alert payload, and the orchestrator posts it to the Workato webhook.

## Running Tests

```bash
pytest -v
```

86 tests across four suites:
- `tests/test_datadog_tool.py` — MCP tool dispatch, transport selection, sanitization
- `tests/test_cross_tenant.py` — DDSQL query construction, confidence levels
- `tests/test_agents.py` — agent tool definitions, supervisor delegation, config validation
- `tests/test_workato_tool.py` — Salesforce/TFS/Teams webhook calls

## Knowledge Base

The `knowledge/` directory contains markdown files that the `search_known_issues` tool searches:

- `known_issues.md` — Index of known error patterns
- `ms_throttling.md` — Microsoft throttling investigation guide
- `runbooks/connector_failure.md` — Connector failure runbook
- `datadog-apm-reference.md` — Datadog MCP tool reference for agents

## Project Structure

```
├── agents/
│   ├── base.py              # BaseAgent: Anthropic client, tool loop
│   ├── supervisor.py        # SupervisorAgent: orchestrates sub-agents
│   ├── investigator.py      # InvestigatorAgent: trace/log deep-dive
│   └── smoke_detector.py    # SmokeDetectorAgent: cross-tenant pattern detection
├── api/
│   └── main.py              # FastAPI app, conversation persistence
├── orchestrator/
│   └── main.py              # smoke_alert parsing, Workato forwarding
├── tools/
│   ├── datadog_tool.py      # Datadog MCP client (HTTP + stdio)
│   ├── cross_tenant.py      # DDSQL cross-tenant aggregation
│   ├── knowledge_tool.py    # Markdown knowledge base search
│   └── workato_tool.py      # Salesforce, TFS, Teams webhooks
├── knowledge/               # Agent knowledge base (Markdown)
├── tests/                   # pytest test suite (86 tests)
├── config.py                # Environment-based configuration
├── requirements.txt
└── .env.example
```
```

- [ ] **Step 2: Verify README.md was written**

Run: `wc -l README.md`
Expected: 150+ lines

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add README with architecture, setup, and API reference"
```

---

### Task 2: Write knowledge/datadog-apm-reference.md

**Files:**
- Create: `knowledge/datadog-apm-reference.md`

- [ ] **Step 1: Write the reference doc**

Content covers: MCP tool names and signatures, Datadog span filter syntax, DDSQL basics, common tag names for tenant-scoped queries.

- [ ] **Step 2: Verify file exists**

Run: `wc -l knowledge/datadog-apm-reference.md`
Expected: 80+ lines

- [ ] **Step 3: Commit**

```bash
git add knowledge/datadog-apm-reference.md
git commit -m "docs: add Datadog APM MCP reference for agents"
```

---

### Task 3: Open PR — mcp-integration → main

**Files:** none

- [ ] **Step 1: Push latest commits**

```bash
git push origin mcp-integration
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --base main --head mcp-integration \
  --title "feat: Datadog MCP integration with multi-agent support system" \
  --body "..."
```

- [ ] **Step 3: Verify PR URL is returned**

Expected: `https://github.com/9q4kt8t4df-byte/datadog-support-agent/pull/N`
