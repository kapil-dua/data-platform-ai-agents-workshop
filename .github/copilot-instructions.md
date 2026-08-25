---
description: "Guidelines for developing the Agentic Data Operations application with multi-agent ETL monitoring, using LangGraph workflows."
---

# Token Minimization Guidelines
Strictly use minimum input and output tokens for all agents. Avoid unnecessary verbosity in prompts and responses. Use concise language and structured data formats (e.g., JSON, TypedDict) to reduce token usage.


## Project Overview

This is a **Multi-Agent Data Platform AI Agents Application** designed to perform data platform operations using Agentic AI. The system coordinates multiple specialized agents like monitoring ETL jobs, performing root cause analysis (RCA), and creating incidents.

### Core Agents

1. **Supervisor Agent**: Orchestrates workflow between monitor and RCA agents using LangGraph
2. **Monitor Agent**: Tracks AWS Glue job execution and status
3. **RCA Agent**: Performs root cause analysis on job failures
4. **Incident Creation Agent**: Creates incidents in incident management systems
---

## Architecture & Design Patterns

### Multi-Agent Orchestration

- Use **LangGraph** (`StateGraph`) for all agent workflows
- Follow the **Supervisor pattern**: one coordinator agent manages task distribution to specialized agents
- For langraph workflows, follow skills and patterns defined in `data-ops-ai-agents/.github/skills/langgraph-agents/SKILL.md`


### Configuration-Driven Design

- All environment variables and settings go in `config.py` using the `Config` class
- Use `pydantic` for validating configuration objects

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

### Tool Development

When creating tools for agents (e.g., `aws_utils.py`, `llm_utils.py`):
- Each tool should be a utility class or function set with clear purpose

---

## File Organization

```
data-ops-ai-agents/
├── agents/
│   ├── __init__.py
│   ├── supervisor_agent.py     # Main orchestrator
│   ├── monitor_agent.py        # Job monitoring
│   ├── rca_agent.py           # Failure analysis
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
