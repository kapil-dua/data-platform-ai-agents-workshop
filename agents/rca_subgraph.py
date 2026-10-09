"""
RCA Subgraph — isolated RCA + Evaluator loop per job.

Each parallel branch (one per failed job) runs this self-contained subgraph:

    rca_node → eval_node → rca_node (retry) → eval_node → ... → END

Because each Send invokes its own subgraph instance, there is zero shared
state between parallel branches. No rca_eval_pending race conditions.

State is scoped to a single job — the subgraph outputs a single scored
RCA result that fans back into the parent SupervisorState via
_rca_results_reducer.
"""

from __future__ import annotations

import os
import re as _re
import time
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph

from agents.rca_evaluator_agent import EVAL_THRESHOLD, RCAEvaluatorAgent
from config import Config
from tools.dab_context_loader import DABContextLoader
from tools.uc_lineage_fetcher import UCLineageFetcher


# ── Subgraph state ────────────────────────────────────────────────────────────

class RCASubgraphState(TypedDict):
    """State scoped to a single failed job — no cross-branch sharing."""
    # Input: the single job being analysed
    job:              dict[str, Any]
    logs:             str
    dab_text:         str
    uc_text:          str
    uc_ctx:           dict[str, Any]
    # Working state
    rca_result:       dict[str, Any]   # current RCA output
    eval_feedback:    str              # feedback from last evaluation
    iteration:        int
    # Output accumulated across retries
    best_result:      dict[str, Any]
    best_score:       float


# ── Node implementations ──────────────────────────────────────────────────────

def _build_rca_node(rca_agent):
    """Return a subgraph rca node closure bound to the given RCAAgent instance."""

    def rca_node(state: RCASubgraphState) -> dict[str, Any]:
        job      = state["job"]
        feedback = state.get("eval_feedback", "")

        # Inject evaluator feedback for retries
        job_for_rca = {**job}
        if feedback:
            job_for_rca["evaluator_feedback"] = feedback

        # Execute RCA for this single job
        single_state = {"failed_jobs": [job_for_rca]}
        updated      = rca_agent.execute(single_state)
        results      = updated.get("rca_results", [])
        result       = results[0] if results else {}

        return {
            "rca_result":    result,
            "eval_feedback": "",  # clear after use
        }

    return rca_node


def _build_eval_node(evaluator_agent, uc_fetcher):
    """Return a subgraph eval node closure bound to the given evaluator instance."""

    def eval_node(state: RCASubgraphState) -> dict[str, Any]:
        rca       = state.get("rca_result", {})
        iteration = state.get("iteration", 1)

        if not rca:
            return {"best_result": rca, "best_score": 0.0, "iteration": iteration}

        # Throttle for Groq only
        if Config.MODEL_PROVIDER == "groq":
            time.sleep(int(os.getenv("RCA_EVAL_SLEEP_S", "8")))

        # Remove abfss:// references from evaluator context — they don't exist in this workspace
        # and cause the evaluator to hallucinate abfss fix steps
        clean_dab = _re.sub(r'abfss://\S+', '[ADLS path — not applicable in this environment]',
                            state.get("dab_text", ""))
        clean_dab = _re.sub(r'Source table \(for UC lineage only\):.*\n?', '', clean_dab)

        evaluation = evaluator_agent.evaluate(
            job_name=rca.get("job_name", ""),
            error_message=rca.get("error_message", ""),
            rca_analysis=rca.get("root_cause", ""),
            dab_context=clean_dab,
            uc_lineage=state.get("uc_text", ""),
        )

        scored = {
            **rca,
            "eval_score":      evaluation.overall_score,
            "eval_passed":     evaluation.passed,
            "eval_iterations": iteration,  # this iteration number
            "eval_scores_breakdown": {
                "clarity":       evaluation.clarity_score,
                "actionability": evaluation.actionability_score,
                "completeness":  evaluation.completeness_score,
            },
            "_eval_clarity_feedback":      evaluation.clarity_feedback,
            "_eval_actionability_feedback":evaluation.actionability_feedback,
            "_eval_completeness_feedback": evaluation.completeness_feedback,
            "uc_lineage":  state.get("uc_ctx", {}),
        }

        print(
            f"[RCA Evaluator] {rca.get('job_name','?')} "
            f"iter={iteration}/{int(os.getenv('RCA_EVAL_MAX_ITERATIONS', '3'))} "
            f"score={evaluation.overall_score:.1f} "
            f"passed={evaluation.passed}"
        )

        # Track best across iterations
        best_score  = state.get("best_score", 0.0)
        best_result = state.get("best_result", {})
        if evaluation.overall_score > best_score:
            best_score  = evaluation.overall_score
            best_result = scored

        # Build targeted feedback for next iteration
        feedback_parts = []
        if evaluation.clarity_feedback:
            feedback_parts.append(f"CLARITY: {evaluation.clarity_feedback}")
        if evaluation.actionability_feedback:
            feedback_parts.append(f"ACTIONABILITY: {evaluation.actionability_feedback}")
        if evaluation.completeness_feedback:
            feedback_parts.append(f"COMPLETENESS: {evaluation.completeness_feedback}")
        feedback = "\n\n".join(feedback_parts) or evaluation.feedback

        return {
            "rca_result":   scored,
            "best_result":  best_result,
            "best_score":   best_score,
            "eval_feedback": feedback if not evaluation.passed else "",
            "iteration":    iteration + 1,
        }

    return eval_node


