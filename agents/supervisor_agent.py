"""Supervisor Agent - Coordinates specialized worker agents via a ReAct LangGraph workflow.

Architecture patterns demonstrated:
  - Option 2: ReAct Supervisor — LLM reasons about state and decides next agent
  - Option 3: Shared Memory   — Annotated reducers, nodes return only their contribution
  - Option 6: Evaluator loop  — rca_evaluator is a separate graph node that loops back to rca
"""
import json
import operator
import os
import sqlite3
from typing import Annotated, Any, Literal, TypedDict


def _replace_reducer(current: list, update: list) -> list:
    """Reducer that replaces the current value entirely.
    Used for rca_eval_pending where the evaluator needs to clear
    the list and set only the retry items, not append to old ones.
    """
    return update


def _rca_results_reducer(current: list, update: list) -> list:
    """Smart reducer for rca_results.

    - During parallel fan-in: each rca node returns 1 item → append (operator.add behaviour)
    - When evaluator writes scored results: items have eval_score set → replace existing
      entries for the same job rather than duplicating them.
    """
    if not update:
        return current

    # If update contains scored results (eval_score present), replace matching jobs
    if any(r.get("eval_score") is not None for r in update):
        updated_run_ids = {str(r.get("run_id")) for r in update}
        kept   = [r for r in current if str(r.get("run_id")) not in updated_run_ids]
        return kept + update

    # Otherwise plain append (parallel fan-in)
    return current + update

from langchain_core.messages import HumanMessage, SystemMessage

from agents.base_agent import AgentResult
from agents.incident_agent import IncidentAgent
from agents.monitor_agent import MonitorAgent
from agents.rca_agent import RCAAgent
from agents.rca_evaluator_agent import RCAEvaluatorAgent, EVAL_THRESHOLD
from config import Config
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, Send, interrupt
from utils.durable_memory import WorkflowStore
from utils.langfuse_tracing import generate_session_id, get_agent_handler


# ── Shared state ──────────────────────────────────────────────────────────────

class SupervisorState(TypedDict):
    """Shared state passed between the supervisor and worker agents.

    List fields use Annotated[list, operator.add] so LangGraph automatically
    merges contributions from each node by appending — no manual concat needed.
    This is the correct pattern for shared memory in multi-agent graphs and is
    required for parallel fan-out to work correctly.
    """
    # Scalar fields (last-write-wins)
    task:             str
    workflow_run_id:  str
    jobs_data:        dict[str, Any]
    monitor_summary:  str
    next_agent:       str
    workflow_status:  str
    error:            str
    # Evaluator loop control — replace reducer so evaluator can clear-and-reset
    rca_eval_pending: Annotated[list[dict[str, Any]], _replace_reducer]
    rca_eval_done:    Annotated[list[dict[str, Any]], _replace_reducer]

    # List fields — auto-appended by each node via operator.add
    failed_jobs:      Annotated[list[dict[str, Any]], operator.add]
    rca_results:      Annotated[list[dict[str, Any]], _rca_results_reducer]  # smart: append on fan-in, replace on eval
    incident_results: Annotated[list[dict[str, Any]], operator.add]
    agent_results:    Annotated[list[AgentResult],    operator.add]
    execution_log:    Annotated[list[str],            operator.add]


# ── ReAct supervisor system prompt ────────────────────────────────────────────

_REACT_SYSTEM = """You are a data-platform triage supervisor orchestrating specialized agents.

Available tools:
  - run_monitor   : Fetch Databricks ETL job statuses. Always call this first.
  - run_rca       : Analyse failed jobs for root cause. Call when monitor finds failures.
  - run_incident  : Create incident tickets. Call only when task requires it AND rca_results exist.

Rules:
  - Think step by step before deciding.
  - After run_monitor: no failures → DONE. Failures + task requires analysis → run_rca.
  - After run_rca: task requires incidents AND results exist → run_incident. Otherwise → DONE.
  - Never call run_incident if rca_results is empty.
  - When finished, respond with exactly: DONE

Current task: {task}
"""


