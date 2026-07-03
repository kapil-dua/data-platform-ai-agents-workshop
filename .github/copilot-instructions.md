---
description: "Guidelines for developing the Agentic Data Operations application with multi-agent ETL monitoring, LangGraph workflows, AWS integration, and state management patterns."
---

# Copilot Instructions: Agentic Data Operations Application

## Project Overview

This is a **Multi-Agent ETL Monitoring Application** designed to perform data platform operations using Agentic AI. The system coordinates multiple specialized agents to monitor ETL jobs, perform root cause analysis (RCA), and create incidents.

### Core Agents

1. **Supervisor Agent**: Orchestrates workflow between monitor and RCA agents using LangGraph
2. **Monitor Agent**: Tracks AWS Glue job execution and status
3. **RCA Agent**: Performs root cause analysis on job failures
4. **Incident Creation Agent**: Creates incidents in incident management systems
5. **Chat Agent**: Handles user interactions and queries
---

## Architecture & Design Patterns

### Multi-Agent Orchestration

- Use **LangGraph** (`StateGraph`) for all agent workflows
- Define agent states using `TypedDict` for type safety and clarity
- Follow the **Supervisor pattern**: one coordinator agent manages task distribution to specialized agents
- Use explicit state transitions with conditional routing via `add_conditional_edges()`

**Example Pattern:**
```python
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, END

class AgentState(TypedDict):
    """Typed state for the agent workflow"""
    task: str
    data: dict
    results: list
    next_agent: str

workflow = StateGraph(AgentState)
workflow.add_node("agent_name", node_function)
workflow.add_conditional_edges("agent_name", routing_function)
```

### Agent Structure

Each agent should:
- Inherit from a base `Agent` class or follow the same interface
- Define a clear `name` and `description`
- Implement a `run()` or `execute()` method for task execution
- Return structured results matching the state schema

### Configuration-Driven Design

- All environment variables and settings go in `config.py` using the `Config` class
- Use `pydantic` for validating configuration objects
- Support multiple LLM backends (Groq, Ollama) via `MODEL_TO_USE` config
- Validate all required credentials at startup via `Config.validate()`

---

## Code Standards

### Python Style & Structure

- **Python 3.12+** minimum
- Use **type hints** on all functions and class methods
- Use `TypedDict` for structured data (never plain dicts for agent state)
- Include module docstrings and function docstrings
- Use `pydantic` models for data validation and serialization

### Error Handling & Logging

- Wrap agent operations in try-except blocks with meaningful error messages
- Log agent decisions and state transitions (use `logging` module)
- Return error states in agent results, don't raise exceptions silently
- Include context in error messages (job ID, agent name, timestamp)

### Tool Development

When creating tools for agents (e.g., `aws_utils.py`, `llm_utils.py`):
- Each tool should be a utility class or function set with clear purpose
- Document AWS service dependencies (Glue, CloudWatch, etc.)
- Use boto3 with proper session/credential management via `config.py`
- Handle AWS API rate limits and transient failures gracefully

---

## AWS Integration Guidelines

### Service Usage

- **AWS Glue**: Job definitions, runs, and metrics
- **CloudWatch**: Job logs and performance metrics
- **Secrets Manager** (optional): Manage sensitive credentials

---

## Agent Development Checklist

When adding or modifying agents:

1. **State Management**
   - Define `AgentState` using `TypedDict`
   - Include all fields needed for workflow routing
   - Document each field's purpose

2. **Initialization**
   - Set `name` and `description` attributes
   - Initialize required tools/clients (AWS, LLM, etc.)
   - Validate configuration in `__init__` if needed

3. **Workflow Integration**
   - Create workflow nodes with clear function signatures
   - Use `StateGraph` to define the graph structure
   - Test edge cases and conditional routing

4. **Tool Usage**
   - Use existing tools from `tools/` directory
   - Create tools for new AWS or external service integrations
   - Follow the `AWSGlueClient` pattern for reusability

5. **Testing**
   - Add unit tests in `tests/test_agents.py`
   - Mock AWS calls for unit tests
   - Test state transitions and error paths

---

## File Organization

```
data-ops-ai-agents/
├── agents/
│   ├── __init__.py
│   ├── supervisor_agent.py     # Main orchestrator
│   ├── monitor_agent.py        # Job monitoring
│   ├── rca_agent.py           # Failure analysis
│   ├── chat_agent.py          # User interaction
│   └── incident_agent.py      # Incident creation (if needed)
├── tools/
│   ├── aws_utils.py           # AWS service integrations
│   ├── llm_utils.py           # LLM client wrapper
│   └── incident_tools.py      # Incident API tools (if needed)
├── models/
│   └── llm_client.py          # Unified LLM interface
├── config.py                  # All configuration
├── app.py                     # Streamlit UI entry point
└── tests/
    └── test_agents.py         # Agent tests
```
