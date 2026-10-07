"""
RCA Evaluator Agent — Option 6: Evaluator-Optimizer Pattern

Evaluates the quality of an RCA analysis produced by the RCA Agent.
The evaluator is context-aware: it receives the same DAB context and UC
lineage that the RCA agent had, and checks whether the RCA actually USED
that information correctly.

Evaluation criteria (each scored 1-10):

  CLARITY       — Root cause stated in one sentence, not buried in paragraphs.

  ACTIONABILITY — Every fix step must have three components:
                    WHAT  : what to check or do
                    WHERE : exact path / full table name / exact system name
                    ACCESS: how to access it (tool, permission, command)
                  Generic steps like "check the landing zone" score 1-4.
                  Specific steps like "check abfss://raw@.../inventory/daily/
                  using Azure Storage Explorer or az storage fs file list"
                  score 9-10.

  COMPLETENESS  — Covers WHAT failed, WHY, HOW to fix, and DOWNSTREAM IMPACT
                  with exact table names from UC lineage.

The feedback for failed criteria includes exact values pulled from the DAB
context and UC lineage that the RCA agent should have used but didn't.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from models.llm_client import LLMClient


# ── Config ────────────────────────────────────────────────────────────────────

EVAL_THRESHOLD      = float(os.getenv("RCA_EVAL_THRESHOLD", "9.0"))
EVAL_MAX_ITERATIONS = int(os.getenv("RCA_EVAL_MAX_ITERATIONS", "3"))


# ── Structured output schema ──────────────────────────────────────────────────

class RCAEvaluation(BaseModel):
    clarity_score:       float = Field(description="Score 1-10: Is the root cause in one clear sentence?")
    actionability_score: float = Field(description="Score 1-10: Does every fix step have WHAT+WHERE+ACCESS?")
    completeness_score:  float = Field(description="Score 1-10: Covers what/why/how/downstream impact?")
    overall_score:       float = Field(description="Average of the three scores")
    passed:              bool  = Field(description="True if overall_score >= threshold")
    clarity_feedback:       str = Field(description="Specific clarity improvement if score < threshold, else empty")
    actionability_feedback: str = Field(description="Specific actionability improvement with exact values, else empty")
    completeness_feedback:  str = Field(description="Specific completeness improvement with exact values, else empty")
    feedback:               str = Field(description="Combined feedback summary for the RCA agent")


# ── Prompts ───────────────────────────────────────────────────────────────────

_EVAL_SYSTEM = """You are a senior data engineering reviewer evaluating a root cause analysis (RCA) for a failed ETL job.

The RCA agent had access to the DAB context and UC lineage shown below. Your job is to check
whether the RCA actually USED this information correctly — not just whether it sounds good.

Score each criterion 1-10:

──────────────────────────────────────────────────────────────────
1. CLARITY (1-10)
   9-10: Root cause in ONE sentence, unambiguous, leads the response
   7-8:  Clear but slightly verbose or buried
   5-6:  Requires inference to understand the root cause
   1-4:  Vague, missing, or buried in paragraphs

──────────────────────────────────────────────────────────────────
2. ACTIONABILITY (1-10)
   Every fix step MUST have all three:
     WHAT   — what to check or do
     WHERE  — exact full path / full 3-part table name (catalog.schema.table) / exact system name
     ACCESS — how to access it: tool name, permission needed, or exact command

   Examples:
   BAD  (score 1-4): "Check the SFTP landing zone for today's file"
   GOOD (score 9-10): "Check SFTP landing zone /inbound/inventory/daily/ for inventory_2026-10-07.csv
                       using WinSCP or sftp client. Requires SFTP read access (contact infra-ops@company.com)"

   BAD  (score 1-4): "Verify the target table exists"
   GOOD (score 9-10): "Verify table demo_etl.cleansed.inventory_daily exists in Unity Catalog
                       under catalog=demo_etl, schema=cleansed. Check via: SELECT * FROM
                       information_schema.tables WHERE table_schema='cleansed'"

   BAD  (score 1-4): "Contact the upstream team"
   GOOD (score 9-10): "Contact the WMS (Warehouse Management System) team to verify
                       whether the export job scheduled at 01:00 UTC ran successfully on 2026-10-07"

   For each step that is missing WHERE or ACCESS, your feedback must supply the exact
   value from the DAB context or UC lineage provided below.

──────────────────────────────────────────────────────────────────
3. COMPLETENESS (1-10)
   9-10: Covers WHAT failed + WHY it failed + HOW to fix (with all steps) + DOWNSTREAM IMPACT
         with exact table/job names from UC lineage
   7-8:  Missing one of: downstream impact or exact table names
   5-6:  Only covers what and why, no fix steps
   1-4:  Incomplete

