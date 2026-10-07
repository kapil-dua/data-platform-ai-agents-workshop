"""
RCA Agent - Performs Root Cause Analysis for failed ETL jobs

Enhanced with:
  - DAB context (job design intent: source/target paths, upstream system, SLA)
  - Unity Catalog lineage (runtime history: tables read/written, downstream consumers)

The LLM receives not just the error log, but the full picture of what the
job was supposed to do and who depends on its output.
"""
from typing import Any, TypedDict
from langchain_core.prompts import ChatPromptTemplate

from agents.base_agent import AgentResult
from tools.databricks_tools import DatabricksJobsClient
from tools.dab_context_loader import DABContextLoader
from tools.uc_lineage_fetcher import UCLineageFetcher
from models.llm_client import LLMClient
from utils.langfuse_tracing import get_prompt_and_template
from config import Config


_JOB_LOG_TRUNCATE_CHARS = 3000

# ── Fallback system prompt (used when Langfuse is unavailable) ────────────────
_FALLBACK_SYSTEM = """You are an expert data engineer performing root cause analysis on failed ETL jobs.

You will be given:
1. Job error logs and stack trace
2. Job context from the DAB (Databricks Asset Bundle) — what the job is designed to do
3. Unity Catalog lineage — what tables the job reads/writes and who depends on its output

CRITICAL RULE: Every path, table name, filename, system name, timestamp, and config value
you mention in your response MUST be copied exactly from the context provided above.
Never say "check the landing zone" — say "check abfss://raw@datalake.dfs.core.windows.net/inventory/daily/".
Never say "the upstream system" — say "the WMS (Warehouse Management System)".
Never say "the expected file" — say "inventory_2026-10-07.csv".
If a value is in the context, use it. If it is not in the context, say it is unknown.

Your analysis must include:

1. ROOT CAUSE — specific explanation referencing the exact error, the job's design intent,
   and the mismatch between what was expected and what was found.
   Quote exact values from the DAB context and error logs.

2. DOWNSTREAM IMPACT — which exact downstream tables or consumers will be affected.
   Reference exact table names and job names from the UC lineage data.

3. RECOMMENDED FIX — numbered, specific steps with exact paths, commands, and contact points.
   Example of good step: "Check SFTP landing zone /inbound/inventory/daily/ for inventory_2026-10-07.csv"
   Example of bad step:  "Check the SFTP landing zone for today's file"

4. SEVERITY — Critical / High / Medium / Low with a one-line justification referencing
   the number of downstream consumers affected.

Be concise but specific. Every actionable step must include exact values."""

_FALLBACK_USER = """\
Job Name: {job_name}
Run ID: {run_id}
Status: {status}
Error Message: {error_message}

=== JOB DESIGN CONTEXT (from DAB) ===
{dab_context}

=== RUNTIME LINEAGE CONTEXT (Unity Catalog) ===
{uc_lineage}

=== JOB LOGS ===
{logs}"""


class RCAAgentState(TypedDict):
    """State for RCA agent"""
    failed_jobs: list
    rca_results: list


