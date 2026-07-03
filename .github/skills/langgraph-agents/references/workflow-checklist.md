# Agent Development & Integration Checklist

Use this checklist to ensure your agent is production-ready before integrating it into the supervisor workflow.

---

## Phase 1: State Design ✓

### State Definition
- [ ] State defined as `TypedDict` (never plain dict)
- [ ] All fields documented with purpose
- [ ] Input fields clearly labeled
- [ ] Output fields for downstream consumption
- [ ] Routing field (if using conditional edges): `Literal["step1", "step2", ...]`
- [ ] Error fields: `errors: list[str]`
- [ ] No function/object references in state (data only)

**Example:**
```python
from typing import TypedDict, Literal

class NewAgentState(TypedDict):
    """State for [agent] workflow"""
    # Input
    input_data: dict
    
    # Processing
    processed: dict
    
    # Output
    result: str
    
    # Routing
    next_step: Literal["analyze", "format", "end"]
    
    # Errors
    errors: list[str]
```

---

## Phase 2: Agent Class & Initialization ✓

### Class Structure
- [ ] Agent class created: `class [Name]Agent:`
- [ ] Module docstring explains purpose
- [ ] `__init__` method initializes:
  - [ ] `self.name` attribute
  - [ ] `self.description` attribute
  - [ ] All required tools/clients (AWS, LLM, etc.)
  - [ ] `self.workflow` from `_build_workflow()`
  - [ ] `self.compiled_workflow = self.workflow.compile()`

### Configuration Validation
- [ ] Required environment variables validated
- [ ] API keys/credentials checked at init time
- [ ] Logging configured (using `logging` module)

**Example:**
```python
from logging import getLogger
from config import Config

logger = getLogger(__name__)

class NewAgent:
    def __init__(self):
        self.name = "NewAgent"
        self.description = "Does X"
        
        # Validate config
        if not Config.GROQ_API_KEY:
            raise ValueError("Missing GROQ_API_KEY")
        
        # Initialize tools
        from tools.aws_utils import AWSGlueClient
        self.aws_client = AWSGlueClient()
        
        # Build workflow
        self.workflow = self._build_workflow()
        self.compiled_workflow = self.workflow.compile()
```

---

## Phase 3: Workflow Implementation ✓

### Node Functions
- [ ] Each node is a pure function: `def node_name(state: State) -> State:`
- [ ] Nodes don't mutate input state
- [ ] All nodes return updated state using `{**state, ...}`
- [ ] Nodes include try-except with error logging
- [ ] Errors appended to `state["errors"]`, not raised

### Graph Structure
- [ ] `StateGraph(StateType)` created with correct type
- [ ] All nodes added: `workflow.add_node(name, func)`
- [ ] Entry point set: `workflow.set_entry_point("entry")`
- [ ] All edges defined:
  - [ ] Normal edges: `workflow.add_edge("from", "to")`
  - [ ] Conditional edges: `workflow.add_conditional_edges("from", router_func)`
  - [ ] End nodes: `workflow.add_edge("final", END)`

### Routing Logic (if used)
- [ ] Routing function returns valid node name
- [ ] All possible states routed to valid nodes
- [ ] No infinite loops or unreachable nodes
- [ ] Router tests with different state values

**Example:**
```python
def _build_workflow(self):
    workflow = StateGraph(NewAgentState)
    
    # Nodes
    workflow.add_node("gather", self._gather_node)
    workflow.add_node("analyze", self._analyze_node)
    workflow.add_node("format", self._format_node)
    workflow.add_node("end", self._end_node)
    
    # Routing
    def route_analysis(state):
        return "format" if state["errors"] else "analyze"
    
    # Edges
    workflow.set_entry_point("gather")
    workflow.add_edge("gather", "analyze")
    workflow.add_conditional_edges("analyze", route_analysis)
    workflow.add_edge("format", "end")
    workflow.add_edge("end", END)
    
    return workflow
```

---

## Phase 4: Tool Integration ✓

### AWS/External Tools
- [ ] Tools initialized in `__init__` (not in nodes)
- [ ] Tool errors caught and logged
- [ ] Timeouts implemented for API calls
- [ ] Retry logic for transient failures
- [ ] Tool methods return predictable types

### LLM Integration
- [ ] All LLM calls use `models/llm_client.py`
- [ ] Prompts support both Groq and Ollama
- [ ] Token limits considered
- [ ] Timeouts set on LLM calls

---

## Phase 5: Testing ✓

