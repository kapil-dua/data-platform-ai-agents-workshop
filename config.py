"""
Configuration module for Data Platform AI Agents Application
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)


class Config:
    """Application configuration"""

    # Application settings
    REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "30"))
    
    # Agent settings

    MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "")

    OLLAMA_MODEL_ID = os.getenv("OLLAMA_MODEL_ID", "")

    # Groq API settings
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL_ID = os.getenv("GROQ_MODEL_ID", "")
    
    # Databricks API settings
    DATABRICKS_WORKSPACE_HOST = os.getenv("DATABRICKS_WORKSPACE_HOST", "")
    DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN", "")
    DATABRICKS_AI_GATEWAY = os.getenv("DATABRICKS_AI_GATEWAY", "")
    DATABRICKS_MODEL_ID = os.getenv("DATABRICKS_MODEL_ID", "")
    DATABRICKS_API_TIMEOUT = int(os.getenv("DATABRICKS_API_TIMEOUT", "30"))
    
    # Langfuse Observability settings
    LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "true").lower() == "true"
    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    LANGFUSE_BATCH_SIZE = int(os.getenv("LANGFUSE_BATCH_SIZE", "100"))
    LANGFUSE_FLUSH_INTERVAL = int(os.getenv("LANGFUSE_FLUSH_INTERVAL", "10"))

    # Fallback Prompts
    _FALLBACK_RCA_SYSTEM_PROMPT = """You are an expert data engineer performing root cause analysis on failed ETL jobs.
Analyze the job failure information and logs to determine:
1. The root cause - Brief explanation of why the job failed (2-3 sentences)
2. Specific recommendation - Actionable steps to prevent this failure in the future
3. Suggest Issue Severity level like Critical, High, Medium, Low

Provide your RCA analysis in a structured format with concise info and focused, Severity level summary less than 20 words."""
    _FALLBACK_RCA_USER_TEMPLATE = (
        "Job Name: {job_name}\n"
        "Run ID: {run_id}\n"
        "Status: {status}\n"
        "Error Message: {error_message}\n\n"
        "Job Logs:\n{logs}"
    )

    @classmethod
    def validate(cls):
        """Validate required configuration"""
        global MODEL_ID

        required_vars = [
            ("DATABRICKS_WORKSPACE_HOST", cls.DATABRICKS_WORKSPACE_HOST),
            ("DATABRICKS_TOKEN", cls.DATABRICKS_TOKEN),
        ]
        
        # Add model-specific requirements based on MODEL_PROVIDER
        if cls.MODEL_PROVIDER == "ollama":
            MODEL_ID = cls.OLLAMA_MODEL_ID
            required_vars.append(("MODEL_ID", cls.OLLAMA_MODEL_ID))
        elif cls.MODEL_PROVIDER == "groq":
            required_vars.append(("GROQ_API_KEY", cls.GROQ_API_KEY))
            required_vars.append(("MODEL_ID", cls.GROQ_MODEL_ID))
        elif cls.MODEL_PROVIDER == "databricks":
            required_vars.append(("DATABRICKS_API_KEY", cls.DATABRICKS_TOKEN))
            required_vars.append(("MODEL_ID", cls.DATABRICKS_MODEL_ID))
        
        missing = [var_name for var_name, var_value in required_vars if not var_value]

        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        return True