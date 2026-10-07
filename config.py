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

    JIRA_ENABLED = os.getenv("JIRA_ENABLED", "false").lower() == "true"
    # Atlassian Rovo MCP settings
    ATLASSIAN_MCP_URL = os.getenv("ATLASSIAN_MCP_URL", "https://mcp.atlassian.com/v2/mcp")
    ATLASSIAN_API_TOKEN = os.getenv("ATLASSIAN_API_TOKEN", "")
    ATLASSIAN_AUTH_HEADER = os.getenv("ATLASSIAN_AUTH_HEADER", "")
    ATLASSIAN_EMAIL = os.getenv("ATLASSIAN_EMAIL", "")
    ATLASSIAN_CLOUD_ID = os.getenv("ATLASSIAN_CLOUD_ID", "nagarro-dataai-1.atlassian.net")
    ATLASSIAN_PROJECT_KEY = os.getenv("ATLASSIAN_PROJECT_KEY", "")
    ATLASSIAN_ISSUE_TYPE = os.getenv("ATLASSIAN_ISSUE_TYPE", os.getenv("JIRA_ISSUE_TYPE", "Task"))
    
    # Langfuse Observability settings
    LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "true").lower() == "true"
    LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_BATCH_SIZE = int(os.getenv("LANGFUSE_BATCH_SIZE", "100"))
    LANGFUSE_FLUSH_INTERVAL = int(os.getenv("LANGFUSE_FLUSH_INTERVAL", "10"))

    # Fallback Prompts
    _FALLBACK_RCA_SYSTEM_PROMPT = """You are an expert data engineer performing root cause analysis on failed ETL jobs.

You will be given error logs, DAB job context, and Unity Catalog lineage.

CRITICAL RULE: Every path, table name, filename, system name, and config value you mention
MUST be copied exactly from the context. Never be generic — always use the exact values provided.

Your analysis must include:
1. ROOT CAUSE — cite exact error, exact expected vs actual values from context
2. DOWNSTREAM IMPACT — exact table/job names from UC lineage
3. RECOMMENDED FIX — numbered steps with exact paths and system names
4. SEVERITY — Critical/High/Medium/Low with one-line justification"""

    _FALLBACK_RCA_USER_TEMPLATE = (
        "Job Name: {job_name}\n"
        "Run ID: {run_id}\n"
        "Status: {status}\n"
        "Error Message: {error_message}\n\n"
        "=== JOB DESIGN CONTEXT (from DAB) ===\n"
        "{dab_context}\n\n"
        "=== RUNTIME LINEAGE CONTEXT (Unity Catalog) ===\n"
        "{uc_lineage}\n\n"
        "=== JOB LOGS ===\n"
        "{logs}"
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