──────────────────────────────────────────────────────────────────
FEEDBACK RULES:
- For each criterion below threshold, provide feedback that includes EXACT values
  from the DAB context and UC lineage that were available but not used.
- Do NOT say "add the path" — say "the path is abfss://raw@... (from DAB source_path)"
- Do NOT say "mention downstream tables" — say "downstream table is demo_etl.conformed.fact_inventory_summary (from UC lineage)"

Respond ONLY with valid JSON:
{{
  "clarity_score": <float>,
  "actionability_score": <float>,
  "completeness_score": <float>,
  "overall_score": <float>,
  "passed": <bool>,
  "clarity_feedback": "<exact feedback with values, or empty>",
  "actionability_feedback": "<exact feedback with values from DAB/UC, or empty>",
  "completeness_feedback": "<exact feedback with values from DAB/UC, or empty>",
  "feedback": "<combined one-paragraph summary for the RCA agent>"
}}

Threshold: {threshold}. passed=true only if overall_score >= {threshold}."""

_EVAL_USER = """Job: {job_name}
Error: {error_message}

=== DAB CONTEXT (what was available to RCA agent) ===
{dab_context}

=== UC LINEAGE (what was available to RCA agent) ===
{uc_lineage}

=== RCA TO EVALUATE ===
{rca_analysis}"""


# ── Agent ─────────────────────────────────────────────────────────────────────

class RCAEvaluatorAgent:
    """
    Context-aware RCA evaluator.

    Checks whether the RCA agent used the DAB context and UC lineage correctly.
    Enforces that every actionability step has WHAT + WHERE + ACCESS.
    Feedback includes exact values from DAB/UC that were missed.
    """

    def __init__(self) -> None:
        self.name           = "RCA Evaluator Agent"
        self.threshold      = EVAL_THRESHOLD
        self.max_iterations = EVAL_MAX_ITERATIONS
        self.llm            = LLMClient().get_llm()
        self._prompt        = ChatPromptTemplate.from_messages([
            ("system", _EVAL_SYSTEM),
            ("user",   _EVAL_USER),
        ])

    def _parse_json_response(self, content: str) -> dict:
        """Robustly parse JSON, stripping markdown fences if present."""
        content = content.strip()
        content = re.sub(r'^```(?:json)?\s*', '', content)
        content = re.sub(r'\s*```$', '', content)
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            content = match.group(0)
        return json.loads(content)

    def evaluate(
        self,
        job_name:     str,
        error_message:str,
        rca_analysis: str,
        dab_context:  str = "",
        uc_lineage:   str = "",
    ) -> RCAEvaluation:
        """
        Score an RCA analysis against the available job context.

        Args:
            job_name:      Job name
            error_message: Original error message
            rca_analysis:  The RCA text to evaluate
            dab_context:   DAB context string (what the job is designed to do)
            uc_lineage:    UC lineage string (upstream/downstream tables)

        Returns:
            RCAEvaluation with scores and per-criterion targeted feedback.
        """
        try:
            messages = self._prompt.format_messages(
                threshold=self.threshold,
                job_name=job_name,
                error_message=error_message,
                dab_context=dab_context or "Not available",
                uc_lineage=uc_lineage or "Not available",
                rca_analysis=rca_analysis,
            )
            response = self.llm.invoke(messages)
            content  = response.content if hasattr(response, "content") else str(response)
            raw      = self._parse_json_response(content)
        except Exception as e:
            print(f"[{self.name}] JSON parse error: {e} — using default scores")
            raw = {}

        clarity       = float(raw.get("clarity_score", 5))
        actionability = float(raw.get("actionability_score", 5))
        completeness  = float(raw.get("completeness_score", 5))
        overall       = round((clarity + actionability + completeness) / 3, 2)
        passed        = overall >= self.threshold

        # Build combined targeted feedback
        parts = []
        if not passed:
            if raw.get("clarity_feedback"):
                parts.append(f"CLARITY ({clarity:.0f}/10): {raw['clarity_feedback']}")
            if raw.get("actionability_feedback"):
                parts.append(f"ACTIONABILITY ({actionability:.0f}/10): {raw['actionability_feedback']}")
            if raw.get("completeness_feedback"):
                parts.append(f"COMPLETENESS ({completeness:.0f}/10): {raw['completeness_feedback']}")

        combined_feedback = raw.get("feedback", "") or "\n\n".join(parts)

        return RCAEvaluation(
            clarity_score=clarity,
            actionability_score=actionability,
            completeness_score=completeness,
            overall_score=overall,
            passed=passed,
            clarity_feedback=raw.get("clarity_feedback", ""),
            actionability_feedback=raw.get("actionability_feedback", ""),
            completeness_feedback=raw.get("completeness_feedback", ""),
            feedback=combined_feedback if not passed else "",
        )
