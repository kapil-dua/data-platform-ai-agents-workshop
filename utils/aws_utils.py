"""
AWS utility functions for Glue job monitoring and log retrieval
"""
import boto3
from typing import Dict, List, Optional
from datetime import datetime
from config.config import Config


class AWSGlueClient:
    """AWS Glue client wrapper for job monitoring"""
    
    def __init__(self):
        """Initialize AWS Glue client"""
        self.glue_client = boto3.client(
            'glue',
            aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
            region_name=Config.AWS_REGION
        )
        
        self.logs_client = boto3.client(
            'logs',
            aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
            region_name=Config.AWS_REGION
        )
    
    def list_all_jobs(self) -> List[str]:
        """List all Glue jobs"""
        try:
            response = self.glue_client.list_jobs()
            return response.get('JobNames', [])
        except Exception as e:
            print(f"Error listing Glue jobs: {str(e)}")
            return []
    
    def get_job_runs(self, job_name: str, max_results: int = 10) -> List[Dict]:
        """Get recent job runs for a specific job"""
        try:
            response = self.glue_client.get_job_runs(
                JobName=job_name,
                MaxResults=max_results
            )
            return response.get('JobRuns', [])
        except Exception as e:
            print(f"Error getting job runs for {job_name}: {str(e)}")
            return []
    
    def get_job_run_details(self, job_name: str, run_id: str) -> Optional[Dict]:
        """Get detailed information about a specific job run"""
        try:
            response = self.glue_client.get_job_run(
                JobName=job_name,
                RunId=run_id
            )
            return response.get('JobRun', {})
        except Exception as e:
            print(f"Error getting job run details: {str(e)}")
            return None
    
    def get_all_jobs_status(self) -> List[Dict]:
        """Get status of all Glue jobs with their latest runs"""
        jobs_status = []
        job_names = self.list_all_jobs()
        
        for job_name in job_names:
            job_runs = self.get_job_runs(job_name, max_results=1)
            if job_runs:
                latest_run = job_runs[0]
                jobs_status.append({
                    'job_name': job_name,
                    'run_id': latest_run.get('Id'),
                    'status': latest_run.get('JobRunState'),
                    'started_on': latest_run.get('StartedOn'),
                    'completed_on': latest_run.get('CompletedOn'),
                    'execution_time': latest_run.get('ExecutionTime'),
                    'error_message': latest_run.get('ErrorMessage', '')
                })
        
        return jobs_status
    
    def get_failed_jobs(self) -> List[Dict]:
        """Get all jobs that have failed in their latest run"""
        all_jobs = self.get_all_jobs_status()
        return [job for job in all_jobs if job['status'] == 'FAILED']
    
    def get_job_logs(self, job_name: str, run_id: str) -> str:
        """Retrieve CloudWatch logs for a failed job run"""
        try:
            # Construct log group name (Glue uses this pattern)
            log_group_name = f"/aws-glue/jobs/error"
            log_stream_prefix = f"{job_name}/{run_id}"
            
            # Get log streams
            log_streams_response = self.logs_client.describe_log_streams(
                logGroupName=log_group_name,
                logStreamNamePrefix=log_stream_prefix,
                orderBy='LastEventTime',
                descending=True,
                limit=5
            )
            
            log_streams = log_streams_response.get('logStreams', [])
            
            if not log_streams:
                return f"No logs found for job {job_name}, run {run_id}"
            
            # Get log events from the most recent stream
            all_logs = []
            for log_stream in log_streams[:2]:  # Get logs from top 2 streams
                log_stream_name = log_stream['logStreamName']
                
                events_response = self.logs_client.get_log_events(
                    logGroupName=log_group_name,
                    logStreamName=log_stream_name,
                    limit=100,
                    startFromHead=False
                )
                
                events = events_response.get('events', [])
                for event in events:
                    all_logs.append(event['message'])
            
            return "\n".join(all_logs) if all_logs else "No log messages found"
            
        except self.logs_client.exceptions.ResourceNotFoundException:
            return f"Log group not found for job {job_name}"
        except Exception as e:
            return f"Error retrieving logs: {str(e)}"
    
    def format_job_status_summary(self, jobs_status: List[Dict]) -> str:
        """Format job status information for LLM consumption"""
        if not jobs_status:
            return "No jobs found in AWS Glue"
        
        summary_parts = [f"Total jobs monitored: {len(jobs_status)}\n"]
        
        for job in jobs_status:
            summary_parts.append(f"\nJob Name: {job['job_name']}")
            summary_parts.append(f"  Status: {job['status']}")
            summary_parts.append(f"  Run ID: {job['run_id']}")
            summary_parts.append(f"  Started: {job['started_on']}")
            
            if job['completed_on']:
                summary_parts.append(f"  Completed: {job['completed_on']}")
            
            if job['execution_time']:
                summary_parts.append(f"  Execution Time: {job['execution_time']} seconds")
            
            if job['error_message']:
                summary_parts.append(f"  Error: {job['error_message']}")
        
        return "\n".join(summary_parts)