from __future__ import annotations
import httpx
import config


class WorkatoTool:
    """
    Calls Workato webhook endpoints. The only path to Salesforce and Azure TFS.
    All functions degrade gracefully when webhooks are not configured.
    """

    def __init__(self):
        self.sf_read_url = config.WORKATO_WEBHOOK_SF_READ
        self.tfs_write_url = config.WORKATO_WEBHOOK_TFS_WRITE
        self.api_key = config.WORKATO_API_KEY
        self.teams_notify_url = config.WORKATO_WEBHOOK_TEAMS_NOTIFY
        self.sf_update_url = config.WORKATO_WEBHOOK_SF_UPDATE

    @staticmethod
    def _build_ticket_body(
        root_cause: str,
        affected_tenants: list,
        evidence_links: list,
        priority: str,
        linked_sf_case_id: str,
    ) -> str:
        tenants_md = "\n".join(f"- {t}" for t in affected_tenants) or "- (none)"
        evidence_md = "\n".join(f"- {e}" for e in evidence_links) or "- (none)"
        return (
            f"## Root Cause\n{root_cause}\n\n"
            f"## Affected Tenants\n{tenants_md}\n\n"
            f"## Evidence\n{evidence_md}\n\n"
            f"## Priority\n{priority}\n\n"
            f"## Linked Salesforce Case\n{linked_sf_case_id}"
        )

    async def read_salesforce_case(self, case_id: str) -> str:
        if not self.sf_read_url:
            return f"[Workato not configured — Salesforce read unavailable. Case ID: {case_id}]"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.sf_read_url,
                    json={"case_id": case_id},
                    headers={"x-api-key": self.api_key},
                    timeout=30,
                )
                response.raise_for_status()
                return response.text
        except httpx.HTTPStatusError as e:
            return f"[Workato error — HTTP {e.response.status_code}]"
        except httpx.RequestError as e:
            return f"[Workato unreachable — {type(e).__name__}: {e}]"

    async def create_tfs_ticket(
        self,
        title: str,
        root_cause: str,
        affected_tenants: list,
        evidence_links: list,
        priority: str,
        linked_sf_case_id: str,
    ) -> str:
        body = self._build_ticket_body(
            root_cause=root_cause,
            affected_tenants=affected_tenants,
            evidence_links=evidence_links,
            priority=priority,
            linked_sf_case_id=linked_sf_case_id,
        )
        if not self.tfs_write_url:
            return (
                "[Workato not configured — TFS ticket NOT created. "
                "Please create manually with the following details:\n"
                f"Title: {title}\n"
                f"Priority: {priority}\n"
                f"SF Case: {linked_sf_case_id}\n\n"
                f"{body}]"
            )
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.tfs_write_url,
                    json={
                        "title": title,
                        "root_cause": root_cause,
                        "affected_tenants": affected_tenants,
                        "evidence_links": evidence_links,
                        "priority": priority,
                        "linked_sf_case_id": linked_sf_case_id,
                        "body": body,
                    },
                    headers={"x-api-key": self.api_key},
                    timeout=30,
                )
                response.raise_for_status()
                return response.text
        except httpx.HTTPStatusError as e:
            return f"[Workato error — HTTP {e.response.status_code}]"
        except httpx.RequestError as e:
            return f"[Workato unreachable — {type(e).__name__}: {e}]"

    async def send_teams_alert(
        self,
        case_id: str,
        root_cause: str,
        affected_tenant_count: int,
        affected_tenant_ids: list,
        earliest_occurrence_utc: str,
        pattern_confidence: str,
        conversation_url: str,
    ) -> str:
        if not self.teams_notify_url:
            return (
                f"[Workato not configured — Teams alert NOT sent. Manual notification required.\n"
                f"Case: {case_id} | Tenants: {affected_tenant_count} | Confidence: {pattern_confidence}]"
            )
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.teams_notify_url,
                    json={
                        "case_id": case_id,
                        "root_cause": root_cause,
                        "affected_tenant_count": affected_tenant_count,
                        "affected_tenant_ids": affected_tenant_ids,
                        "earliest_occurrence_utc": earliest_occurrence_utc,
                        "pattern_confidence": pattern_confidence,
                        "conversation_url": conversation_url,
                    },
                    headers={"x-api-key": self.api_key},
                    timeout=30,
                )
                response.raise_for_status()
                return response.text
        except httpx.HTTPStatusError as e:
            return f"[Workato error — HTTP {e.response.status_code}]"
        except httpx.RequestError as e:
            return f"[Workato unreachable — {type(e).__name__}: {e}]"

    async def update_salesforce_case_priority(
        self,
        case_id: str,
        priority: str,
    ) -> str:
        if not self.sf_update_url:
            return (
                f"[Workato not configured — Salesforce case {case_id} NOT updated. "
                f"Please manually set priority to {priority}.]"
            )
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.sf_update_url,
                    json={"case_id": case_id, "priority": priority},
                    headers={"x-api-key": self.api_key},
                    timeout=30,
                )
                response.raise_for_status()
                return response.text
        except httpx.HTTPStatusError as e:
            return f"[Workato error — HTTP {e.response.status_code}]"
        except httpx.RequestError as e:
            return f"[Workato unreachable — {type(e).__name__}: {e}]"

    def as_tools(self) -> list:
        return [
            {
                "name": "read_salesforce_case",
                "description": (
                    "Fetch details of a Salesforce support case by case ID. "
                    "Returns case subject, description, customer name, tenant_id, priority, and opened_at. "
                    "Call this first if the engineer provides a case_id."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "case_id": {"type": "string", "description": "Salesforce case ID, e.g. SF-12345"}
                    },
                    "required": ["case_id"],
                },
            },
            {
                "name": "create_tfs_ticket",
                "description": (
                    "Create an escalation ticket in Azure TFS/Azure DevOps. "
                    "IMPORTANT: Always present the ticket body to the engineer and receive confirmation BEFORE calling this tool."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "root_cause": {"type": "string"},
                        "affected_tenants": {"type": "array", "items": {"type": "string"}},
                        "evidence_links": {"type": "array", "items": {"type": "string"}},
                        "priority": {"type": "string", "enum": ["P1", "P2", "P3", "P4"]},
                        "linked_sf_case_id": {"type": "string"},
                    },
                    "required": ["title", "root_cause", "affected_tenants", "evidence_links", "priority", "linked_sf_case_id"],
                },
            },
            {
                "name": "update_salesforce_case_priority",
                "description": (
                    "Update the priority of a Salesforce support case via Workato. "
                    "Call this when escalating a confirmed platform-wide incident to P1, "
                    "BEFORE calling create_tfs_ticket. "
                    "Extract case_id from the [Salesforce case_id: ...] prefix in the conversation."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "case_id": {"type": "string", "description": "Salesforce case ID, e.g. SF-12345"},
                        "priority": {"type": "string", "enum": ["P1", "P2", "P3", "P4"]},
                    },
                    "required": ["case_id", "priority"],
                },
            },
        ]

    async def call(self, tool_name: str, tool_input: dict) -> str:
        if tool_name == "read_salesforce_case":
            return await self.read_salesforce_case(**tool_input)
        if tool_name == "create_tfs_ticket":
            return await self.create_tfs_ticket(**tool_input)
        if tool_name == "update_salesforce_case_priority":
            return await self.update_salesforce_case_priority(**tool_input)
        return f"Unknown tool: {tool_name}"
