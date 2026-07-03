# Quick Snippets & Common Patterns

Copy-paste ready code for common agent development tasks.

---

## Snippet 1: Basic Agent Scaffold

```python
"""
[Agent Name] - [Brief description]
"""
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, END
from config import Config
import logging

logger = logging.getLogger(__name__)

class [Name]State(TypedDict):
    """State for [name] workflow"""
    task: str
    data: dict
    result: dict
    next_step: Literal["process", "format", "end"]
    errors: list[str]

class [Name]Agent:
    def __init__(self):
        self.name = "[Name]"
        self.description = "[Description]"
        self.workflow = self._build_workflow()
        self.compiled = self.workflow.compile()
    
    def _build_workflow(self) -> StateGraph:
        workflow = StateGraph([Name]State)
        workflow.add_node("process", self._process_node)
        workflow.add_node("format", self._format_node)
        workflow.set_entry_point("process")
        workflow.add_edge("process", "format")
        workflow.add_edge("format", END)
        return workflow
    
    def _process_node(self, state: [Name]State) -> [Name]State:
        try:
            # Your logic here
            result = {"status": "ok"}
            return {**state, "result": result}
        except Exception as e:
            logger.error(f"{self.name}: {str(e)}")
            return {**state, "errors": state["errors"] + [str(e)]}
    
    def _format_node(self, state: [Name]State) -> [Name]State:
        return state
    
    def run(self, state: [Name]State) -> [Name]State:
        return self.compiled.invoke(state)
```

---

## Snippet 2: Conditional Routing

```python
# Define routing states in TypedDict
class State(TypedDict):
    decision_field: str
    next_step: Literal["path_a", "path_b", "end"]

# Router function
def route_decision(state: State) -> str:
    if state["decision_field"] == "condition_1":
        return "path_a"
    else:
        return "path_b"

# Add to workflow
workflow.add_node("path_a", node_a_func)
workflow.add_node("path_b", node_b_func)
workflow.add_conditional_edges("entry", route_decision, {
    "path_a": "path_a",
    "path_b": "path_b"
})
```

---

## Snippet 3: AWS Glue Integration

```python
from tools.aws_utils import AWSGlueClient

class MyAgent:
    def __init__(self):
        self.aws_client = AWSGlueClient()
    
    def _fetch_jobs_node(self, state):
        try:
            # Get jobs by name
            jobs = self.aws_client.get_job_runs(
                job_names=state["job_ids"]
            )
            
            # Extract failed jobs
            failed = [j for j in jobs if j["JobRunState"] == "FAILED"]
            
            return {
                **state,
                "jobs_data": jobs,
                "failed_count": len(failed)
            }
        except Exception as e:
            logger.error(f"AWS error: {e}")
            return {**state, "errors": state["errors"] + [str(e)]}
```

---

## Snippet 4: LLM Integration

```python
from models.llm_client import LLMClient

class MyAgent:
    def __init__(self):
        self.llm = LLMClient()
    
    def _analyze_node(self, state):
        try:
            prompt = f"""
            Analyze these job failures:
            {state['failed_jobs']}
            
            Provide root cause analysis.
            """
            
            analysis = self.llm.invoke(prompt)
            
            return {**state, "analysis": analysis}
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return {**state, "errors": state["errors"] + [str(e)]}
```

---

## Snippet 5: State Validation

```python
from pydantic import BaseModel, ValidationError

class JobInput(BaseModel):
    job_ids: list[str]
    priority: int = 1

def _validate_input_node(self, state):
    try:
        # Validate input data
        validated = JobInput(**state["input_data"])
        
        return {**state, "validated_input": validated.dict()}
    except ValidationError as e:
        logger.error(f"Validation error: {e}")
        return {**state, "errors": state["errors"] + [str(e)]}
```

---

## Snippet 6: Batch Processing

```python
def _process_batch_node(self, state):
    """Process multiple items with progress tracking"""
    items = state["items"]
    results = {}
    errors = state["errors"].copy()
    
    for i, item in enumerate(items):
        try:
            result = self._process_single_item(item)
            results[item["id"]] = result
        except Exception as e:
            logger.error(f"Error processing {item['id']}: {e}")
            errors.append(f"Item {item['id']}: {str(e)}")
    
    return {
        **state,
        "results": results,
        "errors": errors,
        "processed_count": len(results)
    }
```

---

## Snippet 7: Error Recovery with Retry

```python
import time
from functools import wraps

def retry_on_failure(max_retries=3, backoff_seconds=1):
    """Decorator for retrying operations with exponential backoff"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    wait_time = backoff_seconds * (2 ** attempt)
                    logger.warning(f"Attempt {attempt+1} failed, retrying in {wait_time}s")
                    time.sleep(wait_time)
        return wrapper
    return decorator

# Usage
@retry_on_failure(max_retries=3)
def fetch_from_aws(self, job_id):
    return self.aws_client.get_job_run(job_id)
```

---

## Snippet 8: Logging & Debugging

