"""Supervisor Agent - A data-platform triage agent which coordinates specialized worker agents
."""
import json
import os
import sqlite3
from typing import Any, Literal, TypedDict
from agents.base_agent import AgentResult
from agents.incident_agent import IncidentAgent
from agents.monitor_agent import MonitorAgent
from agents.rca_agent import RCAAgent
from config import Config
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from utils.durable_memory import WorkflowStore
from utils.langfuse_tracing import generate_session_id, get_agent_handler


class SupervisorState(TypedDict):
    """Shared state passed between the supervisor and worker agents."""
    task: str
    workflow_run_id: str
    jobs_data: dict[str, Any]
    failed_jobs: list[dict[str, Any]]
    monitor_summary: str
    rca_results: list[dict[str, Any]]
    incident_results: list[dict[str, Any]]
    agent_results: list[AgentResult]
    execution_log: list[str]
    next_agent: str
    workflow_status: str
    error: str


class SupervisorAgent:
    """Coordinate specialized agents through a conditional LangGraph workflow."""

    def __init__(self):
        self.name = "Supervisor Agent"
        self.description = "A data-platform triage agent which coordinates specialized worker agents"
        self.monitor_agent = MonitorAgent()
        self.rca_agent = RCAAgent()
        self.incident_agent = IncidentAgent()
        self.workflow_store = WorkflowStore()
        self.checkpointer = self._build_checkpointer()
        self.workflow = self._build_workflow()
        # Debug: Print the workflow graph in Mermaid format
        print(self.workflow.get_graph().draw_mermaid())

    def _build_checkpointer(self):
        """Create a lightweight SQLite-based LangGraph checkpointer for durable state."""
        if SqliteSaver is None:
            return None
        data_dir = os.path.join(os.getcwd(), ".sqlite")
        os.makedirs(data_dir, exist_ok=True)
        checkpoint_path = os.path.join(data_dir, "langgraph_checkpoints.db")
        conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
        return SqliteSaver(conn)

    def _build_workflow(self) -> StateGraph:
        workflow = StateGraph(SupervisorState)
        workflow.add_node("supervisor", self._supervisor_node)
        workflow.add_node("monitor", self._monitor_node)
        workflow.add_node("rca", self._rca_node)
        workflow.add_node("incident", self._incident_node)
        workflow.set_entry_point("supervisor")
        workflow.add_conditional_edges(
            "supervisor", self._route_agent,
            {"monitor": "monitor", "rca": "rca", "incident": "incident", "end": END},
        )
        workflow.add_conditional_edges(
            "monitor", self._route_after_monitor,
            {"rca": "rca", "end": END},
        )
        workflow.add_conditional_edges(
            "rca", self._route_after_rca,
            {"incident": "incident", "end": END},
        )
        workflow.add_edge("incident", END)
        if self.checkpointer is not None:
            return workflow.compile(checkpointer=self.checkpointer)
        return workflow.compile()

    def _workflow_path(self, state: dict[str, Any]) -> list[str]:
        path = ["supervisor"]
        first_agent = state.get("next_agent")
        if first_agent in {"monitor", "rca", "incident"}:
            path.append(first_agent)

        execution_log = state.get("execution_log", [])
        if first_agent == "monitor" and any(
            "failures found; routing to RCA Agent" in message
            for message in execution_log
        ):
            path.append("rca")
        if any(
            "routing RCA results to Incident Agent" in message
            for message in execution_log
        ):
            path.append("incident")
        return path

    def _workflow_graph_dot(self, workflow_path: list[str]) -> str:
        """Return a Graphviz representation of the compiled workflow graph."""
        graph = self.workflow.get_graph()
        visited_nodes = ["__start__", *workflow_path, "__end__"]
        active_edges = set(zip(visited_nodes, visited_nodes[1:]))
        lines = [
            "digraph workflow {",
            "  rankdir=TB;",
            '  graph [nodesep=0.12, ranksep=0.2, margin=0.04, pad=0.05];',
            '  node [shape=box, style="rounded,filled", fillcolor="#eef4f3", color="#57736d", fontname="sans-serif", fontsize=9, margin="0.08,0.04"];',
            '  edge [color="#71817d", fontname="sans-serif", fontsize=8, arrowsize=0.7];',
        ]

        for node_id, node in graph.nodes.items():
            if node_id in visited_nodes:
                attributes = 'fillcolor="#d9f2e8", color="#13805f", fontcolor="#174b3c", penwidth=2'
            else:
                attributes = 'fillcolor="#f1f3f2", color="#c5ccca", fontcolor="#78817e"'
            lines.append(
                f'  "{node_id}" [label={json.dumps(node.name)}, {attributes}];'
            )

        for edge in graph.edges:
            attributes = []
            if edge.data:
                attributes.append(f"label={json.dumps(str(edge.data))}")
            if edge.conditional:
                attributes.append('style="dashed"')
            if (edge.source, edge.target) in active_edges:
                attributes.extend(['color="#13805f"', 'penwidth=2.5'])
            else:
                attributes.append('color="#c5ccca"')
            suffix = f" [{', '.join(attributes)}]" if attributes else ""
            lines.append(f'  "{edge.source}" -> "{edge.target}"{suffix};')

        lines.append("}")
        return "\n".join(lines)

    def _supervisor_node(self, state: SupervisorState) -> SupervisorState:
        """Select the first worker based on the requested demo task."""
        task = state.get("task", "monitor_and_analyze")
        next_agent = {
            "monitor": "monitor",
            "rca": "rca",
            "incident": "incident",
            "monitor_and_analyze": "monitor",
            "monitor_analyze_incident": "monitor",
        }.get(task, "monitor")
        return {
            **state,
            "next_agent": next_agent,
            "workflow_status": "running",
            "execution_log": [
                *state.get("execution_log", []),
                f"{self.name}: received task '{task}'",
                f"{self.name}: routing to {next_agent.title()} Agent",
            ],
        }

    def _monitor_node(self, state: SupervisorState) -> SupervisorState:
        """Run the Monitor Agent and record the handoff."""
        updated_state = self.monitor_agent.execute(state)
        updated_state["execution_log"] = [
            *updated_state.get("execution_log", []),
            f"{self.name}: Monitor Agent completed; evaluating failures",
        ]
        try:
            run_id = updated_state.get("workflow_run_id")
            if run_id:
                self.workflow_store.record_event(
                    run_id,
                    self.monitor_agent.name,
                    "completed",
                    {
                        "failed_jobs": len(updated_state.get("failed_jobs", [])),
                        "job_count": len(updated_state.get("jobs_data", {}).get("all_jobs", [])),
                    },
                )
        except Exception:
            pass
        return updated_state

    def _rca_node(self, state: SupervisorState) -> SupervisorState:
        """Run the RCA Agent and record the handoff."""
        updated_state = self.rca_agent.execute(state)
        updated_state["execution_log"] = [
            *updated_state.get("execution_log", []),
            f"{self.name}: RCA Agent completed",
        ]
        try:
            run_id = updated_state.get("workflow_run_id")
            if run_id:
                self.workflow_store.record_event(
                    run_id,
                    self.rca_agent.name,
                    "completed",
                    {"rca_count": len(updated_state.get("rca_results", []))},
                )
        except Exception:
            pass
        return updated_state

    def _incident_node(self, state: SupervisorState) -> SupervisorState:
        """Pause for human approval before creating any proposed incidents."""
        candidates = state.get("rca_results", [])
        if not candidates:
            return {
                **state,
                "incident_results": [],
                "execution_log": [
                    *state.get("execution_log", []),
                    f"{self.name}: no RCA results to review; skipped incident creation",
                ],
                "workflow_status": "completed",
            }

        decision = interrupt(
            {
                "type": "incident_review",
                "workflow_run_id": state.get("workflow_run_id"),
                "incidents": candidates,
            }
        )
        if not decision.get("approved", False):
            return {
                **state,
                "incident_results": [
                    {
                        "incident_id": f"REVIEW-{result.get('run_id', 'unknown')}",
                        "job_name": result.get("job_name", "unknown"),
                        "run_id": result.get("run_id"),
                        "severity": result.get("severity"),
                        "status": "rejected",
                        "message": "Incident creation rejected during human review",
                    }
                    for result in candidates
                ],
                "execution_log": [
                    *state.get("execution_log", []),
                    f"{self.name}: incident creation rejected during human review",
                ],
                "workflow_status": "rejected",
            }

        approved_state = {**state, "rca_results": candidates}
        updated_state = self.incident_agent.execute(approved_state)
        try:
            run_id = updated_state.get("workflow_run_id")
            if run_id:
                self.workflow_store.record_event(
                    run_id,
                    self.incident_agent.name,
                    "completed",
                    {"incident_count": len(updated_state.get("incident_results", []))},
                )
        except Exception:
            pass
        return updated_state

    def _route_agent(self, state: SupervisorState) -> Literal["monitor", "rca", "incident", "end"]:
        next_agent = state.get("next_agent", "")
        return next_agent if next_agent in {"monitor", "rca", "incident"} else "end"

    def _route_after_monitor(self, state: SupervisorState) -> Literal["rca", "end"]:
        if state.get("task") in {"monitor_and_analyze", "monitor_analyze_incident"} and state.get("failed_jobs"):
            state["execution_log"].append(f"{self.name}: failures found; routing to RCA Agent")
            return "rca"
        state["execution_log"].append(f"{self.name}: no RCA required; ending workflow")
        return "end"

    def _route_after_rca(self, state: SupervisorState) -> Literal["incident", "end"]:
        if state.get("task") == "monitor_analyze_incident":
            state["execution_log"].append(f"{self.name}: routing RCA results to Incident Agent")
            return "incident"
        state["execution_log"].append(f"{self.name}: incident creation not requested")
        return "end"

    def run_monitoring_workflow(
        self,
        task: str = "monitor_and_analyze",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Run the selected workflow with optional Langfuse tracing."""
        initial_state: SupervisorState = {
            "task": task,
            "workflow_run_id": session_id or generate_session_id(prefix="etl_monitoring"),
            "jobs_data": {},
            "failed_jobs": [],
            "monitor_summary": "",
            "rca_results": [],
            "incident_results": [],
            "agent_results": [],
            "execution_log": [],
            "next_agent": "monitor",
            "workflow_status": "queued",
            "error": "",
        }
        session_id = initial_state["workflow_run_id"]
        try:
            self.workflow_store.start_run(run_id=session_id, task=task)
            self.workflow_store.record_event(session_id, self.name, "workflow_started", {"task": task})
        except Exception:
            pass
        trace_tags = ["workflow_orchestration", self.name.lower().replace(" ", "_")]
        trace_metadata = {
            "langfuse_session_id": session_id,
            "langfuse_trace_name": f"{self.name}: {task}",
        }
        langfuse_handler = get_agent_handler(
            agent_name=self.name,
            session_id=session_id,
            additional_tags=["workflow_orchestration"],
        )
        callbacks = [langfuse_handler] if langfuse_handler else []
        graph_config = {
            "callbacks": callbacks,
            "metadata": trace_metadata,
            "tags": trace_tags,
            "configurable": {"thread_id": session_id},
        }
        try:
            final_state = self.workflow.invoke(
                input=initial_state,
                config=graph_config,
            )
            workflow_path = self._workflow_path(final_state)
            final_state["workflow_graph"] = self._workflow_graph_dot(workflow_path)
            is_interrupted = bool(final_state.get("__interrupt__"))
            final_state["workflow_status"] = "awaiting_review" if is_interrupted else "completed"
            try:
                self.workflow_store.update_run(
                    run_id=session_id,
                    status=final_state["workflow_status"],
                    final_summary=(
                        f"workflow awaiting incident review for task '{task}'"
                        if is_interrupted
                        else f"workflow completed for task '{task}'"
                    ),
                )
                self.workflow_store.record_event(
                    session_id,
                    self.name,
                    "incident_review_requested" if is_interrupted else "workflow_completed",
                    {
                        "task": task,
                        "failed_jobs": len(final_state.get("failed_jobs", [])),
                        "incident_count": len(final_state.get("incident_results", [])),
                        "review_count": len(final_state.get("rca_results", [])) if is_interrupted else 0,
                    },
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

    def resume_incident_review(self, run_id: str, approved: bool) -> dict[str, Any]:
        """Resume a paused workflow with the human's incident-review decision."""
        graph_config = {"configurable": {"thread_id": run_id}}
        final_state = self.workflow.invoke(
            Command(resume={"approved": approved}),
            config=graph_config,
        )
        final_state["workflow_graph"] = self._workflow_graph_dot(self._workflow_path(final_state))
        status = final_state.get("workflow_status", "completed")
        try:
            self.workflow_store.update_run(
                run_id=run_id,
                status=status,
                final_summary=f"incident review {status} for workflow '{run_id}'",
            )
            self.workflow_store.record_event(
                run_id,
                self.name,
                "incident_review_approved" if approved else "incident_review_rejected",
                {"incident_count": len(final_state.get("incident_results", []))},
            )
        except Exception:
            pass
        return final_state
