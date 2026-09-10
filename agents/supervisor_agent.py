"""Supervisor Agent - Coordinates the data-platform agent workflow."""
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from agents.base_agent import AgentResult
from agents.incident_agent import IncidentAgent
from agents.monitor_agent import MonitorAgent
from agents.rca_agent import RCAAgent
from config import Config
from utils.langfuse_tracing import generate_session_id, get_agent_handler


class SupervisorState(TypedDict):
    """Shared state passed between the supervisor and worker agents."""
    task: str
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
        self.description = "Coordinates monitoring, RCA, and demo incident workflows"
        self.monitor_agent = MonitorAgent()
        self.rca_agent = RCAAgent()
        self.incident_agent = IncidentAgent()
        self.workflow = self._build_workflow()
        # Debug: Print the workflow graph in Mermaid format
        print(self.workflow.get_graph().draw_mermaid())

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
        return workflow.compile()

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
        return updated_state

    def _rca_node(self, state: SupervisorState) -> SupervisorState:
        """Run the RCA Agent and record the handoff."""
        updated_state = self.rca_agent.execute(state)
        updated_state["execution_log"] = [
            *updated_state.get("execution_log", []),
            f"{self.name}: RCA Agent completed",
        ]
        return updated_state

    def _incident_node(self, state: SupervisorState) -> SupervisorState:
        """Run the demo Incident Agent."""
        return self.incident_agent.execute(state)

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
        session_id = session_id or generate_session_id(prefix="etl_monitoring")
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
        try:
            final_state = self.workflow.invoke(
                input=initial_state,
                config={
                    "callbacks": callbacks,
                    "metadata": trace_metadata,
                    "tags": trace_tags,
                },
            )
            final_state["workflow_status"] = "completed"
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