### Unit Tests
- [ ] Created `tests/test_new_agent.py`
- [ ] Mock AWS client for isolated tests
- [ ] Mock LLM client for isolated tests
- [ ] Test each node with sample data
- [ ] Test all routing branches
- [ ] Test error cases (API failures, invalid input)

### Integration Tests
- [ ] Full workflow runs with sample data
- [ ] State flows correctly through nodes
- [ ] Errors handled gracefully
- [ ] Results match expectations

### Manual Testing
- [ ] Run agent with real AWS data (if possible)
- [ ] Verify state transitions in logs
- [ ] Check final output format

**Example Test:**
```python
import pytest
from unittest.mock import MagicMock, patch
from agents.new_agent import NewAgent, NewAgentState

@pytest.fixture
def agent():
    return NewAgent()

def test_gather_node(agent):
    """Test the gather node"""
    # Mock AWS client
    agent.aws_client = MagicMock()
    agent.aws_client.get_data.return_value = {"data": "sample"}
    
    # Create initial state
    state: NewAgentState = {
        "input_data": {"id": "123"},
        "processed": {},
        "result": "",
        "next_step": "analyze",
        "errors": []
    }
    
    # Run node
    result = agent._gather_node(state)
    
    # Verify
    assert result["processed"]["data"] == "sample"
    assert result["next_step"] == "analyze"
    assert len(result["errors"]) == 0
```

---

## Phase 6: Documentation ✓

### Code Documentation
- [ ] Module docstring with overview
- [ ] Class docstring with description and usage
- [ ] Node functions documented: what they do, what they expect
- [ ] State fields documented
- [ ] Tool integrations noted

### Project Documentation
- [ ] Agent added to `agents-readme.md`
- [ ] Agent description explains purpose
- [ ] Example invocation provided
- [ ] Dependencies listed (AWS services, LLM, etc.)

**Example README entry:**
```markdown
### NewAgent

**Purpose**: Performs [X] on [data type]

**Inputs**: 
- `input_field`: Description

**Outputs**:
- `output_field`: Description

**Tools**: AWS Glue, Groq LLM

**Example**:
```python
from agents.new_agent import NewAgent

agent = NewAgent()
result = agent.run({"input": "value"})
```
"""
```

---

## Phase 7: Integration with Supervisor ✓

### Registration (if task agent)
- [ ] Agent registered in `supervisor_agent.py`:
  - [ ] `self.new_agent = NewAgent()` in init
  - [ ] Node added to supervisor workflow
  - [ ] Conditional edge created for routing
- [ ] Supervisor tests updated to include new agent

### State Compatibility
- [ ] New agent state compatible with supervisor state
- [ ] All required fields present
- [ ] No conflicting field definitions

### End-to-End Testing
- [ ] Supervisor can route to new agent
- [ ] Agent receives supervisor state correctly
- [ ] Agent returns state in expected format
- [ ] Supervisor consumes results correctly

---

## Phase 8: Production Readiness ✓

### Performance
- [ ] No unnecessary API calls
- [ ] State serialization is efficient
- [ ] Long-running operations have timeouts
- [ ] Database/API queries optimized

### Error Handling
- [ ] All exceptions caught and logged
- [ ] Graceful degradation on failures
- [ ] User-facing errors are clear
- [ ] System errors logged for debugging

### Security
- [ ] No credentials logged
- [ ] Sensitive data handled carefully
- [ ] Input validation on all user inputs
- [ ] AWS IAM permissions minimal (least privilege)

### Monitoring
- [ ] Key metrics logged (execution time, success rate)
- [ ] Errors include context (agent name, step, timestamp)
- [ ] State transitions logged at appropriate level

---

## Final Sign-Off

- [ ] All tests pass: `pytest tests/test_new_agent.py -v`
- [ ] All checks above completed
- [ ] Code review completed
- [ ] Documentation updated
- [ ] Agent ready for production

---

## Quick Verification Commands

```bash
# Run agent tests
pytest tests/test_new_agent.py -v

# Check for common issues
grep -r "\.copy()" agents/new_agent.py  # Verify state handling
grep -r "raise " agents/new_agent.py    # Check error handling

# Lint & type check
pylint agents/new_agent.py
mypy agents/new_agent.py --strict

# Test with supervisor
python -c "
from agents.supervisor_agent import SupervisorAgent
supervisor = SupervisorAgent()
state = {'task': 'new_agent_task', ...}
result = supervisor.compiled_workflow.invoke(state)
print(result)
"
```
