"""
RCA Evaluator Agent — Option 6: Evaluator-Optimizer Pattern

Evaluates the quality of an RCA analysis produced by the RCA Agent and
returns a structured score with feedback. If the score is below the
threshold, the feedback is sent back to the RCA Agent for a retry.

Evaluation criteria (each scored 1-10):
  - Clarity       : Is the root cause clearly and concisely stated?
  - Actionability : Are the recommendations specific and immediately actionable?
  - Completeness  : Does the analysis cover what failed, why, and how to fix it?

Overall score = average of the three criteria.
Threshold     : 7.0  (configurable via RCA_EVAL_THRESHOLD env var)
Max iterations: 3    (configurable via RCA_EVAL_MAX_ITERATIONS env var)
"""

from __future__ import annotations

import os
from typing import Any

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from models.llm_client import LLMClient


# ── Config ────────────────────────────────────────────────────────────────────

EVAL_THRESHOLD      = float(os.getenv("RCA_EVAL_THRESHOLD", "7.0"))
EVAL_MAX_ITERATIONS = int(os.getenv("RCA_EVAL_MAX_ITERATIONS", "3"))


# ── Structured output schema ──────────────────────────────────────────────────

class RCAEvaluation(BaseModel):
    clarity_score:       float = Field(description="Score 1-10: Is the root cause clearly stated?")
    actionability_score: float = Field(description="Score 1-10: Are recommendations specific and actionable?")
    completeness_score:  float = Field(description="Score 1-10: Does it cover what/why/how to fix?")
    overall_score:       float = Field(description="Average of the three scores")
    passed:              bool  = Field(description="True if overall_score >= threshold")
    feedback:            str   = Field(description="Specific improvement feedback if not passed, else empty string")


# ── Prompts ───────────────────────────────────────────────────────────────────

_EVAL_SYSTEM = """You are a senior data engineering reviewer evaluating the quality of a root cause analysis (RCA) report for a failed ETL job.

Score the RCA on three criteria (each 1-10):

1. CLARITY (1-10)
   - 9-10: Root cause is stated in one clear sentence, unambiguous
   - 7-8:  Root cause is clear but slightly verbose
   - 5-6:  Root cause requires inference, not directly stated
   - 1-4:  Root cause is vague, missing, or buried in noise

2. ACTIONABILITY (1-10)
   - 9-10: Recommendations are specific, include exact steps or config changes
   - 7-8:  Recommendations are clear but lack specificity on how to implement
   - 5-6:  Recommendations are generic (e.g. "review logs")
   - 1-4:  No actionable recommendations

3. COMPLETENESS (1-10)
   - 9-10: Covers WHAT failed, WHY it failed, and HOW to fix it
   - 7-8:  Covers what and why but how-to-fix is partial
   - 5-6:  Only covers what failed
   - 1-4:  Incomplete or missing key sections

Respond ONLY with valid JSON matching this schema:
{{
  "clarity_score": <float>,
  "actionability_score": <float>,
  "completeness_score": <float>,
  "overall_score": <float>,
  "passed": <bool>,
  "feedback": "<specific improvement instructions if not passed, else empty string>"
}}

The threshold for passing is {threshold}. Set passed=true only if overall_score >= {threshold}."""

_EVAL_USER = """Job: {job_name}
Error: {error_message}

RCA Analysis to evaluate:
{rca_analysis}"""


# ── Agent ─────────────────────────────────────────────────────────────────────

class RCAEvaluatorAgent:
    """Evaluates RCA quality and drives the evaluate-refine loop."""

    def __init__(self) -> None:
        self.name = "RCA Evaluator Agent"
        self.threshold = EVAL_THRESHOLD
        self.max_iterations = EVAL_MAX_ITERATIONS
        self.llm = LLMClient().get_llm()
        self._chain = (
            ChatPromptTemplate.from_messages([
                ("system", _EVAL_SYSTEM),
                ("user", _EVAL_USER),
            ])
            | self.llm
            | JsonOutputParser()
        )

    def evaluate(self, job_name: str, error_message: str, rca_analysis: str) -> RCAEvaluation:
        """Score a single RCA analysis. Returns a structured evaluation."""
        raw = self._chain.invoke({
            "threshold": self.threshold,
            "job_name": job_name,
            "error_message": error_message,
            "rca_analysis": rca_analysis,
        })

        overall = round(
            (raw.get("clarity_score", 0) +
             raw.get("actionability_score", 0) +
             raw.get("completeness_score", 0)) / 3,
            2,
        )
        passed = overall >= self.threshold

        return RCAEvaluation(
            clarity_score=raw.get("clarity_score", 0),
            actionability_score=raw.get("actionability_score", 0),
            completeness_score=raw.get("completeness_score", 0),
            overall_score=overall,
            passed=passed,
            feedback=raw.get("feedback", "") if not passed else "",
        )

    def evaluate_and_refine(
        self,
        job_info: dict[str, Any],
        rca_fn,
        logs: str,
    ) -> dict[str, Any]:
        """
        Run the evaluate-refine loop for a single job.

        Args:
            job_info : Job metadata dict (job_name, run_id, error_message, …)
            rca_fn   : Callable(job_info, logs) -> dict with 'root_cause' key
            logs     : Raw job logs string

        Returns:
            Enriched RCA result dict with evaluation metadata:
              eval_score, eval_iterations, eval_passed, eval_scores_breakdown
        """
        job_name      = job_info.get("job_name", "unknown")
        error_message = job_info.get("error_message", "")
        feedback      = ""
        best_result   = None
        best_score    = 0.0

        for iteration in range(1, self.max_iterations + 1):
            print(f"  [{self.name}] {job_name} — iteration {iteration}/{self.max_iterations}")

            # Inject evaluator feedback into job_info for the RCA agent
            job_info_with_feedback = {**job_info}
            if feedback:
                job_info_with_feedback["evaluator_feedback"] = (
                    f"Previous RCA scored below {self.threshold}. "
                    f"Improve based on this feedback: {feedback}"
                )

            rca_result = rca_fn(job_info_with_feedback, logs)
            evaluation = self.evaluate(
                job_name=job_name,
                error_message=error_message,
                rca_analysis=rca_result.get("root_cause", ""),
            )

            print(
                f"  [{self.name}] score={evaluation.overall_score} "
                f"(clarity={evaluation.clarity_score}, "
                f"actionability={evaluation.actionability_score}, "
                f"completeness={evaluation.completeness_score}) "
                f"passed={evaluation.passed}"
            )

            # Track best result across iterations
            if evaluation.overall_score > best_score:
                best_score  = evaluation.overall_score
                best_result = {
                    **rca_result,
                    "eval_score":      evaluation.overall_score,
                    "eval_iterations": iteration,
                    "eval_passed":     evaluation.passed,
                    "eval_scores_breakdown": {
                        "clarity":       evaluation.clarity_score,
                        "actionability": evaluation.actionability_score,
                        "completeness":  evaluation.completeness_score,
                    },
                }

            if evaluation.passed:
                print(f"  [{self.name}] ✅ Passed threshold {self.threshold} on iteration {iteration}")
                break

            feedback = evaluation.feedback
            print(f"  [{self.name}] ⚠️  Below threshold — feedback: {feedback[:120]}")

        return best_result
