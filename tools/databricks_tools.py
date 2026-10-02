"""Databricks Jobs SDK utilities for job monitoring and failure details."""
from typing import Any, Dict, List

from databricks.sdk import WorkspaceClient
from config import Config


class DatabricksJobsClient:
    """Small wrapper around the Databricks Python SDK Jobs service."""

    def __init__(self) -> None:
        """Initialize the client from Databricks workspace settings."""
        self.workspace_client = WorkspaceClient(
            host=Config.DATABRICKS_WORKSPACE_HOST,
            token=Config.DATABRICKS_TOKEN,
        )

    def list_all_jobs(self) -> List[Dict[str, Any]]:
        """List all jobs using the SDK iterator and its built-in pagination."""
        return list(self.workspace_client.jobs.list(expand_tasks=False))

    def get_job_runs(self, job_id: int, max_results: int = 1) -> List[Dict[str, Any]]:
        """Get the most recent runs for a Databricks job."""
        return list(self.workspace_client.jobs.list_runs(
            job_id=job_id,
            limit=max_results,
            expand_tasks=True,
        ))

    @staticmethod
    def _value(value: Any) -> Any:
        """Return an SDK enum value as text while supporting plain test values."""
        return getattr(value, "value", value)

    @staticmethod
    def _normalize_status(run: Dict[str, Any]) -> str:
        """Map Databricks lifecycle and result states to monitor states."""
        state = run.state
        lifecycle_state = DatabricksJobsClient._value(state.life_cycle_state)
        result_state = DatabricksJobsClient._value(state.result_state)

        if lifecycle_state in {"PENDING", "RUNNING", "TERMINATING", "BLOCKED", "QUEUED"}:
            return "RUNNING"
        if result_state == "SUCCESS":
            return "SUCCEEDED"
        if lifecycle_state in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
            return "FAILED"
        return "UNKNOWN"

    def get_all_jobs_status(self) -> List[Dict[str, Any]]:
        """Return each job with the status of its latest run."""
        jobs_status: List[Dict[str, Any]] = []
        for job in self.list_all_jobs():
            job_id = job.job_id
            if job_id is None:
                continue
            runs = self.get_job_runs(job_id)
            if not runs:
                jobs_status.append({
                    "job_name": job.settings.name if job.settings else str(job_id),
                    "job_id": job_id,
                    "run_id": None,
                    "status": "UNKNOWN",
                    "started_on": None,
                    "completed_on": None,
                    "execution_time": None,
                    "error_message": "No runs found",
                })
                continue

            latest_run = runs[0]
            state = latest_run.state
            start_time = latest_run.start_time
            end_time = latest_run.end_time
            jobs_status.append({
                "job_name": latest_run.run_name or (job.settings.name if job.settings else str(job_id)),
                "job_id": job_id,
                "run_id": latest_run.run_id,
                "status": self._normalize_status(latest_run),
                "started_on": start_time,
                "completed_on": end_time,
                "execution_time": (
                    (end_time - start_time) / 1000 if start_time and end_time else None
                ),
                "error_message": state.state_message or "",
                "run_page_url": latest_run.run_page_url or "",
            })
        return jobs_status

    def get_failed_jobs(self) -> List[Dict[str, Any]]:
        """Return jobs whose latest run failed."""
        return [job for job in self.get_all_jobs_status() if job["status"] == "FAILED"]

    def get_job_logs(self, job_name: str, run_id: int) -> str:
        """Retrieve error details and output from a failed job or task run."""
        run = self.workspace_client.jobs.get_run(run_id)
        task_runs = getattr(run, "tasks", None) or []
        output_run_ids = [
            task_run.run_id
            for task_run in task_runs
            if getattr(task_run, "run_id", None) is not None
        ] or [run_id]

        logs: List[str] = []
        for task_run_id in output_run_ids:
            response = self.workspace_client.jobs.get_run_output(task_run_id)
            details = [
                response.error or "",
                response.error_trace or "",
                response.notebook_output.result if response.notebook_output else "",
            ]
            task_logs = "\n".join(str(detail) for detail in details if detail)
            if task_logs:
                logs.append(f"Task run {task_run_id}:\n{task_logs}")

        return "\n\n".join(logs) or f"No output found for job {job_name}, run {run_id}"

    def format_job_status_summary(self, jobs_status: List[Dict[str, Any]]) -> str:
        """Format Databricks job statuses for the monitor report."""
        if not jobs_status:
            return "No jobs found in Databricks"

        summary_parts = [f"Total Databricks jobs monitored: {len(jobs_status)}"]
        for job in jobs_status:
            summary_parts.extend([
                f"\nJob Name: {job['job_name']}",
                f"  Status: {job['status']}",
                f"  Run ID: {job['run_id']}",
            ])
            if job.get("error_message"):
                summary_parts.append(f"  Error: {job['error_message']}")
        return "\n".join(summary_parts)