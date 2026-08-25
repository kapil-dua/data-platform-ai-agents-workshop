"""
Databricks LLM client implementation using AI Gateway (OpenAI-compatible endpoint)
"""
from langchain_openai import ChatOpenAI
from config import Config


class DatabricksClient:
    """Databricks AI Gateway LLM client wrapper"""
    
    def __init__(self):
        """Initialize Databricks AI Gateway client via OpenAI-compatible endpoint"""
        # Databricks AI Gateway provides an OpenAI-compatible API
        # The endpoint should end with /ai-gateway/mlflow/v1
        # Note: Databricks AI Gateway API doesn't support max_completion_tokens parameter
        self.llm = ChatOpenAI(
            base_url=Config.DATABRICKS_AI_GATEWAY,
            api_key=Config.DATABRICKS_TOKEN,
            model=Config.DATABRICKS_MODEL_ID,
            temperature=0.1
        )
        print(f"[DatabricksClient] Initialized Databricks AI Gateway with model: {Config.DATABRICKS_MODEL_ID}")
    
    def get_llm(self):
        """Get the LLM instance"""
        return self.llm