class RCAAgent:
    """Agent responsible for root cause analysis of failed jobs.

    Enriches each analysis with:
    - DAB context: source/target paths, upstream system, filename patterns, SLA
    - UC lineage: tables read/written, last successful write, downstream consumers
    """

    PROMPT_NAME = "job-failure-rca-analysis"

    def __init__(self):
        self.databricks_client = DatabricksJobsClient()
        self.llm_client        = LLMClient()
        self.dab_loader        = DABContextLoader()
        self.uc_fetcher        = UCLineageFetcher(self.databricks_client.workspace_client)
        self.name              = "RCA Agent"
        self.description       = (
            "Performs root cause analysis on failed Databricks jobs using "
            "error logs, DAB job context, and Unity Catalog lineage."
        )

        self._langfuse_prompt, self._prompt_template = get_prompt_and_template(
            name=self.PROMPT_NAME,
            prompt_type="chat",
            fallback_messages=[
                ("system", _FALLBACK_SYSTEM),
                ("user",   _FALLBACK_USER),
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
                job_id   = job.get("job_id")
                run_id   = job["run_id"]
                print(f"[{self.name}] Analysing {job_name} (Run: {run_id})...")

                # Get error logs
                logs = self.databricks_client.get_job_logs(job_name, run_id)

                # Get DAB context (job design intent)
                dab_ctx = self.dab_loader.get_context(job_name)
                dab_text = self.dab_loader.format_for_prompt(dab_ctx)
                print(f"[{self.name}]   DAB context: {'found' if dab_ctx else 'not found'}")

                # Get UC lineage (runtime history + downstream impact)
                uc_ctx  = self.uc_fetcher.get_lineage_context(
                    job_name=job_name,
                    job_id=job_id,
                )
                uc_text = self.uc_fetcher.format_for_prompt(uc_ctx)
                print(
                    f"[{self.name}]   UC lineage : "
                    f"{'found (' + str(len(uc_ctx.get('tables_written',[]))) + ' writes, ' + str(len(uc_ctx.get('downstream_consumers',[]))) + ' downstream)' if uc_ctx.get('lineage_available') else 'not found'}"
                )

                rca = self._perform_rca(job, logs, dab_text, uc_text)

                rca_results.append({
                    "job_name":        job_name,
                    "run_id":          run_id,
                    "error_message":   job.get("error_message", "N/A"),
                    "root_cause":      rca["root_cause"],
                    "recommendations": rca["recommendations"],
                    "severity":        rca["severity"],
                    "dab_context":     dab_ctx,
                    "uc_lineage":      uc_ctx,
                    # Evaluator metadata — populated by rca_evaluator node
                    "eval_score":            None,
                    "eval_iterations":       1,
                    "eval_passed":           None,
                    "eval_scores_breakdown": None,
                    "evaluator_feedback":    job.get("evaluator_feedback", ""),
                })

            print(f"[{self.name}] RCA generation complete — passing to evaluator.")
            return {
                "rca_results":  rca_results,
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

    def _perform_rca(
        self,
        job_info: dict,
        logs: str,
        dab_context: str,
        uc_lineage: str,
    ) -> dict:
        """Single RCA generation pass with enriched context."""
        feedback_note = ""
        if job_info.get("evaluator_feedback"):
            feedback_note = (
                f"\n\nEVALUATOR FEEDBACK (improve based on this):\n"
                f"{job_info['evaluator_feedback']}"
            )

        variables = {
            "job_name":      job_info["job_name"],
            "run_id":        job_info["run_id"],
            "status":        job_info.get("status", "FAILED"),
            "error_message": job_info.get("error_message", "N/A") + feedback_note,
            "dab_context":   dab_context,
            "uc_lineage":    uc_lineage,
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
        """Extract recommendation lines from LLM response."""
        recommendations = []
        for line in llm_response.split("\n"):
            stripped = line.strip()
            if stripped and any(
                kw in stripped.lower()
                for kw in ["recommend", "should", "fix", "resolve", "check", "update", "contact"]
            ):
                recommendations.append(stripped)
        return recommendations[:5] if recommendations else ["Review logs and DAB config for specific details"]

    def _determine_severity(self, job_info: dict, llm_response: str) -> str:
        """Determine severity, boosting if downstream consumers are affected."""
        llm_lower = llm_response.lower()

        # Check if UC lineage shows downstream impact
        uc_ctx = job_info.get("uc_lineage", {})
        has_downstream = bool(uc_ctx.get("downstream_consumers"))

        if any(w in llm_lower for w in ["critical", "severe", "corruption", "blocking"]):
            return "Critical"
        elif any(w in llm_lower for w in ["high", "important", "data loss"]):
            return "High"
        elif has_downstream:
            # If downstream consumers exist, escalate to High even if LLM says Medium
            return "High"
        elif any(w in llm_lower for w in ["medium", "moderate"]):
            return "Medium"
        return "Low"
