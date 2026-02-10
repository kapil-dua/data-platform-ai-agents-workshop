"""
Supervisor Agent - Coordinates workflow between monitor and RCA agents
"""
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, END
from agents.monitor_agent import MonitorAgent
from agents.rca_agent import RCAAgent
from utils.llm_utils import LLMClient


class SupervisorState(TypedDict):
    """Overall state for the supervisor workflow"""
    task: str
    jobs_data: dict
    failed_jobs: list
    monitor_summary: str
    rca_results: list
    rca_summary: str
    next_agent: str
    final_report: str


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
        workflow.add_node("report", self._report_node)
        
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
        workflow.add_edge("rca", "report")
        workflow.add_edge("report", END)
        
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
    
    def _report_node(self, state: SupervisorState) -> SupervisorState:
        """Generate final report"""
        print(f"\n[{self.name}] Generating final report...")
        
        final_report = self._generate_final_report(state)
        
        return {
            **state,
            "final_report": final_report
        }
    
    def _route_next(self, state: SupervisorState) -> Literal["monitor", "end"]:
        """Route to next agent"""
        next_agent = state.get("next_agent", "")
        
        if next_agent == "monitor":
            return "monitor"
        else:
            return "end"
    
    def _generate_final_report(self, state: SupervisorState) -> str:
        """Generate comprehensive final report"""
        jobs_data = state.get("jobs_data", {})
        monitor_summary = state.get("monitor_summary", "")
        rca_summary = state.get("rca_summary", "")
        rca_results = state.get("rca_results", [])
        
        system_prompt = """You are generating an executive report for ETL job monitoring.
        Create a comprehensive but concise report that includes:
        1. Overall status summary
        2. Key metrics
        3. Critical issues and their root causes
        4. Recommended actions
        
        Format the report in a clear, professional manner suitable for technical stakeholders."""
        
        user_message = f"""
        Generate final report based on:
        
        MONITORING SUMMARY:
        {monitor_summary}
        
        JOBS DATA:
        - Total Jobs: {jobs_data.get('total_jobs', 0)}
        - Successful: {jobs_data.get('successful_count', 0)}
        - Failed: {jobs_data.get('failed_count', 0)}
        - Running: {jobs_data.get('running_count', 0)}
        
        RCA SUMMARY:
        {rca_summary}
        
        DETAILED RCA RESULTS:
        {len(rca_results)} jobs analyzed
        """
        
        final_report = self.llm_client.invoke_with_prompt(
            system_message=system_prompt,
            user_message=user_message
        )
        
        print(f"[{self.name}] Workflow complete!")
        
        return final_report
    
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
            "next_agent": "monitor",
            "final_report": ""
        }
        
        # Execute workflow
        final_state = self.workflow.invoke(initial_state)
        
        return final_state