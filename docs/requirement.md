# Requirements: Data Engineering Platform AI Agents Application

## 1. Purpose

Develop an Agentic AI application that monitors data-platform ETL jobs, analyzes failures, and supports operational response through coordinated AI agents.

The initial implementation targets Databricks Jobs and provides a Streamlit-based operational dashboard.

## 2. Objectives

The application shall:

- Monitor the latest execution status of configured Databricks jobs.
- Identify failed, successful, running, and unknown job states.
- Retrieve logs and execution details for failed jobs.
- Use an LLM to perform root cause analysis.
- Present monitoring and RCA results through a web interface.
- Provide an extensible multi-agent architecture for future operational tasks.

## 3. Functional Requirements

### 3.1 Supervisor Agent

The Supervisor Agent shall:

- Coordinate the end-to-end monitoring workflow using LangGraph.
- Maintain shared workflow state.
- Delegate job-status collection to the Monitor Agent.
- Delegate failure analysis to the RCA Agent.
- Return a consolidated workflow result.
- Support session identifiers for grouping workflow executions.

### 3.2 Monitor Agent

The Monitor Agent shall:

- Retrieve all Databricks jobs using the Databricks Jobs API.
- Retrieve the latest run for each job.
- Normalize Databricks lifecycle and result states into:
  - `RUNNING`
  - `SUCCEEDED`
  - `FAILED`
  - `UNKNOWN`
- Calculate total, successful, failed, and running job counts.
- Identify failed jobs and preserve their run metadata.
- Produce a human-readable monitoring summary.
- Support retrieval of recent runs for an individual job.

### 3.3 RCA Agent

The RCA Agent shall:

- Process every failed job returned by the Monitor Agent.
- Retrieve run output, task output, error messages, and stack traces.
- Analyze failure information using a configured LLM.
- Produce:
  - Root-cause explanation
  - Actionable recommendations
  - Severity classification
- Support configurable prompts through Langfuse Prompt Management.
- Provide a fallback prompt when Langfuse is unavailable.
- Avoid RCA processing when no failed jobs are detected.

### 3.4 Incident Creation Agent

The platform shall support a future Incident Creation Agent that:

- Creates incidents for qualifying job failures.
- Uses RCA results to populate incident details.
- Includes job name, run ID, error information, root cause, recommendations, and severity.
- Integrates with an incident-management platform such as ServiceNow, Jira
- Prevents duplicate incidents for the same job run.

This capability is planned and is not currently implemented.

### 3.5 User Interface

The Streamlit interface shall:

- Validate required configuration before executing workflows.
- Allow users to manually start monitoring.
- Support configurable automatic refresh.
- Display the configured Databricks workspace and active model information.
- Display job-count metrics for total, successful, failed, and running jobs.
- Display detailed job status records.
- Display RCA results for failed jobs.
- Display severity, root cause, recommendations, and error information.
- Display a successful operational status when no failures are found.
- Report configuration and workflow errors to the user.

## 4. LLM and Prompt Requirements

The application shall:

- Support configurable LLM providers:
  - Ollama
  - Groq
  - Databricks AI Gateway
- Select the provider through environment-based configuration.
- Validate provider-specific credentials and model identifiers.
- Use low-temperature model settings for operational analysis.
- Keep RCA prompts externally manageable through Langfuse when enabled.
- Fall back to local prompts if Langfuse is disabled or unavailable.

## 5. Observability Requirements

The application shall:

- Support optional Langfuse tracing for LangGraph and LangChain execution.
- Record workflow and agent metadata.
- Associate traces with generated session identifiers.
- Capture agent and LLM execution information.
- Support Langfuse prompt-version linking for RCA prompts.
- Flush traces after workflow execution when tracing is enabled.
- Continue operating without Langfuse when tracing is disabled or misconfigured.

## 6. Configuration Requirements

The application shall:

- Load configuration from environment variables.
- Validate Databricks workspace and authentication settings.
- Validate the selected model provider and its required settings.
- Configure refresh intervals.
- Configure Langfuse credentials and tracing behavior.
- Avoid hard-coding credentials or environment-specific endpoints.

## 7. Integration Requirements

The initial platform shall integrate with:

- Databricks Jobs API for job and run information.
- Databricks run-output APIs for failure logs.
- One of the supported LLM providers for RCA.
- Langfuse for optional tracing and prompt management.

The architecture shall allow additional data platforms, incident systems, and worker agents to be added without redesigning the supervisor workflow.

## 8. Reliability and Error Handling

The application shall:

- Handle missing or invalid configuration before workflow execution.
- Surface Databricks, LLM, prompt-management, and incident-integration errors.
- Preserve clear failure context for troubleshooting.
- Handle jobs with no available runs.
- Handle jobs with no available output.
- Limit log content passed to the LLM to control request size and cost.
- Avoid creating incidents when RCA data is incomplete or the failure is not eligible.

## 9. Testing Requirements

The test suite shall cover:

- Configuration validation.
- Databricks job listing and pagination.
- Job status normalization.
- Execution-time calculation.
- Missing-run handling.
- Multi-task run-log aggregation.
- Monitor Agent state generation.
- RCA Agent behavior for failed and non-failed jobs.
- Supervisor workflow routing.
- LLM and external-service behavior using mocks where appropriate.
- Incident deduplication and failure handling once incident creation is implemented.

## 10. Non-Functional Requirements

The application should be:

- Modular, with separate agents, tools, models, and configuration modules.
- Implemented with typed workflow state.
- Compatible with Python 3.12 or later.
- Secure when handling credentials and operational logs.
- Observable through structured traces and metadata.
- Extensible for additional worker agents and data-platform integrations.
- Efficient in LLM usage through concise prompts and bounded log input.