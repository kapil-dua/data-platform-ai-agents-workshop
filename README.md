# Data Engineering Platform AI Agents Application

## Project Structure
```
data-ops-ai-agents/
├── README.md                   # Project documentation
├── requirements.txt            # Python dependencies
├── .env.example                # Environment template
├── app.py                      # Streamlit web interface
├── config.py                   # Configuration settings
├── agents/
│   ├── __init__.py
│   ├── agents-readme.md        # Agent-specific documentation
│   ├── supervisor_agent.py     # Supervisor with LangGraph workflow
│   ├── monitor_agent.py        # Databricks job monitoring agent
│   ├── rca_agent.py            # Root cause analysis agent
│   └── incident_agent.py       # Incident creation agent
├── tools/
│   ├── __init__.py
│   ├── databricks_tools.py     # Databricks Jobs API utilities
│   └── llm_utils.py            # Groq LLM wrapper
├── models/
│   └── ollama.py               # Ollama model integration
│   └── databricks.py           # Databricks model integration
├── tests/
│   └── test_agents.py          # Agent tests
└── scripts/                    # Utility scripts for setup and deployment
```

## Setup Instructions

1. Install dependencies:
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure environment variables:
```bash
cp .env.example .env
# Edit .env for Model Provider, Data Platform, Atlassian Jira, and Langfuse configurations
```

3. Run the application:
```bash
streamlit run app.py
```
The application will open in your browser at `http://localhost:8501`

## Agent Workflow

### Supervisor Agent
- Uses LangGraph to orchestrate workflow
- Routes tasks to appropriate worker agents

### Monitor Agent
- Queries ETL Jobs API for job statuses
- Identifies failed jobs

### RCA Agent
- Retrieves logs for failed jobs
- Uses LLM to analyze logs and identify root causes
- Provides actionable recommendations

### Incident Agent
- For failed jobs, creates Jira tickets using Atlassian Jira MCP client

### Adding More Agents
1. Create new agent file in `agents/` directory
2. Add to workflow in `supervisor_agent.py`
3. Update Streamlit UI in `app.py`