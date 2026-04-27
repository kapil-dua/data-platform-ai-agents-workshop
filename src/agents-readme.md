## How It Works

### Agent Workflow

1. **Supervisor Agent** starts the workflow
2. **Monitor Agent** checks all AWS Glue job statuses
3. **RCA Agent** analyzes logs for failed jobs
4. **Supervisor Agent** generates final executive report

### Features

- **Real-time Monitoring**: Click "Run Monitoring Now" to trigger workflow
- **Auto-refresh**: Enable automatic monitoring at set intervals
- **Detailed RCA**: Get AI-powered root cause analysis for failures
- **Executive Reports**: Download comprehensive reports

## Project Structure Explained

```
etl_monitoring/
├── app.py                      # Streamlit web interface
├── config/
│   └── config.py               # Configuration management
├── agents/
│   ├── supervisor_agent.py     # Coordinates workflow
│   ├── monitor_agent.py        # Monitors Glue jobs
│   └── rca_agent.py            # Performs RCA
└── utils/
    ├── aws_utils.py            # AWS Glue/CloudWatch utilities
    └── llm_utils.py            # Groq LLM client wrapper
```

## Key Components

### Supervisor Agent
- Uses LangGraph to orchestrate workflow
- Routes tasks to appropriate worker agents
- Generates final reports

### Monitor Agent
- Queries AWS Glue API for job statuses
- Identifies failed jobs
- Uses LLM to create intelligent summaries

### RCA Agent
- Retrieves CloudWatch logs for failed jobs
- Uses LLM to analyze logs and identify root causes
- Provides actionable recommendations

## Customization

### Changing LLM Model
Edit `config/config.py`:
```python
GROQ_MODEL = "llama-3.1-8b-instant"  # Change to other Groq models
```

### Adjusting Refresh Interval
Edit `.env`:
```
REFRESH_INTERVAL=300  # seconds
```

### Adding More Agents
1. Create new agent file in `agents/` directory
2. Add to workflow in `supervisor_agent.py`
3. Update Streamlit UI in `app.py`

## Troubleshooting

### AWS Credentials Error
- Verify AWS credentials in `.env`
- Ensure IAM user has permissions for Glue and CloudWatch

### Groq API Error
- Check GROQ_API_KEY is valid
- Verify API rate limits

### No Jobs Found
- Confirm you have AWS Glue jobs in your account
- Check AWS region is correct

## Next Steps

- Add email notifications for critical failures
- Implement job scheduling recommendations
- Add historical trend analysis
- Create custom alert rules