"""
RCA Agent - Performs Root Cause Analysis for failed ETL jobs
"""
from typing import TypedDict
from langchain_core.prompts import ChatPromptTemplate

from tools.databricks_tools import DatabricksJobsClient
from models.llm_client import LLMClient
from utils.langfuse_tracing import get_prompt_and_template
from config import Config


_JOB_LOG_TRUNCATE_CHARS = 3000


class RCAAgentState(TypedDict):
    """State for RCA agent"""
    failed_jobs: list
    rca_results: list


class RCAAgent:
    """Agent responsible for root cause analysis of failed jobs"""

    PROMPT_NAME = "job-failure-rca-analysis"

    def __init__(self):
        """Initialize RCA agent"""
        self.databricks_client = DatabricksJobsClient()
        self.llm_client = LLMClient()
        self.name = "RCA Agent"
        self.description = "Performs root cause analysis on failed Databricks jobs by analyzing run output"

        # Pull the RCA prompt from Langfuse Prompt Management.
        # ``get_prompt_and_template`` returns a LangChain ChatPromptTemplate with
        # ``metadata={"langfuse_prompt": ...}`` so any generation produced through
        # this template is automatically linked to the prompt version in Langfuse.
        self._langfuse_prompt, self._prompt_template = get_prompt_and_template(
            name=self.PROMPT_NAME,
            prompt_type="chat",
            fallback_messages=[
                ("system", Config._FALLBACK_RCA_SYSTEM_PROMPT),
                ("user", Config._FALLBACK_RCA_USER_TEMPLATE),
            ],
        )
        self._chain = self._prompt_template | self.llm_client.get_llm()

    def analyze_failed_jobs(self, state: dict) -> dict:
        """
        Perform RCA on all failed jobs

        Args:
            state: Current agent state containing failed jobs

        Returns:
            Updated state with RCA results
        """
        try:
            failed_jobs = state.get("failed_jobs", [])

            if not failed_jobs:
                print(f"[{self.name}] No failed jobs to analyze.")
                return {
                    **state,
                    "rca_results": []
                }

            print(f"[{self.name}] Analyzing {len(failed_jobs)} failed jobs...")

            rca_results = []

            for job in failed_jobs:
                job_name = job['job_name']
                run_id = job['run_id']

                print(f"[{self.name}] Analyzing {job_name} (Run: {run_id})...")

                try:
                    logs = self.databricks_client.get_job_logs(job_name, run_id)
                    rca = self._perform_rca(job, logs)

                    rca_result = {
                        "job_name": job_name,
                        "run_id": run_id,
                        "error_message": job.get('error_message', 'N/A'),
                        "root_cause": rca['root_cause'],
                        "recommendations": rca['recommendations'],
                        "severity": rca['severity'],
                    }

                    rca_results.append(rca_result)

                except Exception:
                    raise

            print(f"[{self.name}] RCA complete for all failed jobs.")

            return {
                **state,
                "rca_results": rca_results,
            }

        except Exception:
            raise

    def _perform_rca(self, job_info: dict, logs: str) -> dict:
        """
        Perform root cause analysis using the ``job-failure-rca-analysis`` managed prompt.

        Args:
            job_info: Job information dictionary
            logs: Databricks run output and error details

        Returns:
            Dictionary with RCA findings
        """
        variables = {
            "job_name": job_info["job_name"],
            "run_id": job_info["run_id"],
            "status": job_info["status"],
            "error_message": job_info.get("error_message", "N/A"),
            "logs": (logs or "")[:_JOB_LOG_TRUNCATE_CHARS],
        }

        response = self._chain.invoke(variables)

        if hasattr(response, "content"):
            llm_response = response.content
        elif isinstance(response, str):
            llm_response = response
        else:
            llm_response = str(response)

        return {
            "root_cause": llm_response,
            "recommendations": self._extract_recommendations(llm_response),
            "severity": self._determine_severity(job_info, llm_response),
        }

    def _extract_recommendations(self, llm_response: str) -> list:
        """Extract recommendations from LLM response"""
        recommendations = []
        lines = llm_response.split('\n')

        for line in lines:
            if any(keyword in line.lower() for keyword in ['recommend', 'should', 'fix', 'resolve']):
                recommendations.append(line.strip())

        return recommendations[:5] if recommendations else ["Review logs manually for specific details"]

    def _determine_severity(self, job_info: dict, llm_response: str) -> str:
        """Determine severity of the failure"""
        llm_lower = llm_response.lower()

        if any(word in llm_lower for word in ['critical', 'severe', 'corruption', 'blocking']):
            return "Critical"
        elif any(word in llm_lower for word in ['high', 'important', 'data loss']):
            return "High"
        elif any(word in llm_lower for word in ['medium', 'moderate']):
            return "Medium"
        else:
            return "Low"
