"""
Monitor Agent - Monitors Data Platform ETL job status
"""
from typing import Any, TypedDict
from agents.base_agent import AgentResult
from tools.databricks_tools import DatabricksJobsClient
from models.llm_client import LLMClient


class MonitorAgentState(TypedDict):
    """State for monitor agent"""
    jobs_data: dict
    summary: str
    failed_jobs: list


class MonitorAgent:
    """Agent responsible for monitoring Databricks job status"""
    
    def __init__(self):
        """Initialize monitor agent"""
        self.databricks_client = DatabricksJobsClient()
        self.name = "Monitor Agent"
        self.description = "Monitors Databricks jobs and reports their status"

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute monitoring using the common worker-agent contract."""
        return self.monitor_jobs(state)
    
    def monitor_jobs(self, state: dict) -> dict:
        """
        Monitor all Databricks jobs and return their status

        Args:
            state: Current agent state

        Returns:
            Updated state with monitoring results
        """
        try:
            print(f"[{self.name}] Starting job monitoring...")

            # Get all jobs status
            all_jobs = self.databricks_client.get_all_jobs_status()
            # For multi-task pipelines, only include individual task failures (not the pipeline-level entry)
            # For single-task jobs, include only the job-level entry (not the redundant task entry)
            # Deduplicate by job_id: prefer task-level entries for multi-task, job-level for single-task
            all_failed = [job for job in all_jobs if job['status'] == 'FAILED']

            # Group by job_id, keep only the most useful entry
            seen_job_ids: set = set()
            failed_jobs = []
            # First pass: task-level entries from genuine multi-task jobs
            for job in all_failed:
                if job.get('is_task') and job.get('pipeline_name'):
                    jid = f"{job['job_id']}_{job.get('task_key','')}"
                    if jid not in seen_job_ids:
                        seen_job_ids.add(jid)
                        seen_job_ids.add(str(job['job_id']))  # block job-level duplicate
                        failed_jobs.append(job)
            # Second pass: job-level entries not already covered
            for job in all_failed:
                if not job.get('is_task') and not job.get('is_pipeline'):
                    jid = str(job['job_id'])
                    if jid not in seen_job_ids:
                        seen_job_ids.add(jid)
                        failed_jobs.append(job)

            # Format data for LLM analysis
            jobs_summary = self.databricks_client.format_job_status_summary(all_jobs)

            # Log monitoring results
            monitoring_stats = {
                "total_jobs": len(all_jobs),
                "failed_count": len(failed_jobs),
                "successful_count": len([j for j in all_jobs if j['status'] == 'SUCCEEDED']),
                "running_count": len([j for j in all_jobs if j['status'] == 'RUNNING']),
            }

            print(f"[{self.name}] Monitoring complete. Found {len(failed_jobs)} failed jobs.")

            return {
                "jobs_data": {
                    "all_jobs": all_jobs,
                    **monitoring_stats
                },
                "failed_jobs": failed_jobs,
                "monitor_summary": jobs_summary,
                "execution_log": [
                    f"{self.name}: found {len(failed_jobs)} failed job(s)",
                ],
                "agent_results": [
                    AgentResult(
                        agent=self.name,
                        status="completed",
                        message=f"Found {len(failed_jobs)} failed job(s)",
                        data=monitoring_stats,
                    ),
                ],
            }

        except Exception:
            raise
    
    def get_job_details(self, job_name: str) -> dict:
        """Get detailed information about a specific job"""
        job_runs = self.databricks_client.get_job_runs(job_name, max_results=5)
        return {
            "job_name": job_name,
            "recent_runs": job_runs
        }