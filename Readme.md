# Multi-Agent ETL Monitoring Application

## Project Structure
```
etl_monitoring/
├── README.md
├── requirements.txt
├── .env.example
├── config/
│   └── config.py
├── agents/
│   ├── __init__.py
│   ├── supervisor_agent.py
│   ├── monitor_agent.py
│   └── rca_agent.py
├── utils/
│   ├── __init__.py
│   ├── aws_utils.py
│   └── llm_utils.py
└── app.py (Streamlit web interface)
```

etl_monitoring/
├── README.md                    # Project documentation
├── QUICKSTART.md               # Setup guide
├── requirements.txt             # Python dependencies
├── app.py                       # Streamlit web interface
├── .env                         # Environment template
├── test_agents.py              # Test script
├── config/
│   └── config.py               # Configuration management
├── agents/
│   ├── __init__.py
│   ├── supervisor_agent.py     # Supervisor with LangGraph workflow
│   ├── monitor_agent.py        # AWS Glue job monitoring
│   └── rca_agent.py            # Root cause analysis
├── utils/
│   ├── __init__.py
    ├── aws_utils.py            # AWS Glue/CloudWatch utilities
    └── llm_utils.py            # Groq LLM wrapper

## Setup Instructions

1. Install dependencies:
```bash
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