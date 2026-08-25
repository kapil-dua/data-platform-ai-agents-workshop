"""
Supervisor Agent - Coordinates workflow between monitor and RCA agents
"""
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, END
from agents.monitor_agent import MonitorAgent
from agents.rca_agent import RCAAgent
from utils.langfuse_tracing import get_agent_handler, generate_session_id
from config import Config


class SupervisorState(TypedDict):
    """Overall state for the supervisor workflow"""
    task: str
    jobs_data: dict
    failed_jobs: list
    monitor_summary: str
    rca_results: list
    next_agent: str


class SupervisorAgent:
    """Supervisor agent that coordinates the monitoring workflow"""
    
    def __init__(self):
        """Initialize supervisor agent and workflow"""
        self.name = "Supervisor Agent"
        self.description = "Coordinates monitoring and RCA workflow"
        
        # Initialize worker agents
        self.monitor_agent = MonitorAgent()
        self.rca_agent = RCAAgent()
        
        # Build the workflow graph
        self.workflow = self._build_workflow()     
        # Debug: Print the workflow graph in Mermaid format
        print(self.workflow.get_graph().draw_mermaid())

    
    def _build_workflow(self) -> StateGraph:
        """Build the LangGraph workflow"""
        workflow = StateGraph(SupervisorState)
        
        # Add nodes
        workflow.add_node("supervisor", self._supervisor_node)
        workflow.add_node("monitor", self._monitor_node)
        workflow.add_node("rca", self._rca_node)
        
        # Set entry point
        workflow.set_entry_point("supervisor")
        
        # Add edges
        workflow.add_conditional_edges(
            "supervisor",
            self._route_next,
            {
                "monitor": "monitor",
                "end": END
            }
        )
        
        workflow.add_edge("monitor", "rca")
        workflow.add_edge("rca", END)
        
        return workflow.compile()
    
    def _supervisor_node(self, state: SupervisorState) -> SupervisorState:
        """Supervisor decision node"""
        print(f"\n[{self.name}] Starting Supervisor Node...")
        #print(f"[{self.name}] Task: {state.get('task', 'Monitor all ETL jobs')}")
        
        return {
            **state,
            "next_agent": "monitor"
        }
    
    def _monitor_node(self, state: SupervisorState) -> SupervisorState:
        """Execute monitor agent"""
        print(f"\n[{self.name}] Delegating to Monitor Agent...")
        updated_state = self.monitor_agent.monitor_jobs(state)
        return updated_state
    
    def _rca_node(self, state: SupervisorState) -> SupervisorState:
        """Execute RCA agent"""
        print(f"\n[{self.name}] Delegating to RCA Agent...")
        updated_state = self.rca_agent.analyze_failed_jobs(state)
        return updated_state
    
    def _route_next(self, state: SupervisorState) -> Literal["monitor", "end"]:
        """Route to next agent"""
        next_agent = state.get("next_agent", "")
        
        if next_agent == "monitor":
            return "monitor"
        else:
            return "end"
    
    def run_monitoring_workflow(self, task: str = "Monitor all ETL jobs", session_id: str = None) -> dict:
        """
        Run the complete monitoring workflow with Langfuse tracing

        Args:
            task: Description of monitoring task
            session_id: Optional session ID for trace grouping

        Returns:
            Final state with all results
        """
        initial_state = {
            "task": task,
            "jobs_data": {},
            "failed_jobs": [],
            "monitor_summary": "",
            "rca_results": [],
            "next_agent": "monitor"
        }

        # Generate session ID if not provided
        if not session_id:
            session_id = generate_session_id(prefix="etl_monitoring")

        try:
            print(f"\n[{self.name}] Starting ETL monitoring workflow...")
            print(f"[{self.name}] Task: {task}")
            print(f"[{self.name}] Session ID: {session_id}")


            # Setup Langfuse tracing metadata
            trace_tags = ["workflow_orchestration", self.name.lower().replace(" ", "_")]
            trace_metadata = {
                "langfuse_session_id": session_id,
                "langfuse_trace_name": f"{self.name}: {task}",
            }

            # Get Langfuse callback handler for tracing
            langfuse_handler = get_agent_handler(
                agent_name=self.name,
                session_id=session_id,
                additional_tags=["workflow_orchestration"]
            )

            # Debug: verify handler was created for the workflow run
            if langfuse_handler and Config.LANGFUSE_ENABLED:
                print(f"[{self.name}] ✅ Langfuse handler created for session metadata: {session_id}")
            
            # Build callback list
            callbacks = []
            if langfuse_handler:
                callbacks.append(langfuse_handler)

            # Langfuse tracing: 

            # Execute workflow
            final_state = self.workflow.invoke(
                input=initial_state,
                config={
                    "callbacks": callbacks,
                    "metadata": trace_metadata,
                    "tags": trace_tags,
                } if callbacks else {
                    "metadata": trace_metadata,
                    "tags": trace_tags,
                }
            )

            print(f"\n[{self.name}] Workflow complete!")

            # Flush Langfuse traces to ensure they're sent
            if langfuse_handler and Config.LANGFUSE_ENABLED:
                try:
                    from langfuse import Langfuse
                    client = Langfuse(
                        public_key=Config.LANGFUSE_PUBLIC_KEY,
                        secret_key=Config.LANGFUSE_SECRET_KEY,
                        host=Config.LANGFUSE_HOST
                    )
                    client.flush()
                    
                    # Extract trace ID from handler if available
                    if hasattr(langfuse_handler, 'last_trace_id') and langfuse_handler.last_trace_id:
                        trace_id = langfuse_handler.last_trace_id
                        print(f"[{self.name}] ✅ Traces recorded successfully")
                        print(f"[{self.name}] Trace ID: {trace_id}")
                    else:
                        print(f"[{self.name}] ✅ Traces flushed to Langfuse")
                    
                except Exception as flush_error:
                    print(f"[{self.name}] Warning: Traces sent but could not retrieve trace URL: {flush_error}")


            return final_state

        except Exception as e:
            raise