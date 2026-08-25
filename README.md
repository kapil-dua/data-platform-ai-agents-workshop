# Multi-Agent Data Platform AI Agents Application

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
├── tools/
│   ├── __init__.py
│   ├── databricks_tools.py     # Databricks Jobs API utilities
│   └── llm_utils.py            # Groq LLM wrapper
├── models/
│   └── ollama.py               # Ollama model integration
├── tests/
│   └── test_agents.py          # Agent tests
└── infra/                      # Infrastructure code
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
# Edit .env with your credentials
```

3. Run the application:
```bash
streamlit run app.py
```
The application will open in your browser at `http://localhost:8501`
### Environment Variables Required
- GROQ_API_KEY: Your Groq API key
- DATABRICKS_WORKSPACE_HOST: Databricks workspace URL used by the Jobs API
- DATABRICKS_TOKEN: Databricks personal access token or service principal token
- DATABRICKS_AI_GATEWAY: Databricks AI Gateway URL used by the configured LLM


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

### Adding More Agents
1. Create new agent file in `agents/` directory
2. Add to workflow in `supervisor_agent.py`
3. Update Streamlit UI in `app.py`