class SupervisorAgent:
    """Coordinate specialized agents through a ReAct + Evaluator-loop LangGraph workflow."""

    def __init__(self):
        self.name            = "Supervisor Agent"
        self.description     = "ReAct supervisor with evaluator-optimizer loop for RCA quality"
        self.monitor_agent   = MonitorAgent()
        self.rca_agent       = RCAAgent()
        self.evaluator_agent = RCAEvaluatorAgent()
        self.incident_agent  = IncidentAgent()
        self.workflow_store  = WorkflowStore()
        self._last_fan_out_degree = 0  # captured for diagram label
        self._last_execution_log  = []  # captured for retry detection in diagram
        self.checkpointer    = self._build_checkpointer()
        self.workflow        = self._build_workflow()
        print(self.workflow.get_graph().draw_mermaid())

    # ── Setup ─────────────────────────────────────────────────────────────────

    def _build_checkpointer(self):
        if SqliteSaver is None:
            return None
        data_dir = os.path.join(os.getcwd(), ".sqlite")
        os.makedirs(data_dir, exist_ok=True)
        conn = sqlite3.connect(
            os.path.join(data_dir, "langgraph_checkpoints.db"),
            check_same_thread=False,
        )
        return SqliteSaver(conn)

    def _build_workflow(self) -> StateGraph:
        """
        Linear topology with parallel RCA fan-out:

            start → supervisor → monitor → rca_fan_out ──┬→ rca (job 1) ─┐
                                                          ├→ rca (job 2) ─┤→ rca_evaluator → incident → end
                                                          └→ rca (job N) ─┘

        rca_fan_out uses LangGraph Send API to dispatch one rca node
        execution per failed job in parallel. Results fan back in via
        Annotated[list, operator.add] reducer on rca_results.
        """
        workflow = StateGraph(SupervisorState)

        workflow.add_node("supervisor",    self._react_supervisor_node)
        workflow.add_node("monitor",       self._monitor_node)
        workflow.add_node("rca_fan_out",   self._rca_fan_out_node)
        workflow.add_node("rca",           self._rca_node)
        workflow.add_node("rca_evaluator", self._rca_evaluator_node)
        workflow.add_node("incident",      self._incident_node)

        workflow.set_entry_point("supervisor")

        workflow.add_conditional_edges(
            "supervisor", self._route_from_supervisor,
            {"monitor": "monitor", "rca_fan_out": "rca_fan_out", "incident": "incident", "end": END},
        )

        workflow.add_conditional_edges(
            "monitor", self._route_after_monitor,
            {"rca_fan_out": "rca_fan_out", "end": END},
        )

        # Fan-out: returns Send objects — one per failed job
        workflow.add_conditional_edges("rca_fan_out", self._fan_out_rca)

        # Each parallel rca execution feeds into rca_evaluator
        workflow.add_edge("rca", "rca_evaluator")

        workflow.add_conditional_edges(
            "rca_evaluator", self._route_after_evaluator,
            {"rca": "rca", "incident": "incident", "end": END},
        )

        workflow.add_edge("incident", END)

        if self.checkpointer is not None:
            return workflow.compile(checkpointer=self.checkpointer)
        return workflow.compile()

    # ── ReAct supervisor node ─────────────────────────────────────────────────

    def _react_supervisor_node(self, state: SupervisorState) -> dict[str, Any]:
        """LLM reasons about current workflow state and decides the next step."""
        from models.llm_client import LLMClient

        task           = state.get("task", "monitor_and_analyze")
        failed_count   = len(state.get("failed_jobs", []))
        rca_count      = len(state.get("rca_results", []))
        incident_count = len(state.get("incident_results", []))

        context = (
            f"Current state:\n"
            f"  - Jobs monitored : {'yes' if state.get('jobs_data') else 'not yet'}\n"
            f"  - Failed jobs    : {failed_count}\n"
            f"  - RCA completed  : {rca_count}\n"
            f"  - Incidents      : {incident_count}\n"
        )

        messages = [
            SystemMessage(content=_REACT_SYSTEM.format(task=task)),
            HumanMessage(content=context + "\nWhat should be done next?"),
        ]

        llm       = LLMClient().get_llm()
        response  = llm.invoke(messages)
        reasoning = response.content if hasattr(response, "content") else str(response)
        rl        = reasoning.lower()

        # Parse decision — order matters (most specific first)
        if "done" in rl and "run_" not in rl:
            next_action = "end"
        elif "run_incident" in rl or ("incident" in rl and rca_count > 0):
            next_action = "incident"
        elif "run_rca" in rl or ("rca" in rl and failed_count > 0 and rca_count == 0):
            next_action = "rca"
        elif "run_monitor" in rl or not state.get("jobs_data"):
            next_action = "monitor"
        else:
            next_action = "end"

        return {
            "next_agent":      next_action,
            "workflow_status": "running" if next_action != "end" else "completed",
            "execution_log": [
                f"Supervisor [ReAct]: {reasoning[:300]}{'...' if len(reasoning) > 300 else ''}",
                f"Supervisor [ReAct]: → {next_action}",
            ],
        }

    def _route_from_supervisor(
        self, state: SupervisorState,
    ) -> Literal["monitor", "rca_fan_out", "incident", "end"]:
        next_agent = state.get("next_agent", "end")
        if next_agent == "rca":
            next_agent = "rca_fan_out"
        return next_agent if next_agent in {"monitor", "rca_fan_out", "incident"} else "end"

    # ── Worker nodes ──────────────────────────────────────────────────────────

    def _monitor_node(self, state: SupervisorState) -> dict[str, Any]:
        updated = self.monitor_agent.execute(state)
        try:
            run_id = state.get("workflow_run_id")
            if run_id:
                self.workflow_store.record_event(
                    run_id, self.monitor_agent.name, "completed",
                    {"failed_jobs": len(updated.get("failed_jobs", []))},
                )
        except Exception:
            pass
        return {
            "jobs_data":       updated.get("jobs_data", {}),
            "failed_jobs":     updated.get("failed_jobs", []),
            "monitor_summary": updated.get("monitor_summary", ""),
            "agent_results":   updated.get("agent_results", []),
            "execution_log":   [
                *updated.get("execution_log", []),
                "Supervisor: Monitor Agent completed",
            ],
        }

    def _rca_node(self, state: SupervisorState) -> dict[str, Any]:
        """Run RCA on a single job — called N times in parallel via Send API.
        Results fan back in via rca_results (Annotated operator.add reducer).
        """
        updated     = self.rca_agent.execute(state)
        new_results = updated.get("rca_results", [])
        return {
            # Fan-in via operator.add — all parallel nodes append here
            "rca_results":      new_results,
            # Clear pending so evaluator starts fresh each cycle
            "rca_eval_pending": [],
            "rca_eval_done":    [],
            "agent_results":    updated.get("agent_results", []),
            "execution_log":    [
                *updated.get("execution_log", []),
                f"Supervisor: RCA Agent completed — {len(new_results)} result(s) ready for evaluation",
            ],
        }

    def _rca_evaluator_node(self, state: SupervisorState) -> dict[str, Any]:
        """
        Evaluator-Optimizer node (Option 6).

        On first pass: reads all results from rca_results (fan-in from parallel rca nodes).
        On retry pass: reads from rca_eval_pending (only the ones that need retry).
        Results that pass are kept in rca_results. Failed results go to rca_eval_pending for retry.
        """
        # On retry, evaluate only pending items; on first pass, evaluate all rca_results
        pending_retry = state.get("rca_eval_pending", [])
        to_evaluate   = pending_retry if pending_retry else state.get("rca_results", [])

        passed = []
        failed = []
        log    = []

        for rca in to_evaluate:
            score = rca.get("eval_score")
            if score is None:
                # Extract DAB context and UC lineage stored on the RCA result
                # so the evaluator can check whether they were actually used
                from tools.dab_context_loader import DABContextLoader
                from tools.uc_lineage_fetcher import UCLineageFetcher
                dab_loader = DABContextLoader()
                dab_ctx    = dab_loader.get_context(rca.get("job_name", ""))
                dab_text   = dab_loader.format_for_prompt(dab_ctx)
                uc_ctx     = rca.get("uc_lineage", {})
                uc_text    = UCLineageFetcher(
                    self.monitor_agent.databricks_client.workspace_client
                ).format_for_prompt(uc_ctx)

                evaluation = self.evaluator_agent.evaluate(
                    job_name=rca.get("job_name", ""),
                    error_message=rca.get("error_message", ""),
                    rca_analysis=rca.get("root_cause", ""),
                    dab_context=dab_text,
                    uc_lineage=uc_text,
                )
                rca = {
                    **rca,
                    "eval_score":      evaluation.overall_score,
                    "eval_passed":     evaluation.passed,
                    "eval_iterations": rca.get("eval_iterations", 1),
                    "eval_scores_breakdown": {
                        "clarity":       evaluation.clarity_score,
                        "actionability": evaluation.actionability_score,
                        "completeness":  evaluation.completeness_score,
                    },
                    "_eval_feedback":              evaluation.feedback,
                    "_eval_clarity_feedback":      evaluation.clarity_feedback,
                    "_eval_actionability_feedback":evaluation.actionability_feedback,
                    "_eval_completeness_feedback": evaluation.completeness_feedback,
                }
                score = evaluation.overall_score

            max_iters    = self.evaluator_agent.max_iterations
            current_iter = rca.get("eval_iterations", 1)

            if rca.get("eval_passed") or current_iter >= max_iters:
                status = "✅ passed" if rca.get("eval_passed") else f"⚠️ max iterations ({max_iters}) reached"
                log.append(
                    f"RCA Evaluator: {rca['job_name']} — score {score:.1f}/10 "
                    f"(C:{rca['eval_scores_breakdown']['clarity']:.0f} "
                    f"A:{rca['eval_scores_breakdown']['actionability']:.0f} "
                    f"Co:{rca['eval_scores_breakdown']['completeness']:.0f}) {status}"
                )
                passed.append(rca)
            else:
                log.append(
                    f"RCA Evaluator: {rca['job_name']} — score {score:.1f}/10 "
                    f"(C:{rca['eval_scores_breakdown']['clarity']:.0f} "
                    f"A:{rca['eval_scores_breakdown']['actionability']:.0f} "
                    f"Co:{rca['eval_scores_breakdown']['completeness']:.0f}) "
                    f"below threshold {EVAL_THRESHOLD} — retry {current_iter + 1}/{max_iters}"
                )
                # Build structured targeted feedback for the retry
                feedback_parts = []
                if rca.get("_eval_clarity_feedback"):
                    feedback_parts.append(f"CLARITY: {rca['_eval_clarity_feedback']}")
                if rca.get("_eval_actionability_feedback"):
                    feedback_parts.append(f"ACTIONABILITY: {rca['_eval_actionability_feedback']}")
                if rca.get("_eval_completeness_feedback"):
                    feedback_parts.append(f"COMPLETENESS: {rca['_eval_completeness_feedback']}")

                rca["evaluator_feedback"] = "\n\n".join(feedback_parts) or rca.get("_eval_feedback", "")
                rca["eval_iterations"]    = current_iter + 1
                rca["eval_score"]  = None
                rca["eval_passed"] = None
                failed.append(rca)

        return {
            # Replace rca_results with scored+passed versions
            "rca_results":      passed,
            # Replace pending — empty means no retry, non-empty triggers retry
            "rca_eval_pending": failed,
            "rca_eval_done":    passed,
            "execution_log":    log,
        }

    def _route_after_monitor(
        self, state: SupervisorState,
    ) -> Literal["rca_fan_out", "end"]:
        if state.get("failed_jobs"):
            return "rca_fan_out"
        return "end"

    # ── Parallel RCA fan-out (Option 4) ──────────────────────────────────────

    def _rca_fan_out_node(self, state: SupervisorState) -> dict[str, Any]:
        """Staging node that shows up in the diagram between monitor and rca."""
        failed_jobs = state.get("failed_jobs", [])
        self._last_fan_out_degree = len(failed_jobs)  # captured for diagram label
        return {
            "execution_log": [
                f"Supervisor: fanning out RCA to {len(failed_jobs)} parallel job(s)"
            ],
        }

    def _fan_out_rca(self, state: SupervisorState):
        """
        Option 4 — Parallel RCA using LangGraph Send API.

        Returns one Send per failed job. LangGraph executes all rca nodes
        simultaneously. Results merge back via Annotated[list, operator.add]
        on rca_results — no manual merging needed (Option 3 enables this).
        """
        failed_jobs = state.get("failed_jobs", [])
        if not failed_jobs:
            return END
        return [
            Send("rca", {**state, "failed_jobs": [job]})
            for job in failed_jobs
        ]

    def _route_after_evaluator(
        self, state: SupervisorState,
    ) -> Literal["rca", "incident", "end"]:
        """Retry loop back to rca if pending, else proceed to incident or end."""
        if state.get("rca_eval_pending"):
            return "rca"
        task = state.get("task", "")
        if task == "monitor_analyze_incident" and state.get("rca_results"):
            return "incident"
        return "end"

    def _incident_node(self, state: SupervisorState) -> dict[str, Any]:
        """Pause for per-incident human review before creating any tickets.

        Option 5 — Richer Human-in-the-Loop:
        The interrupt payload exposes each incident individually. The human can:
          - Approve or reject each incident independently
          - Override the severity the LLM assigned
          - Add a context note that gets appended to the Jira ticket description
        Only approved incidents proceed to ticket creation.
        """
        candidates = state.get("rca_results", [])
        if not candidates:
            return {
                "incident_results": [],
                "execution_log":    ["Supervisor: no RCA results — skipped incident creation"],
                "workflow_status":  "completed",
            }

        # Interrupt — UI renders per-incident review form and resumes with decisions
        decisions = interrupt({
            "type":            "incident_review",
            "workflow_run_id": state.get("workflow_run_id"),
            "incidents":       candidates,
        })

        # decisions is a list of per-incident dicts:
        # [{"run_id": ..., "approved": bool, "severity_override": str|None, "context_note": str}]
        decision_map: dict[str, dict] = {}
        if isinstance(decisions, list):
            for d in decisions:
                decision_map[str(d.get("run_id"))] = d
        elif isinstance(decisions, dict):
            # Legacy: single approve/reject for all
            approved = decisions.get("approved", False)
            decision_map = {
                str(r.get("run_id")): {"approved": approved, "severity_override": None, "context_note": ""}
                for r in candidates
            }

        approved_rca    = []
        rejected_results = []

        for rca in candidates:
            run_id   = str(rca.get("run_id"))
            decision = decision_map.get(run_id, {"approved": False})

            if decision.get("approved", False):
                # Apply human overrides before passing to incident agent
                enriched = {**rca}
                if decision.get("severity_override"):
                    enriched["severity"] = decision["severity_override"]
                if decision.get("context_note"):
                    enriched["human_context"] = decision["context_note"]
                approved_rca.append(enriched)
            else:
                rejected_results.append({
                    "incident_id": f"REVIEW-{run_id}",
                    "job_name":    rca.get("job_name"),
                    "run_id":      rca.get("run_id"),
                    "severity":    rca.get("severity"),
                    "status":      "rejected",
                    "message":     "Rejected during human review",
                })

        log = []
        if rejected_results:
            log.append(f"Supervisor: {len(rejected_results)} incident(s) rejected by human")
        if not approved_rca:
            return {
                "incident_results": rejected_results,
                "execution_log":    log + ["Supervisor: no approved incidents — skipping creation"],
                "workflow_status":  "rejected",
            }

        # Run incident agent only on approved + enriched RCA results
        approved_state = {**state, "rca_results": approved_rca}
        updated = self.incident_agent.execute(approved_state)

        try:
            run_id = state.get("workflow_run_id")
            if run_id:
                self.workflow_store.record_event(
                    run_id, self.incident_agent.name, "completed",
                    {"incident_count": len(updated.get("incident_results", []))},
                )
        except Exception:
            pass

        return {
            "incident_results": rejected_results + updated.get("incident_results", []),
            "agent_results":    updated.get("agent_results", []),
            "execution_log":    log + updated.get("execution_log", []),
            "workflow_status":  "completed",
        }

    # ── Graph visualisation ───────────────────────────────────────────────────

    def _workflow_path(self, state: dict[str, Any]) -> list[str]:
        """Reconstruct visited nodes from execution_log for graph highlighting."""
        log  = state.get("execution_log", [])
        path = ["supervisor"]
        # Only add nodes that were actually visited — check log markers
        node_markers = {
            "monitor":       "Monitor Agent completed",
            "rca_fan_out":   "fanning out RCA",
            "rca_evaluator": "RCA Evaluator:",
            "incident":      "Incident Agent",
        }
        for entry in log:
            for node, marker in node_markers.items():
                if marker in entry and node not in path:
                    path.append(node)
        # rca node is hidden in diagram but drives rca_fan_out highlight — skip it
        return path

    def _workflow_graph_dot(self, workflow_path: list[str]) -> str:
        """Build DOT graph from LangGraph's topology + manually injected Send edges.

        rca is a real graph node but hidden from the diagram — rca_fan_out
        represents the parallel RCA work visually. rca_evaluator connects
        directly to rca_fan_out in the diagram.
        """
        graph         = self.workflow.get_graph()
        visited_nodes = ["__start__", *workflow_path, "__end__"]
        active_edges  = set(zip(visited_nodes, visited_nodes[1:]))

        # Fan-out degree from state (stored by _rca_fan_out_node)
        fan_out_degree = self._last_fan_out_degree

        hidden_nodes = {"rca"}
        skip_edges = {
            ("rca_fan_out",   "rca"),
            ("rca",           "rca_evaluator"),
            ("rca_evaluator", "rca"),
            # Replace with injected dotted version below
            ("rca_evaluator", "incident"),
        }

        rca_visited      = "rca_fan_out" in visited_nodes
        incident_visited = "incident" in visited_nodes
        fan_label        = f"×{fan_out_degree} parallel" if fan_out_degree else "×N parallel"
        retry_happened   = any("retry" in e for e in getattr(self, "_last_execution_log", []))
        injected_edges = [
            # rca_fan_out → rca_evaluator (solid when visited)
            ("rca_fan_out",   "rca_evaluator", fan_label, False, rca_visited),
            # rca_evaluator → rca_fan_out retry (dashed, active only when retry happened)
            ("rca_evaluator", "rca_fan_out",   "retry",   True,  retry_happened),
            # rca_evaluator → incident (dashed conditional — always shown, active when visited)
            ("rca_evaluator", "incident",      "",        True,  incident_visited),
        ]

        lines = [
            "digraph workflow {",
            "  rankdir=TB;",
            '  graph [nodesep=0.12, ranksep=0.2, margin=0.04, pad=0.05];',
            '  node [shape=box, style="rounded,filled", fillcolor="#eef4f3", color="#57736d", fontname="sans-serif", fontsize=9, margin="0.08,0.04"];',
            '  edge [color="#71817d", fontname="sans-serif", fontsize=8, arrowsize=0.7];',
        ]

        for node_id, node in graph.nodes.items():
            if node_id in hidden_nodes:
                continue
            if node_id in visited_nodes:
                attrs = 'fillcolor="#d9f2e8", color="#13805f", fontcolor="#174b3c", penwidth=2'
            else:
                attrs = 'fillcolor="#f1f3f2", color="#c5ccca", fontcolor="#78817e"'
            # Override rca_fan_out label with actual degree
            if node_id == "rca_fan_out" and fan_out_degree:
                label = f"rca_fan_out ({fan_out_degree} jobs)"
            else:
                label = node.name
            lines.append(f'  "{node_id}" [label={json.dumps(label)}, {attrs}];')

        for edge in graph.edges:
            if (edge.source, edge.target) in skip_edges:
                continue
            if edge.source in hidden_nodes or edge.target in hidden_nodes:
                continue
            attrs = []
            if edge.data:
                attrs.append(f"label={json.dumps(str(edge.data))}")
            if edge.conditional:
                attrs.append('style="dashed"')
            if (edge.source, edge.target) in active_edges:
                attrs.extend(['color="#13805f"', 'penwidth=2.5'])
            else:
                attrs.append('color="#c5ccca"')
            suffix = f" [{', '.join(attrs)}]" if attrs else ""
            lines.append(f'  "{edge.source}" -> "{edge.target}"{suffix};')

        for src, tgt, label, dashed, active in injected_edges:
            attrs = [f'label="{label}"']
            if dashed:
                attrs.append('style="dashed"')
            attrs.extend(['color="#13805f"', 'penwidth=2.5'] if active else ['color="#c5ccca"'])
            lines.append(f'  "{src}" -> "{tgt}" [{", ".join(attrs)}];')

        lines.append("}")
        return "\n".join(lines)

    # ── Public API ────────────────────────────────────────────────────────────

    def run_monitoring_workflow(
        self,
        task: str = "monitor_and_analyze",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        initial_state: SupervisorState = {
            "task":             task,
            "workflow_run_id":  session_id or generate_session_id(prefix="etl_monitoring"),
            "jobs_data":        {},
            "failed_jobs":      [],
            "monitor_summary":  "",
            "rca_results":      [],
            "rca_eval_pending": [],
            "rca_eval_done":    [],
            "incident_results": [],
            "agent_results":    [],
            "execution_log":    [],
            "next_agent":       "",
            "workflow_status":  "queued",
            "error":            "",
        }
        session_id = initial_state["workflow_run_id"]
        try:
            self.workflow_store.start_run(run_id=session_id, task=task)
            self.workflow_store.record_event(session_id, self.name, "workflow_started", {"task": task})
        except Exception:
            pass

        langfuse_handler = get_agent_handler(
            agent_name=self.name,
            session_id=session_id,
            additional_tags=["workflow_orchestration"],
        )
        graph_config = {
            "callbacks":    [langfuse_handler] if langfuse_handler else [],
            "metadata":     {"langfuse_session_id": session_id, "langfuse_trace_name": f"{self.name}: {task}"},
            "tags":         ["workflow_orchestration"],
            "configurable": {"thread_id": session_id},
        }

        try:
            final_state = self.workflow.invoke(input=initial_state, config=graph_config)
            workflow_path = self._workflow_path(final_state)
            self._last_execution_log = final_state.get("execution_log", [])
            final_state["workflow_graph"] = self._workflow_graph_dot(workflow_path)
            is_interrupted = bool(final_state.get("__interrupt__"))
            final_state["workflow_status"] = "awaiting_review" if is_interrupted else "completed"
            try:
                self.workflow_store.update_run(
                    run_id=session_id,
                    status=final_state["workflow_status"],
                    final_summary=f"workflow {'awaiting review' if is_interrupted else 'completed'} for '{task}'",
                )
            except Exception:
                pass
            return final_state
        finally:
            if langfuse_handler and Config.LANGFUSE_ENABLED:
                try:
                    from langfuse import Langfuse
                    Langfuse(
                        public_key=Config.LANGFUSE_PUBLIC_KEY,
                        secret_key=Config.LANGFUSE_SECRET_KEY,
                        host=Config.LANGFUSE_HOST,
                    ).flush()
                except Exception:
                    pass

    def resume_incident_review(self, run_id: str, decisions) -> dict[str, Any]:
        """Resume a paused workflow with the human's per-incident review decisions.

        decisions: list of per-incident dicts with keys:
            run_id, approved, severity_override, context_note
        Also accepts a plain bool for legacy single approve/reject.
        """
        graph_config = {"configurable": {"thread_id": run_id}}
        final_state  = self.workflow.invoke(
            Command(resume=decisions),
            config=graph_config,
        )
        self._last_execution_log = final_state.get("execution_log", [])
        final_state["workflow_graph"] = self._workflow_graph_dot(self._workflow_path(final_state))
        status = final_state.get("workflow_status", "completed")
        try:
            self.workflow_store.update_run(run_id=run_id, status=status)
            approved_count = sum(1 for d in decisions if isinstance(d, dict) and d.get("approved", False)) if isinstance(decisions, list) else int(bool(decisions))
            self.workflow_store.record_event(
                run_id, self.name,
                "incident_review_submitted",
                {"approved_count": approved_count, "incident_count": len(final_state.get("incident_results", []))},
            )
        except Exception:
            pass
        return final_state
