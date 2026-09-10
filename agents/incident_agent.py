"""Demo incident creation agent."""
from typing import Any

from agents.base_agent import AgentResult


class IncidentAgent:
    """Create simulated incidents for high-severity RCA results."""

    name = "Incident Agent"
    description = "Creates demo incidents for qualifying job failures"

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Create demo incidents without calling an external incident system."""
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