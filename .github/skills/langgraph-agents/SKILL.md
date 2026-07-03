---
name: langgraph-agents
description: "Create and integrate LangGraph-based agents with multi-agent orchestration, state management, and supervisor pattern workflow. Use when: building new task agents, implementing agent workflows, integrating tools into agents, or coordinating multi-agent systems."
argument-hint: "Describe the agent type (task agent, supervisor, etc.) and what it should accomplish"
user-invocable: true
---

# LangGraph Agent Development Skill

Build production-ready multi-agent systems using LangGraph state graphs with type-safe workflows, supervisor orchestration, and tool integration.

## When to Use

- ✅ Creating a new task agent (monitor, RCA, incident creation)
- ✅ Implementing an agent workflow with LangGraph
- ✅ Integrating AWS, LLM, or external tools into an agent
- ✅ Building multi-agent coordination with supervisor pattern
- ✅ Setting up state management and conditional routing
- ✅ Testing agent workflows end-to-end

## Quick Workflow

### Step 1: Define Agent State (TypedDict)
Create a strongly-typed state schema that captures all data flowing through the agent workflow. See [State Patterns](./references/state-patterns.md).

### Step 2: Set Up Agent Class & Initialization
Create the agent class with `name`, `description`, tool initialization, and configuration validation. Use the [Agent Template](./references/agent-template.py).

### Step 3: Build LangGraph Workflow
- Add nodes for each step (gather data, analyze, format results)
- Define conditional routing between nodes
- Set entry point and end state
- Test node transitions with mock data

### Step 4: Integrate Tools
Register AWS clients, LLM connections, or external APIs in the `__init__` method. Tools should be reusable and testable in isolation.

### Step 5: Register with Supervisor (Optional)
If this is a task agent, register it in `supervisor_agent.py`:
```python
self.new_agent = NewAgent()
workflow.add_node("new_agent_node", self._new_agent_node)
```

### Step 6: Test & Validate
Run through [Development Checklist](./references/workflow-checklist.md) and add unit tests to `tests/test_agents.py`.

---

## State Management Essentials

**Define state as TypedDict, not plain dict:**
```python
from typing import TypedDict

class JobMonitorState(TypedDict):
    """Typed state for job monitoring workflow"""
    job_ids: list[str]
    jobs_data: dict
    failed_jobs: list
    monitor_summary: str
    next_step: str  # For routing
```

**Why TypedDict?**
- ✅ Type checking catches schema mismatches early
- ✅ IDE autocomplete for state fields
- ✅ Self-documenting field names and types
- ✅ Validates state at graph compile time

---

## Core Patterns

### Node Function Signature
```python
def node_function(state: JobMonitorState) -> JobMonitorState:
    """Transform state and return updated version"""
    # Don't mutate input state
    updated_state = state.copy()
    updated_state["results"] = process_data(state["data"])
    return updated_state
```

### Conditional Routing
```python
def route_decision(state: JobMonitorState) -> str:
    """Determine next node based on state"""
    if state["failed_jobs"]:
        return "rca_node"  # Route to RCA analysis
    else:
        return "report_node"  # Skip to reporting

workflow.add_conditional_edges("monitor_node", route_decision)
```

### Supervisor Pattern
```python
class SupervisorAgent:
    def __init__(self):
        self.monitor_agent = MonitorAgent()
        self.rca_agent = RCAAgent()
        
    def _supervisor_node(self, state):
        """Route to appropriate task agent"""
        if state["task"] == "monitor":
            return self.monitor_agent.run(state)
        elif state["task"] == "rca":
            return self.rca_agent.run(state)
```

---

## File Structure

Create agents following this layout:

```
agents/
├── base_agent.py           # Optional: shared base class
├── new_agent.py            # Your new agent
├── supervisor_agent.py     # Update to register new agent
├── monitor_agent.py
├── rca_agent.py
└── __init__.py

tools/
├── aws_utils.py            # AWS Glue/CloudWatch tools
├── llm_utils.py            # LLM wrapper
└── new_tools.py            # New tool integrations
```

---

## Tool Integration Example

Add tools in `__init__`, use in nodes:

```python
from tools.aws_utils import AWSGlueClient
from models.llm_client import LLMClient

class JobMonitorAgent:
    def __init__(self):
        self.aws_client = AWSGlueClient()  # Initialize once
        self.llm_client = LLMClient()
        
    def _monitor_node(self, state):
        # Use tool to fetch data
        jobs = self.aws_client.get_job_runs(job_names=state["job_ids"])
        
        # Use LLM to analyze
        summary = self.llm_client.summarize(jobs)
        
        return {
            **state,
            "jobs_data": jobs,
            "monitor_summary": summary
        }
```

---

## Common Pitfalls & Solutions

| Problem | Solution |
|---------|----------|
| State mutations cause unexpected behavior | Always return new dict: `{**state, "field": new_value}` |
| Missing type hints on state | Define `TypedDict` for all state objects |
| Agents not appearing in supervisor | Add node and conditional edge to supervisor workflow |
| AWS API timeouts in workflows | Implement retries with exponential backoff in tools |
| LLM calls hanging | Set explicit timeout on LLM client calls |
| State bloat (too many fields) | Split into separate workflows or compress intermediate data |

---

## Next Steps

1. **Choose Agent Type**: Task agent (monitor, RCA) or Supervisor (orchestrator)
2. **Review References**: Check [State Patterns](./references/state-patterns.md) and [Agent Template](./references/agent-template.py)
3. **Implement**: Build state, class, workflow using Step 1-6 above
4. **Test**: Follow [Checklist](./references/workflow-checklist.md)
5. **Integrate**: Register with supervisor if needed
6. **Document**: Update `agents-readme.md` with new agent description

---

## Related Resources

- [State Patterns](./references/state-patterns.md) — Workflow data modeling
- [Agent Template](./references/agent-template.py) — Boilerplate code
- [Workflow Checklist](./references/workflow-checklist.md) — QA verification
- [LangGraph Docs](https://langchain-ai.github.io/langgraph/) — Official documentation
- Project [copilot-instructions.md](../.github/copilot-instructions.md) — Full project guidelines