```python
import logging
from datetime import datetime

# Configure logger
logger = logging.getLogger(__name__)

def _process_node(self, state):
    logger.info(f"Starting {self.name} processing at {datetime.utcnow().isoformat()}")
    logger.debug(f"State: {state}")
    
    try:
        result = self._do_work(state)
        logger.info(f"Processing complete, result keys: {list(result.keys())}")
        return {**state, "result": result}
    except Exception as e:
        logger.error(f"Processing failed: {str(e)}", exc_info=True)
        return {**state, "errors": state["errors"] + [str(e)]}
```

---

## Snippet 9: Unit Test Template

```python
import pytest
from unittest.mock import MagicMock, patch
from agents.my_agent import MyAgent, MyAgentState

@pytest.fixture
def agent():
    """Fixture: Create agent with mocked tools"""
    with patch('agents.my_agent.AWSGlueClient'):
        agent = MyAgent()
        agent.aws_client = MagicMock()
        return agent

def test_process_node_success(agent):
    """Test node with successful processing"""
    state: MyAgentState = {
        "task": "test",
        "data": {"id": "job-1"},
        "result": {},
        "next_step": "format",
        "errors": []
    }
    
    agent.aws_client.get_job_runs.return_value = [
        {"JobRunId": "job-1", "JobRunState": "SUCCEEDED"}
    ]
    
    result = agent._process_node(state)
    
    assert result["result"]["success"] is True
    assert len(result["errors"]) == 0

def test_process_node_error(agent):
    """Test node with error handling"""
    state: MyAgentState = {
        "task": "test",
        "data": {"id": "job-1"},
        "result": {},
        "next_step": "format",
        "errors": []
    }
    
    agent.aws_client.get_job_runs.side_effect = Exception("AWS error")
    
    result = agent._process_node(state)
    
    assert len(result["errors"]) > 0
    assert "AWS error" in result["errors"][0]
```

---

## Snippet 10: Integration with Supervisor

```python
# In supervisor_agent.py

from agents.my_agent import MyAgent

class SupervisorAgent:
    def __init__(self):
        # Initialize task agent
        self.my_agent = MyAgent()
        self.workflow = self._build_workflow()
    
    def _my_agent_node(self, state: SupervisorState) -> SupervisorState:
        """Route to MyAgent and handle results"""
        # Prepare input for task agent
        task_state = {
            "task": state["task"],
            "data": state["data"],
            "result": {},
            "next_step": "process",
            "errors": []
        }
        
        # Run task agent
        task_result = self.my_agent.run(task_state)
        
        # Update supervisor state with results
        return {
            **state,
            "task_results": task_result["result"],
            "next_agent": "report"  # Route to next step
        }
    
    def _build_workflow(self):
        workflow = StateGraph(SupervisorState)
        
        # Add nodes
        workflow.add_node("my_agent", self._my_agent_node)
        
        # Route supervisor entry to my_agent if needed
        def route_supervisor(state):
            if state["task"] == "my_task":
                return "my_agent"
            else:
                return "other_agent"
        
        workflow.add_conditional_edges("supervisor", route_supervisor)
        
        return workflow
```

---

## Snippet 11: Configuration Validation

```python
from config import Config
from pydantic import BaseModel, Field

class AgentConfig(BaseModel):
    """Validate agent-specific configuration"""
    groq_key: str = Field(min_length=1)
    aws_region: str = Field(default="us-east-1")
    timeout_seconds: int = Field(default=30, ge=1)

class MyAgent:
    def __init__(self):
        # Validate required config
        config = AgentConfig(
            groq_key=Config.GROQ_API_KEY,
            aws_region=Config.AWS_REGION
        )
        
        if not config.groq_key:
            raise ValueError("GROQ_API_KEY not configured")
        
        self.config = config
```

---

## Snippet 12: Performance Timing

```python
from datetime import datetime, timedelta
import time

def _timed_process_node(self, state):
    """Process with execution time tracking"""
    start_time = time.time()
    start_dt = datetime.utcnow()
    
    try:
        # Your processing logic
        result = self._do_work(state)
        
        elapsed = time.time() - start_time
        logger.info(f"Processing completed in {elapsed:.2f}s")
        
        return {
            **state,
            "result": result,
            "execution_time": elapsed,
            "completed_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"Processing failed after {elapsed:.2f}s: {e}")
        return {**state, "errors": state["errors"] + [str(e)]}
```

---

## Quick Reference: TypedDict

```python
from typing import TypedDict, Literal, Optional, Union

# Basic fields
class State(TypedDict):
    name: str                  # Required
    age: int                   # Required
    email: Optional[str]       # Optional
    
    # Collections
    tags: list[str]
    metadata: dict
    items: list[dict]
    
    # Unions
    result: Union[str, dict]
    
    # Literal (for routing)
    status: Literal["pending", "active", "done"]

# Optional fields using total=False
class PartialState(TypedDict, total=False):
    optional_field: str        # Optional
    another_optional: int
```

---

## Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| State mutation in node | Always use `{**state, "field": new_value}` |
| TypedDict field missing | Add field to TypedDict and update all nodes |
| Circular workflow | Check edges - ensure no cycles except via END |
| LLM call timeout | Add timeout param to LLM invoke |
| AWS API throttle | Implement exponential backoff retry |
| State too large | Split into separate state objects |
| Can't import module | Check module in agents/__init__.py or tools/__init__.py |
