"""Create Jira incidents through the Atlassian Rovo MCP server."""
from typing import Any

from agents.base_agent import AgentResult
from config import Config
from tools.jira_tools import JiraMCPClient


class IncidentAgent:
    """Create Jira incidents for qualifying RCA results via Rovo MCP."""

    name = "Incident Agent"
    description = "Creates Jira incidents for qualifying job failures"

    def __init__(
        self,
        mcp_url: str | None = None,
        project_key: str | None = None,
        issue_type: str | None = None,
        mcp_token: str | None = None,
        auth_header: str | None = None,
        cloud_id: str | None = None,
    ) -> None:
        """Configure the Jira client wrapper used by the workflow."""
        self.JIRA_ENABLED = Config.JIRA_ENABLED
        self.client = JiraMCPClient(
            mcp_url=mcp_url,
            project_key=project_key,
            issue_type=issue_type,
            mcp_token=mcp_token,
            auth_header=auth_header,
            cloud_id=cloud_id,
        )

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.JIRA_ENABLED:
            return self.execute_jira(state)
        return self.execute_dummy(state)

    def execute_dummy(self, state: dict[str, Any]) -> dict[str, Any]:
        """Create demo incidents without calling an external incident system."""
        print(f"{self.name}: JIRA_ENABLED is false; creating demo incidents instead")
        incidents = []
        for result in state.get("rca_results", []):
            if result.get("severity") in {"Critical", "High", "Medium"}:
                incidents.append({
                    "incident_id": f"DEMO-{result['run_id']}",
                    "job_name": result["job_name"],
                    "run_id": result["run_id"],
                    "severity": result["severity"],
                    "status": "created",
                    "message": "Demo incident created",
                })

        return {
            **state,
            "incident_results": incidents,
            "execution_log": [
                *state.get("execution_log", []),
                f"{self.name}: created {len(incidents)} demo incident(s)",
            ],
            "agent_results": [
                *state.get("agent_results", []),
                AgentResult(
                    agent=self.name,
                    status="completed",
                    message=f"Created {len(incidents)} demo incident(s)",
                    data={"incident_count": len(incidents)},
                ),
            ],
            "workflow_status": "completed",
        }
    
    def execute_jira(self, state: dict[str, Any]) -> dict[str, Any]:
        """Create Jira incidents for medium, high, and critical RCA results."""
        print(f"{self.name}: JIRA_ENABLED is true; creating Jira incidents through Rovo MCP")
        qualifying_results = [
            result for result in state.get("rca_results", [])
            if result.get("severity") in {"Critical", "High", "Medium"}
        ]
        incidents = self._create_incidents(qualifying_results)
        created_count = sum(incident["status"] == "created" for incident in incidents)
        failed_count = len(incidents) - created_count
        execution_status = "completed" if failed_count == 0 else "completed_with_errors"

        return {
            **state,
            "incident_results": incidents,
            "execution_log": [
                *state.get("execution_log", []),
                f"{self.name}: created {created_count} Jira incident(s)"
                + (f"; {failed_count} failed" if failed_count else ""),
            ],
            "agent_results": [
                *state.get("agent_results", []),
                AgentResult(
                    agent=self.name,
                    status=execution_status,
                    message=f"Created {created_count} Jira incident(s)"
                    + (f"; {failed_count} failed" if failed_count else ""),
                    data={"incident_count": created_count, "failed_count": failed_count},
                ),
            ],
            "workflow_status": "completed",
        }

    def _create_incidents(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Create each Jira incident using the shared Jira client."""
        return self.client.create_incidents(results)