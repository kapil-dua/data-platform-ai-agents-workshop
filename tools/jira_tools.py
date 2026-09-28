"""Shared Jira incident creation helpers for the data-ops agents."""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from config import Config


class JiraMCPClient:
    """Create Jira issues via the Atlassian Rovo MCP server."""

    def __init__(
        self,
        mcp_url: str | None = None,
        project_key: str | None = None,
        issue_type: str | None = None,
        mcp_token: str | None = None,
        auth_header: str | None = None,
        cloud_id: str | None = None,
    ) -> None:
        """Configure the Rovo client without creating a network connection."""
        self.mcp_url = mcp_url if mcp_url is not None else Config.ATLASSIAN_MCP_URL
        self.project_key = project_key if project_key is not None else Config.ATLASSIAN_PROJECT_KEY
        self.issue_type = issue_type if issue_type is not None else Config.ATLASSIAN_ISSUE_TYPE
        self.mcp_token = mcp_token if mcp_token is not None else Config.ATLASSIAN_API_TOKEN
        self.auth_header = auth_header or Config.ATLASSIAN_AUTH_HEADER
        if not self.auth_header and Config.ATLASSIAN_EMAIL and self.mcp_token:
            credentials = f"{Config.ATLASSIAN_EMAIL}:{self.mcp_token}"
            encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
            self.auth_header = f"Basic {encoded}"
        self.cloud_id = cloud_id if cloud_id is not None else Config.ATLASSIAN_CLOUD_ID

    def create_incidents(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Create each Jira incident and retain a result for every RCA."""
        if not results:
            return []
        if not self.project_key:
            return [self._failure(result, "JIRA_PROJECT_KEY is not configured") for result in results]
        if not self.auth_header:
            return [self._failure(result, "Atlassian authorization is not configured") for result in results]
        try:
            return asyncio.run(self._create_incidents_async(results))
        except Exception as exc:
            return [self._failure(result, str(exc)) for result in results]

    async def _create_incidents_async(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Create issues through Atlassian's executeWrite MCP wrapper."""
        headers = {"Authorization": self.auth_header, "Content-Type": "application/json"}
        incidents: list[dict[str, Any]] = []
        async with streamablehttp_client(url=self.mcp_url, headers=headers) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                for result in results:
                    try:
                        response = await session.call_tool(
                            name="executeWrite",
                            arguments=self._issue_arguments(result),
                        )
                        if response.isError:
                            raise RuntimeError(str(response.content))
                        incidents.append(
                            {
                                "incident_id": f"JIRA-{result['run_id']}",
                                "job_name": result["job_name"],
                                "run_id": result["run_id"],
                                "severity": result["severity"],
                                "status": "created",
                                "message": "Jira incident created through Atlassian Rovo MCP",
                                "jira_response": "\n".join(
                                    getattr(item, "text", str(item)) for item in response.content
                                ),
                            }
                        )
                    except Exception as exc:
                        incidents.append(self._failure(result, str(exc)))
        return incidents

    def _issue_arguments(self, result: dict[str, Any]) -> dict[str, Any]:
        """Build the executeWrite envelope used by the working MCP request."""
        description = (
            f"ETL job: {result['job_name']}\nRun ID: {result['run_id']}\n"
            f"Severity: {result['severity']}\n\n"
            f"Root cause: {result.get('root_cause', 'Not provided')}\n\n"
            f"Recommendations: {', '.join(result.get('recommendations', [])) or 'Not provided'}\n\n"
            f"Error: {result.get('error_message', 'Not provided')}"
        )
        return {
            "name": "createJiraIssue",
            "cloudId": self.cloud_id,
            "inputs": {
                "projectKey": self.project_key,
                "summary": f"[{result['severity']}] ETL failure: {result['job_name']}",
                "description": description,
                "issueType": self.issue_type,
            },
        }

    @staticmethod
    def _failure(result: dict[str, Any], message: str) -> dict[str, Any]:
        """Return a stable failed result without exposing credentials."""
        return {
            "incident_id": f"JIRA-{result.get('run_id', 'unknown')}",
            "job_name": result.get("job_name", "unknown"),
            "run_id": result.get("run_id"),
            "severity": result.get("severity"),
            "status": "failed",
            "message": message,
        }
