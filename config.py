"""
Configuration module for ETL Monitoring Application
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Application configuration"""

    # Application settings
    REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "30"))
    
    # Agent settings
    MAX_ITERATIONS = 10

    # AWS settings
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    
    MODEL_TO_USE = os.getenv("MODEL_TO_USE", "")

    OLLAMA_MODEL_ID = os.getenv("OLLAMA_MODEL_ID", "")

    # Groq API settings
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL_ID = os.getenv("GROQ_MODEL_ID", "")
    
    # Databricks API settings
    DATABRICKS_HOST = os.getenv("DATABRICKS_HOST", "")
    DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN", "")
    DATABRICKS_MODEL_ID = os.getenv("DATABRICKS_MODEL_ID", "")
    
    # Langfuse Observability settings
    LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "true").lower() == "true"
    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    LANGFUSE_BATCH_SIZE = int(os.getenv("LANGFUSE_BATCH_SIZE", "100"))
    LANGFUSE_FLUSH_INTERVAL = int(os.getenv("LANGFUSE_FLUSH_INTERVAL", "10"))
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        # Base required vars
        required_vars = [
            ("AWS_ACCESS_KEY_ID", cls.AWS_ACCESS_KEY_ID),
            ("AWS_SECRET_ACCESS_KEY", cls.AWS_SECRET_ACCESS_KEY),
        ]
        
        # Add model-specific requirements based on MODEL_TO_USE
        if cls.MODEL_TO_USE == "groq":
            required_vars.append(("GROQ_API_KEY", cls.GROQ_API_KEY))
        elif cls.MODEL_TO_USE == "databricks":
            required_vars.extend([
                ("DATABRICKS_HOST", cls.DATABRICKS_HOST),
                ("DATABRICKS_TOKEN", cls.DATABRICKS_TOKEN),
                ("DATABRICKS_MODEL_ID", cls.DATABRICKS_MODEL_ID),
            ])
        
        missing = [var_name for var_name, var_value in required_vars if not var_value]
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        return True