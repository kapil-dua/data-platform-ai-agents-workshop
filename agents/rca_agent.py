"""
RCA Agent - Performs Root Cause Analysis for failed ETL jobs
"""
from typing import Any, TypedDict
from langchain_core.prompts import ChatPromptTemplate

from agents.base_agent import AgentResult
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

        self._langfuse_prompt, self._prompt_template = get_prompt_and_template(
            name=self.PROMPT_NAME,
            prompt_type="chat",
            fallback_messages=[
                ("system", Config._FALLBACK_RCA_SYSTEM_PROMPT),
                ("user", Config._FALLBACK_RCA_USER_TEMPLATE),
            ],
        )
        self._chain = self._prompt_template | self.llm_client.get_llm()

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute RCA using the common worker-agent contract."""
        return self.analyze_failed_jobs(state)

    def analyze_failed_jobs(self, state: dict) -> dict:
        """Perform a single RCA generation pass on all failed jobs.
        Results are passed to the rca_evaluator graph node for scoring.
        """
        try:
            failed_jobs = state.get("failed_jobs", [])

            if not failed_jobs:
                print(f"[{self.name}] No failed jobs to analyze.")
                return {
                    "rca_results": [],
                    "execution_log": [f"{self.name}: no failed jobs to analyze"],
                    "agent_results": [
                        AgentResult(
                            agent=self.name,
                            status="completed",
                            message="No failed jobs to analyze",
                            data={"rca_count": 0},
                        ),
                    ],
                }

            print(f"[{self.name}] Generating RCA for {len(failed_jobs)} failed job(s)...")

            rca_results = []
            for job in failed_jobs:
                job_name = job["job_name"]
                run_id   = job["run_id"]
                print(f"[{self.name}] Analysing {job_name} (Run: {run_id})...")
                logs = self.databricks_client.get_job_logs(job_name, run_id)
                rca  = self._perform_rca(job, logs)
                rca_results.append({
                    "job_name":        job_name,
                    "run_id":          run_id,
                    "error_message":   job.get("error_message", "N/A"),
                    "root_cause":      rca["root_cause"],
                    "recommendations": rca["recommendations"],
                    "severity":        rca["severity"],
                    # Evaluator metadata — populated by rca_evaluator node
                    "eval_score":             None,
                    "eval_iterations":        1,
                    "eval_passed":            None,
                    "eval_scores_breakdown":  None,
                    # Carry forward any feedback injected for retries
                    "evaluator_feedback":     job.get("evaluator_feedback", ""),
                })

            print(f"[{self.name}] RCA generation complete — passing to evaluator.")
            return {
                "rca_results": rca_results,
                "execution_log": [f"{self.name}: generated {len(rca_results)} RCA result(s)"],
                "agent_results": [
                    AgentResult(
                        agent=self.name,
                        status="completed",
                        message=f"Generated {len(rca_results)} RCA result(s)",
                        data={"rca_count": len(rca_results)},
                    ),
                ],
            }

        except Exception:
            raise

    def _perform_rca(self, job_info: dict, logs: str) -> dict:
        """Single RCA generation pass — called by the evaluator loop."""
        # Include evaluator feedback in prompt if present
        feedback_note = ""
        if job_info.get("evaluator_feedback"):
            feedback_note = f"\n\nIMPORTANT — Evaluator feedback from previous attempt:\n{job_info['evaluator_feedback']}"

        variables = {
            "job_name":      job_info["job_name"],
            "run_id":        job_info["run_id"],
            "status":        job_info.get("status", "FAILED"),
            "error_message": job_info.get("error_message", "N/A") + feedback_note,
            "logs":          (logs or "")[:_JOB_LOG_TRUNCATE_CHARS],
        }

        response = self._chain.invoke(variables)
        llm_response = response.content if hasattr(response, "content") else str(response)

        return {
            "root_cause":      llm_response,
            "recommendations": self._extract_recommendations(llm_response),
            "severity":        self._determine_severity(job_info, llm_response),
        }

    def _extract_recommendations(self, llm_response: str) -> list:
        """Extract recommendations from LLM response"""
        recommendations = []
        for line in llm_response.split("\n"):
            if any(kw in line.lower() for kw in ["recommend", "should", "fix", "resolve"]):
                recommendations.append(line.strip())
        return recommendations[:5] if recommendations else ["Review logs manually for specific details"]

    def _determine_severity(self, job_info: dict, llm_response: str) -> str:
        """Determine severity of the failure"""
        llm_lower = llm_response.lower()
        if any(w in llm_lower for w in ["critical", "severe", "corruption", "blocking"]):
            return "Critical"
        elif any(w in llm_lower for w in ["high", "important", "data loss"]):
            return "High"
        elif any(w in llm_lower for w in ["medium", "moderate"]):
            return "Medium"
        return "Low"
