"""Databricks Jobs SDK utilities for job monitoring and failure details.

Multi-task pipeline aware: when a pipeline job has multiple tasks, failed
tasks are surfaced individually so the RCA agent analyses each one separately.
"""
from typing import Any, Dict, List

from databricks.sdk import WorkspaceClient
from config import Config


class DatabricksJobsClient:
    """Small wrapper around the Databricks Python SDK Jobs service."""

    def __init__(self) -> None:
        self.workspace_client = WorkspaceClient(
            host=Config.DATABRICKS_WORKSPACE_HOST,
            token=Config.DATABRICKS_TOKEN,
        )

    def list_all_jobs(self) -> List[Dict[str, Any]]:
        return list(self.workspace_client.jobs.list(expand_tasks=False))

    def get_job_runs(self, job_id: int, max_results: int = 1) -> List[Dict[str, Any]]:
        return list(self.workspace_client.jobs.list_runs(
            job_id=job_id,
            limit=max_results,
            expand_tasks=True,
        ))

    @staticmethod
    def _value(value: Any) -> Any:
        return getattr(value, "value", value)

    @staticmethod
    def _normalize_status(run) -> str:
        """Map Databricks lifecycle/result state to a simple RUNNING/SUCCEEDED/FAILED/UNKNOWN string."""
        state          = run.state
        lifecycle_state = DatabricksJobsClient._value(state.life_cycle_state)
        result_state   = DatabricksJobsClient._value(state.result_state)
        if lifecycle_state in {"PENDING", "RUNNING", "TERMINATING", "BLOCKED", "QUEUED"}:
            return "RUNNING"
        if result_state == "SUCCESS":
            return "SUCCEEDED"
        if lifecycle_state in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
            return "FAILED"
        return "UNKNOWN"

    def get_all_jobs_status(self) -> List[Dict[str, Any]]:
        """Return each failed task as a separate entry for multi-task pipelines.

        For a pipeline job with 5 tasks where 2 fail:
          - Returns 2 entries (one per failed task) so RCA agent analyses each separately
          - job_name = "<pipeline_name> / <task_key>" for clear identification
          - Successful tasks are not included (no RCA needed)
          - Single-task jobs behave exactly as before
        """
        jobs_status: List[Dict[str, Any]] = []

        for job in self.list_all_jobs():
            job_id = job.job_id
            if job_id is None:
                continue

            runs = self.get_job_runs(job_id)
            if not runs:
                jobs_status.append({
                    "job_name":      job.settings.name if job.settings else str(job_id),
                    "job_id":        job_id,
                    "run_id":        None,
                    "task_key":      None,
                    "status":        "UNKNOWN",
                    "started_on":    None,
                    "completed_on":  None,
                    "execution_time":None,
                    "error_message": "No runs found",
                    "run_page_url":  "",
                    "is_pipeline":   False,
                })
                continue

            latest_run = runs[0]
            pipeline_name = latest_run.run_name or (
                job.settings.name if job.settings else str(job_id)
            )
            start_time = latest_run.start_time
            end_time   = latest_run.end_time

            task_runs = getattr(latest_run, "tasks", None) or []

            # Count distinct task keys (not all run objects — a single task can have multiple run objects)
            distinct_task_keys = {getattr(t, "task_key", None) for t in task_runs if getattr(t, "task_key", None)}
            is_multi_task = len(distinct_task_keys) > 1

            if not task_runs or not is_multi_task:
                # Single-task job — use job-level entry directly (no task suffix)
                state_msg = latest_run.state.state_message or ""
                # Fetch actual error from run output if state_message is generic
                actual_error = state_msg
                if self._normalize_status(latest_run) == "FAILED" and (
                    not state_msg or "check run details" in state_msg.lower()
                ):
                    try:
                        task_run_id = task_runs[0].run_id if task_runs else latest_run.run_id
                        output = self.workspace_client.jobs.get_run_output(task_run_id)
                        raw_err = (
                            output.error
                            or output.error_trace
                            or (output.notebook_output.result if output.notebook_output else "")
                            or state_msg
                        )
                        if raw_err:
                            first_line = [l.strip() for l in raw_err.split("\n") if l.strip()]
                            actual_error = first_line[0] if first_line else raw_err
                    except Exception:
                        pass

                jobs_status.append({
                    "job_name":      pipeline_name,
                    "job_id":        job_id,
                    "run_id":        latest_run.run_id,
                    "task_key":      None,
                    "status":        self._normalize_status(latest_run),
                    "started_on":    start_time,
                    "completed_on":  end_time,
                    "execution_time":(
                        (end_time - start_time) / 1000
                        if start_time and end_time else None
                    ),
                    "error_message": actual_error,
                    "run_page_url":  latest_run.run_page_url or "",
                    "is_pipeline":   False,
                })
            else:
                # Genuine multi-task pipeline — surface each task individually
                overall_status = self._normalize_status(latest_run)

                # Always add one entry for the overall pipeline status
                jobs_status.append({
                    "job_name":      pipeline_name,
                    "job_id":        job_id,
                    "run_id":        latest_run.run_id,
                    "task_key":      None,
                    "status":        overall_status,
                    "started_on":    start_time,
                    "completed_on":  end_time,
                    "execution_time":(
                        (end_time - start_time) / 1000
                        if start_time and end_time else None
                    ),
                    "error_message": latest_run.state.state_message or "",
                    "run_page_url":  latest_run.run_page_url or "",
                    "is_pipeline":   True,
                    "task_count":    len(task_runs),
                })

                # Add individual entries for each FAILED task
                # Deduplicate by task_key — the SDK returns one task object per
                # historical pipeline run, so the same task_key can appear
                # multiple times when get_job_runs returns >1 run worth of tasks.
                # We keep only the first (latest) occurrence per key.
                seen_task_keys: set = set()
                for task in task_runs:
                    task_status = self._normalize_status(task)
                    if task_status != "FAILED":
                        continue

                    task_key = getattr(task, "task_key", "unknown")
                    # Skip duplicate task keys (can appear if pipeline ran multiple times)
                    if task_key in seen_task_keys:
                        continue
                    seen_task_keys.add(task_key)
                    task_status = self._normalize_status(task)
                    if task_status != "FAILED":
                        continue

                    task_key = getattr(task, "task_key", "unknown")
                    t_start  = getattr(task, "start_time", None)
                    t_end    = getattr(task, "end_time", None)
                    t_state  = getattr(task, "state", None)
                    t_error  = (
                        getattr(t_state, "state_message", "") or ""
                        if t_state else ""
                    )

                    # Try to get the actual error from run output
                    # state_message often just says "check run details"
                    task_run_id = getattr(task, "run_id", None)
                    actual_error = t_error
                    if task_run_id and (not t_error or "check run details" in t_error.lower()):
                        try:
                            output = self.workspace_client.jobs.get_run_output(task_run_id)
                            actual_error = (
                                output.error
                                or output.error_trace
                                or (output.notebook_output.result if output.notebook_output else "")
                                or t_error
                            )
                            # Trim to first meaningful line for the summary
                            if actual_error:
                                first_line = [l.strip() for l in actual_error.split("\n") if l.strip()]
                                actual_error = first_line[0] if first_line else actual_error
                        except Exception:
                            pass

                    jobs_status.append({
                        "job_name":      f"{pipeline_name} / {task_key}",
                        "job_id":        job_id,
                        "run_id":        getattr(task, "run_id", latest_run.run_id),
                        "task_key":      task_key,
                        "pipeline_name": pipeline_name,
                        "status":        "FAILED",
                        "started_on":    t_start,
                        "completed_on":  t_end,
                        "execution_time":(
                            (t_end - t_start) / 1000
                            if t_start and t_end else None
                        ),
                        "error_message": actual_error,
                        "run_page_url":  getattr(task, "run_page_url", ""),
                        "is_pipeline":   True,
                        "is_task":       True,
                    })

        return jobs_status

    def get_failed_jobs(self) -> List[Dict[str, Any]]:
        """Return only failed task entries (not the overall pipeline entry)."""
        return [
            job for job in self.get_all_jobs_status()
            if job["status"] == "FAILED" and (job.get("is_task") or not job.get("is_pipeline"))
        ]

    def get_job_logs(self, job_name: str, run_id: int) -> str:
        """Retrieve error details from a failed task run.

        For multi-task pipelines the run_id is the task-level run_id,
        so this works for both single-task and multi-task jobs.
        """
        try:
            run = self.workspace_client.jobs.get_run(run_id)
        except Exception:
            return f"Could not retrieve run details for run_id={run_id}"

        task_runs = getattr(run, "tasks", None) or []

        # Collect output run IDs (task sub-runs if present, else the run itself)
        output_run_ids = [
            task_run.run_id
            for task_run in task_runs
            if getattr(task_run, "run_id", None) is not None
        ] or [run_id]

        logs: List[str] = []
        for task_run_id in output_run_ids:
            try:
                response = self.workspace_client.jobs.get_run_output(task_run_id)
                details = [
                    response.error or "",
                    response.error_trace or "",
                    response.notebook_output.result if response.notebook_output else "",
                ]
                task_logs = "\n".join(str(d) for d in details if d)
                if task_logs:
                    logs.append(f"Task run {task_run_id}:\n{task_logs}")
            except Exception as e:
                logs.append(f"Task run {task_run_id}: could not retrieve output ({e})")

        return "\n\n".join(logs) or f"No output found for {job_name}, run {run_id}"

    def format_job_status_summary(self, jobs_status: List[Dict[str, Any]]) -> str:
        """Format job/pipeline statuses for the monitor summary."""
        if not jobs_status:
            return "No jobs found in Databricks"

        # Separate pipelines from individual job entries
        pipelines = [j for j in jobs_status if j.get("is_pipeline") and not j.get("is_task")]
        singles   = [j for j in jobs_status if not j.get("is_pipeline")]
        tasks     = [j for j in jobs_status if j.get("is_task")]

        parts = [f"Total jobs monitored: {len(pipelines) + len(singles)}"]

        for j in pipelines:
            parts.append(
                f"\nPipeline: {j['job_name']} | Status: {j['status']} "
                f"| Tasks: {j.get('task_count', '?')} | Run: {j['run_id']}"
            )

        for j in singles:
            parts.append(f"\nJob: {j['job_name']} | Status: {j['status']} | Run: {j['run_id']}")
            if j.get("error_message"):
                parts.append(f"  Error: {j['error_message']}")

        if tasks:
            parts.append(f"\nFailed tasks ({len(tasks)}):")
            for t in tasks:
                parts.append(f"  ❌ {t['job_name']} | Run: {t['run_id']}")
                if t.get("error_message"):
                    parts.append(f"     Error: {t['error_message']}")

        return "\n".join(parts)
