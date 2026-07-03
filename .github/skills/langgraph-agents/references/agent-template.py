"""
Agent Template: Starter code for new LangGraph agents

INSTRUCTIONS:
1. Copy this file to agents/your_agent_name.py
2. Replace "TemplateAgent" with your agent class name (e.g., "MonitorAgent")
3. Replace "AGENT_NAME" in comments with your agent's display name
4. Replace "DESCRIPTION" with what your agent does
5. Implement node functions with your specific logic
6. Update TypedDict fields to match your workflow data
"""

from typing import TypedDict, Literal, Optional
from langgraph.graph import StateGraph, END
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# 1. DEFINE AGENT STATE (TypedDict)
# ============================================================================
# TODO: Replace "TemplateAgent" with your agent name in state class

class TemplateAgentState(TypedDict):
    """State schema for agent workflow"""
    # Input fields
    task: str
    input_data: dict
    
    # Processing fields
    processing_results: dict
    
    # Output fields
    summary: str
    next_step: Literal["analyze", "format", "end"]
    
    # Metadata
    errors: list[str]
    timestamp: str


# ============================================================================
# 2. AGENT CLASS & INITIALIZATION
# ============================================================================
# TODO: Replace "TemplateAgent" with your agent class name

class TemplateAgent:
    """
    Template Agent - Generic agent scaffold
    
    TODO: Replace with your agent description
    
    Example:
        agent = TemplateAgent()
        state = {"task": "...", "input_data": {...}}
        result = agent.run(state)
    """
    
    def __init__(self):
        """Initialize agent with tools and configuration"""
        self.name = "TemplateAgent"  # TODO: Change to your agent name
        self.description = "TODO: Add agent description here"
        
        # Initialize tools/clients
        # from tools.aws_utils import AWSGlueClient
        # self.aws_client = AWSGlueClient()
        
        # Build LangGraph workflow
        self.workflow = self._build_workflow()
        self.compiled_workflow = self.workflow.compile()
    
    # ========================================================================
    # 3. LANGGRAPH WORKFLOW NODES
    # ========================================================================
    
    def _entry_node(self, state: TemplateAgentState) -> TemplateAgentState:
        """
        Entry node: Initialize workflow state
        
        Args:
            state: Current workflow state
            
        Returns:
            Updated state with initialized processing fields
        """
        logger.info(f"{self.name}: Starting workflow for task '{state['task']}'")
        
        return {
            **state,
            "processing_results": {},
            "errors": [],
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        }
    
    def _processing_node(self, state: TemplateAgentState) -> TemplateAgentState:
        """
        Processing node: Main logic
        
        Implement your core business logic here.
        """
        try:
            # Example: Call a tool
            # results = self.aws_client.fetch_data(state["input_data"])
            
            results = {"processed": True}  # Placeholder
            
            return {
                **state,
                "processing_results": results,
                "next_step": "format"
            }
        except Exception as e:
            logger.error(f"{self.name}: Processing failed - {str(e)}")
            return {
                **state,
                "errors": state["errors"] + [str(e)],
                "next_step": "format"
            }
    
    def _format_node(self, state: TemplateAgentState) -> TemplateAgentState:
        """
        Format node: Prepare output
        
        Format results for downstream consumption.
        """
        if state["errors"]:
            summary = f"Workflow completed with errors: {state['errors']}"
        else:
            summary = f"Workflow completed successfully: {state['processing_results']}"
        
        return {
            **state,
            "summary": summary,
            "next_step": "end"
        }
    
    def _end_node(self, state: TemplateAgentState) -> TemplateAgentState:
        """
        End node: Finalize and return results
        """
        logger.info(f"{self.name}: Workflow complete")
        return state
    
    # ========================================================================
    # 4. CONDITIONAL ROUTING (Optional)
    # ========================================================================
    
    def _route_after_processing(self, state: TemplateAgentState) -> str:
        """Route based on processing results"""
        if state["errors"]:
            return "format"  # Skip to error handling
        return "format"  # Normal flow
    
    # ========================================================================
    # 5. BUILD LANGGRAPH WORKFLOW
    # ========================================================================
    
    def _build_workflow(self) -> StateGraph:
        """
        Build the LangGraph state machine
        
        Returns:
            Compiled workflow graph
        """
        workflow = StateGraph(TemplateAgentState)
        
        # Add nodes
        workflow.add_node("entry", self._entry_node)
        workflow.add_node("processing", self._processing_node)
        workflow.add_node("format", self._format_node)
        workflow.add_node("end", self._end_node)
        
        # Set entry point
        workflow.set_entry_point("entry")
        
        # Add edges
        workflow.add_edge("entry", "processing")
        workflow.add_conditional_edges(
            "processing",
            self._route_after_processing,
            {"format": "format"}
        )
        workflow.add_edge("format", "end")
        workflow.add_edge("end", END)
        
        return workflow
    
    # ========================================================================
    # 6. PUBLIC RUN METHOD
    # ========================================================================
    
    def run(self, state: TemplateAgentState) -> TemplateAgentState:
        """
        Execute the agent workflow
        
        Args:
            state: Initial state for workflow
            
        Returns:
            Final state with results
        """
        try:
            result = self.compiled_workflow.invoke(state)
            return result
        except Exception as e:
            logger.error(f"{self.name}: Workflow execution failed - {str(e)}")
            return {
                **state,
                "errors": state.get("errors", []) + [str(e)],
                "summary": f"Workflow failed: {str(e)}"
            }


# ============================================================================
# 7. EXAMPLE USAGE (for testing)
# ============================================================================

if __name__ == "__main__":
    # Initialize agent
    agent = TemplateAgent()
    
    # Create sample state
    sample_state: TemplateAgentState = {
        "task": "test",
        "input_data": {"key": "value"},
        "processing_results": {},
        "summary": "",
        "next_step": "analyze",
        "errors": [],
        "timestamp": ""
    }
    
    # Run workflow
    result = agent.run(sample_state)
    
    print(f"Result: {result}")
