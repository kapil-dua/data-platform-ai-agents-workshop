"""
Monitor Agent - Monitors AWS Glue ETL job status
"""
from typing import TypedDict, Annotated
from langchain_core.messages import HumanMessage, SystemMessage
from utils.aws_utils import AWSGlueClient
from utils.llm_utils import LLMClient


class MonitorAgentState(TypedDict):
    """State for monitor agent"""
    jobs_data: dict
    summary: str
    failed_jobs: list


class MonitorAgent:
    """Agent responsible for monitoring AWS Glue job status"""
    
    def __init__(self):
        """Initialize monitor agent"""
        self.aws_client = AWSGlueClient()
        self.llm_client = LLMClient()
        self.name = "Monitor Agent"
        self.description = "Monitors AWS Glue ETL jobs and reports their status"
    
    def monitor_jobs(self, state: dict) -> dict:
        """
        Monitor all AWS Glue jobs and return their status
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with monitoring results
        """
        print(f"[{self.name}] Starting job monitoring...")
        
        # Get all jobs status
        all_jobs = self.aws_client.get_all_jobs_status()
        failed_jobs = [job for job in all_jobs if job['status'] == 'FAILED']
        
        # Format data for LLM analysis
        jobs_summary = self.aws_client.format_job_status_summary(all_jobs)
        
        # Use LLM to create intelligent summary
        system_prompt = """You are a monitoring agent analyzing AWS Glue ETL jobs.
        Provide a concise summary of the job statuses, highlighting:
        - Total number of jobs
        - Number of successful, failed, and running jobs
        - Any patterns or concerns you notice
        Keep the summary clear and actionable."""
        
        llm_summary = self.llm_client.invoke_with_prompt(
            system_message=system_prompt,
            user_message=f"Analyze these job statuses:\n\n{jobs_summary}"
        )
        
        print(f"[{self.name}] Monitoring complete. Found {len(failed_jobs)} failed jobs.")
        
        return {
            **state,
            "jobs_data": {
                "all_jobs": all_jobs,
                "total_jobs": len(all_jobs),
                "failed_count": len(failed_jobs),
                "successful_count": len([j for j in all_jobs if j['status'] == 'SUCCEEDED']),
                "running_count": len([j for j in all_jobs if j['status'] == 'RUNNING'])
            },
            "failed_jobs": failed_jobs,
            "monitor_summary": llm_summary
        }
    
    def get_job_details(self, job_name: str) -> dict:
        """Get detailed information about a specific job"""
        job_runs = self.aws_client.get_job_runs(job_name, max_results=5)
        return {
            "job_name": job_name,
            "recent_runs": job_runs
        }