def _route_after_eval(state: RCASubgraphState) -> str:
    """Route back to rca if the eval failed and iterations remain; otherwise end the subgraph."""
    rca       = state.get("rca_result", {})
    iteration = state.get("iteration", 1)
    max_iters = int(os.getenv("RCA_EVAL_MAX_ITERATIONS", "3"))

    if rca.get("eval_passed") or iteration > max_iters:
        return "end"
    return "rca"


# ── Subgraph builder ──────────────────────────────────────────────────────────

def build_rca_subgraph(rca_agent, evaluator_agent, uc_fetcher):
    """
    Build and compile the per-job RCA+Evaluator subgraph.

    Graph:
        __start__ → rca → eval → rca (retry) → eval → ... → __end__
    """
    sg = StateGraph(RCASubgraphState)

    sg.add_node("rca",  _build_rca_node(rca_agent))
    sg.add_node("eval", _build_eval_node(evaluator_agent, uc_fetcher))

    sg.set_entry_point("rca")
    sg.add_edge("rca", "eval")
    sg.add_conditional_edges("eval", _route_after_eval, {"rca": "rca", "end": END})

    return sg.compile()


# ── Helper: prepare subgraph initial state from supervisor job entry ──────────

def make_subgraph_input(
    job: dict[str, Any],
    rca_agent,
    uc_fetcher: UCLineageFetcher,
) -> RCASubgraphState:
    """Build the initial state for one subgraph invocation."""
    job_name = job["job_name"]
    run_id   = job.get("run_id")

    # Fetch logs
    try:
        logs = rca_agent.databricks_client.get_job_logs(job_name, run_id)
    except Exception:
        logs = ""

    # DAB context
    dab_loader = DABContextLoader()
    dab_ctx    = dab_loader.get_context(job_name)
    dab_text   = dab_loader.format_for_prompt(dab_ctx)

    # UC lineage
    try:
        uc_ctx  = uc_fetcher.get_lineage_context(job_name=job_name, job_id=job.get("job_id"))
    except Exception:
        uc_ctx  = {}
    uc_text = uc_fetcher.format_for_prompt(uc_ctx)

    return RCASubgraphState(
        job=job,
        logs=logs,
        dab_text=dab_text,
        uc_text=uc_text,
        uc_ctx=uc_ctx,
        rca_result={},
        eval_feedback="",
        iteration=1,
        best_result={},
        best_score=0.0,
    )
