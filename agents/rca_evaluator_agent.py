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
from config import Config


# ── Config ────────────────────────────────────────────────────────────────────

EVAL_THRESHOLD      = float(os.getenv("RCA_EVAL_THRESHOLD", "7.0"))
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

        self.llm = self._build_llm()

        self._prompt = ChatPromptTemplate.from_messages([
            ("system", Config._EVAL_SYSTEM_PROMPT),
            ("user",   Config._EVAL_USER_PROMPT),
        ])

    def _build_llm(self):
        """Build and return the LLM for evaluation, using a dedicated model if RCA_EVAL_MODEL_ID is set."""
        eval_model_id = os.getenv("RCA_EVAL_MODEL_ID", "")
        if eval_model_id and eval_model_id != os.getenv("GROQ_MODEL_ID", ""):
            # Instantiate a separate Groq client for evaluation
            try:
                from langchain_groq import ChatGroq
                llm = ChatGroq(
                    groq_api_key=os.getenv("GROQ_API_KEY", ""),
                    model=eval_model_id,
                    temperature=0.1,
                ).with_retry(
                    retry_if_exception_type=(Exception,),
                    wait_exponential_jitter=True,
                    stop_after_attempt=4,
                )
                print(f"[{self.__class__.__name__}] Using dedicated eval model: {eval_model_id}")
                return llm
            except Exception:
                pass
        return LLMClient().get_llm()

    def _parse_json_response(self, content: str) -> dict:
        """Robustly parse JSON, stripping markdown fences. Falls back to regex extraction on malformed JSON."""
        content = content.strip()
        content = re.sub(r'^```(?:json)?\s*', '', content)
        content = re.sub(r'\s*```$', '', content)
        match = re.search(r'\{.*\}', content, re.DOTALL)
        candidate = match.group(0) if match else content

        # Try clean parse first
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        # Regex fallback — extract individual fields even from malformed JSON
        result: dict = {}
        for field in ("clarity_score", "actionability_score", "completeness_score", "overall_score"):
            m = re.search(rf'"{field}"\s*:\s*([\d.]+)', candidate)
            if m:
                result[field] = float(m.group(1))
        m = re.search(r'"passed"\s*:\s*(true|false)', candidate, re.IGNORECASE)
        if m:
            result["passed"] = m.group(1).lower() == "true"
        for field in ("feedback", "clarity_feedback", "actionability_feedback", "completeness_feedback"):
            m = re.search(rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*?)"', candidate)
            if m:
                result[field] = m.group(1)
        if result:
            return result

        return json.loads(candidate)  # final attempt — will raise if still malformed

    def evaluate(
        self,
        job_name:     str,
        error_message:str,
        rca_analysis: str,
        dab_context:  str = "",
        uc_lineage:   str = "",
    ) -> RCAEvaluation:
        """Score an RCA analysis against the available job context."""
        import time

        for attempt in range(3):
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

                if not content or not content.strip():
                    if os.getenv("MODEL_PROVIDER", "") == "groq":
                        print(f"[{self.name}] Empty response on attempt {attempt + 1} — waiting 10s before retry")
                        time.sleep(10)
                    continue

                raw = self._parse_json_response(content)
                break
            except Exception as e:
                print(f"[{self.name}] Error on attempt {attempt + 1}: {e}")
                if attempt < 2 and os.getenv("MODEL_PROVIDER", "") == "groq":
                    time.sleep(10)
                # Fallback to low scores so the retry loop triggers on parse failure
                raw = {}
        else:
            # Fallback to low scores so the retry loop triggers on parse failure
            raw = {}

        clarity       = float(raw.get("clarity_score", 3))
        actionability = float(raw.get("actionability_score", 3))
        completeness  = float(raw.get("completeness_score", 3))
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
