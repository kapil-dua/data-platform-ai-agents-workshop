"""
RCA Agent - Performs Root Cause Analysis for failed ETL jobs
"""
from typing import TypedDict
from utils.aws_utils import AWSGlueClient
from utils.llm_utils import LLMClient


class RCAAgentState(TypedDict):
    """State for RCA agent"""
    failed_jobs: list
    rca_results: list


class RCAAgent:
    """Agent responsible for root cause analysis of failed jobs"""
    
    def __init__(self):
        """Initialize RCA agent"""
        self.aws_client = AWSGlueClient()
        self.llm_client = LLMClient()
        self.name = "RCA Agent"
        self.description = "Performs root cause analysis on failed ETL jobs by analyzing logs"
    
    def analyze_failed_jobs(self, state: dict) -> dict:
        """
        Perform RCA on all failed jobs
        
        Args:
            state: Current agent state containing failed jobs
            
        Returns:
            Updated state with RCA results
        """
        failed_jobs = state.get("failed_jobs", [])
        
        if not failed_jobs:
            print(f"[{self.name}] No failed jobs to analyze.")
            return {
                **state,
                "rca_results": [],
                "rca_summary": "No failed jobs found. All jobs are running successfully!"
            }
        
        print(f"[{self.name}] Analyzing {len(failed_jobs)} failed jobs...")
        
        rca_results = []
        
        for job in failed_jobs:
            job_name = job['job_name']
            run_id = job['run_id']
            
            print(f"[{self.name}] Analyzing {job_name} (Run: {run_id})...")
            
            # Get job logs
            logs = self.aws_client.get_job_logs(job_name, run_id)
            
            # Perform RCA using LLM
            rca = self._perform_rca(job, logs)
            
            rca_results.append({
                "job_name": job_name,
                "run_id": run_id,
                "error_message": job.get('error_message', 'N/A'),
                "root_cause": rca['root_cause'],
                "recommendations": rca['recommendations'],
                "severity": rca['severity']
            })
        
        # Create overall RCA summary
        rca_summary = self._create_rca_summary(rca_results)
        
        print(f"[{self.name}] RCA complete for all failed jobs.")
        
        return {
            **state,
            "rca_results": rca_results,
            "rca_summary": rca_summary
        }
    
    def _perform_rca(self, job_info: dict, logs: str) -> dict:
        """
        Perform root cause analysis using LLM
        
        Args:
            job_info: Job information dictionary
            logs: Job logs from CloudWatch
            
        Returns:
            Dictionary with RCA findings
        """
        system_prompt = """You are an expert data engineer performing root cause analysis on failed ETL jobs.
        Analyze the job information and logs to determine:
        1. The root cause of the failure
        2. Specific recommendations to fix the issue
        3. Severity level (Critical, High, Medium, Low)
        
        Provide your analysis in a structured format with clear, actionable insights."""
        
        user_message = f"""
        Job Name: {job_info['job_name']}
        Run ID: {job_info['run_id']}
        Status: {job_info['status']}
        Error Message: {job_info.get('error_message', 'N/A')}
        
        Job Logs:
        {logs[:3000]}  # Limit log size for LLM
        
        Provide root cause analysis with recommendations.
        """
        
        llm_response = self.llm_client.invoke_with_prompt(
            system_message=system_prompt,
            user_message=user_message
        )
        
        # Parse LLM response (you can make this more sophisticated)
        return {
            "root_cause": llm_response,
            "recommendations": self._extract_recommendations(llm_response),
            "severity": self._determine_severity(job_info, llm_response)
        }
    
    def _extract_recommendations(self, llm_response: str) -> list:
        """Extract recommendations from LLM response"""
        # Simple extraction - can be enhanced with structured output
        recommendations = []
        lines = llm_response.split('\n')
        
        for line in lines:
            if any(keyword in line.lower() for keyword in ['recommend', 'should', 'fix', 'resolve']):
                recommendations.append(line.strip())
        
        return recommendations[:5] if recommendations else ["Review logs manually for specific details"]
    
    def _determine_severity(self, job_info: dict, llm_response: str) -> str:
        """Determine severity of the failure"""
        llm_lower = llm_response.lower()
        
        if any(word in llm_lower for word in ['critical', 'severe', 'data loss', 'corruption']):
            return "Critical"
        elif any(word in llm_lower for word in ['high', 'important', 'blocking']):
            return "High"
        elif any(word in llm_lower for word in ['medium', 'moderate']):
            return "Medium"
        else:
            return "Low"
    
    def _create_rca_summary(self, rca_results: list) -> str:
        """Create an overall summary of all RCA findings"""
        system_prompt = """You are summarizing multiple root cause analyses for failed ETL jobs.
        Create a concise executive summary that highlights:
        - Total number of failures analyzed
        - Common patterns or root causes
        - Priority recommendations
        - Overall system health assessment"""
        
        user_message = f"Summarize these RCA findings:\n\n{str(rca_results)}"
        
        summary = self.llm_client.invoke_with_prompt(
            system_message=system_prompt,
            user_message=user_message
        )
        
        return summary