"""
Supervisor Agent - Coordinates workflow between monitor and RCA agents
"""
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, END
from agents.monitor_agent import MonitorAgent
from agents.rca_agent import RCAAgent
from models.llm_client import LLMClient
from langfuse.langchain import CallbackHandler


class SupervisorState(TypedDict):
    """Overall state for the supervisor workflow"""
    task: str
    jobs_data: dict
    failed_jobs: list
    monitor_summary: str
    rca_results: list
    rca_summary: str
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
        self.llm_client = LLMClient()
        
        # Build the workflow graph
        self.workflow = self._build_workflow()
    
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
        print(f"\n[{self.name}] Starting ETL monitoring workflow...")
        print(f"[{self.name}] Task: {state.get('task', 'Monitor all ETL jobs')}")
        
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
    
    def run_monitoring_workflow(self, task: str = "Monitor all ETL jobs") -> dict:
        """
        Run the complete monitoring workflow
        
        Args:
            task: Description of monitoring task
            
        Returns:
            Final state with all results
        """
        initial_state = {
            "task": task,
            "jobs_data": {},
            "failed_jobs": [],
            "monitor_summary": "",
            "rca_results": [],
            "rca_summary": "",
            "next_agent": "monitor"
        }
        
        # Initialize Langfuse CallbackHandler for LangGraph/Langchain (tracing)
        langfuse_handler = CallbackHandler()

        # Execute workflow

        # final_state = self.workflow.invoke(initial_state)
        final_state = self.workflow.invoke(
            input=initial_state,
            config={"callbacks": [langfuse_handler]}
            )
        
        print(f"\n[{self.name}] Workflow complete!")
        
        return final_state