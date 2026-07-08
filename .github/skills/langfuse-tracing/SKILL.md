# Langfuse Agent Tracing Skill - Simplified

## Overview

This skill provides best practices for integrating **Langfuse** observability into LangChain and LangGraph applications using Langfuse's simple `CallbackHandler`. This enables comprehensive monitoring of agent execution, LLM calls, and tool usage with minimal code.

## When to Use

Use this skill when you need to:
- Monitor and trace multi-agent workflows built with LangGraph
- Track LLM API calls and their costs
- Debug agent decision-making and state transitions
- Monitor tool execution performance
- Create observability dashboards for production agent systems
- Analyze agent performance metrics and latency
- Capture detailed logs for compliance and audit trails

## Key Concepts

### 1. **CallbackHandler - Simple Integration**
- Langfuse provides a `CallbackHandler` that integrates directly with LangChain
- Simply add it to the `callbacks` config when invoking LangChain operations
- Automatically captures all LLM calls, embeddings, and tool invocations
- No complex initialization or state management needed

### 2. **Session Management**
- Each workflow run can be associated with a session_id
- Related operations are automatically grouped in Langfuse dashboard
- Sessions can be correlated across multiple workflow runs
- Useful for tracing multi-step processes and debugging

### 3. **Metadata and Tags**
- Add custom metadata to traces for filtering and analysis
- Tag agents, workflows, and environment information
- Langfuse automatically captures timing and token usage
- Metadata helps organize traces in the dashboard

## Simple Architecture

```
Agent Workflow
├── Supervisor Agent
│   └── CallbackHandler(session_id="workflow_123", tags=["supervisor"])
├── Monitor Agent
│   └── CallbackHandler(session_id="workflow_123", tags=["monitor"])
└── RCA Agent
    └── CallbackHandler(session_id="workflow_123", tags=["rca"])

All traces → Langfuse Backend → Dashboard & Analytics
```

## References

- [Langfuse Documentation](https://docs.langfuse.com)
- [LangChain Integration](https://docs.langfuse.com/integrations/langchain)
- [Python SDK Reference](https://docs.langfuse.com/reference/python-sdk)
- [API Reference](https://docs.langfuse.com/api)
