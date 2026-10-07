"""
Groq LLM client implementation
"""
from langchain_groq import ChatGroq
from config import Config


class GroqClient:
    """Groq LLM client wrapper"""

    def __init__(self):
        """Initialize Groq LLM client"""
        self.llm = ChatGroq(
            groq_api_key=Config.GROQ_API_KEY,
            model=Config.GROQ_MODEL_ID,   # 'model' is the current param (model_name is deprecated alias)
            temperature=0.1,
        )
        print(f"[GroqClient] Initialized Groq with model: {Config.GROQ_MODEL_ID}")

    def get_llm(self):
        """Get the LLM instance"""
        return self.llm
