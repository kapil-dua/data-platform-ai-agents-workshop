"""
LLM client factory for selecting between different LLM providers
"""
from langchain_core.messages import HumanMessage, SystemMessage
from config import Config


class LLMClient:
    """LLM client factory"""
    
    MODEL_PROVIDER = Config.MODEL_PROVIDER
    
    def __init__(self):
        """Initialize LLM client based on configuration"""
        if self.MODEL_PROVIDER == "ollama":
            from models.ollama import OllamaClient
            self._client = OllamaClient()
            self.llm = self._client.get_llm()
        elif self.MODEL_PROVIDER == "groq":
            from models.groq import GroqClient
            self._client = GroqClient()
            self.llm = self._client.get_llm()
        elif self.MODEL_PROVIDER == "databricks":
            from models.databricks import DatabricksClient
            self._client = DatabricksClient()
            self.llm = self._client.get_llm()
        else:
            raise ValueError(f"Unknown model: {self.MODEL_PROVIDER}")
    
    def get_llm(self):
        """Get the LLM instance"""
        return self.llm
    
    def invoke_with_prompt(self, system_message: str, user_message: str) -> str:
        """Invoke LLM with system and user messages"""
        messages = [
            SystemMessage(content=system_message),
            HumanMessage(content=user_message)
        ]
        
        response = self.llm.invoke(messages)
        
        # Handle response - it should be an AIMessage object with content attribute
        if hasattr(response, 'content'):
            return response.content
        elif isinstance(response, str):
            return response
        else:
            return str(response)