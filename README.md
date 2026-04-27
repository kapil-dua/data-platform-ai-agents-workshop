# Multi-Agent ETL Monitoring Application

## Project Structure
```
ai-agents-etl-poc/
├── README.md                   # Project documentation
├── requirements.txt            # Python dependencies
├── app.py                      # Streamlit web interface
├── config.py                   # Configuration settings
├── .env.example                # Environment template
├── .env                        # Environment variables (local)
├── .gitignore                  # Git ignore file
├── agents/
│   ├── __init__.py
│   ├── agents-readme.md        # Agents documentation
│   ├── supervisor_agent.py     # Supervisor with LangGraph workflow
│   ├── chat_agent.py           # Chat agent
│   ├── monitor_agent.py        # AWS Glue job monitoring agent
│   └── rca_agent.py            # Root cause analysis agent
├── utils/
│   ├── __init__.py
│   ├── aws_utils.py            # AWS Glue/CloudWatch utilities
│   └── llm_utils.py            # Groq LLM wrapper
├── infra/                      # Infrastructure files
├── tests/
│   └── test_agents.py          # Agent tests
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
streamlit run src/app.py
```
The application will open in your browser at `http://localhost:8501`
`
## Environment Variables Required
- GROQ_API_KEY: Your Groq API key
- AWS_ACCESS_KEY_ID: AWS access key
- AWS_SECRET_ACCESS_KEY: AWS secret key
- AWS_REGION: AWS region (default: us-east-1)

## Features
- Supervisor agent coordinates workflow
- Monitor agent tracks AWS Glue job status
- RCA agent analyzes failed job logs
- Real-time Streamlit dashboard
