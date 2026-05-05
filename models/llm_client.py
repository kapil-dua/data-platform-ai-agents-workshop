"""
LLM client factory for selecting between different LLM providers
"""
from langchain_core.messages import HumanMessage, SystemMessage
from config import Config


class LLMClient:
    """LLM client factory"""
    
    MODEL_TO_USE = Config.MODEL_TO_USE
    
    def __init__(self):
        """Initialize LLM client based on configuration"""
        if self.MODEL_TO_USE == "ollama":
            from models.ollama import create_model_instance
            self.llm = create_model_instance(model_name=Config.OLLAMA_MODEL_ID)
        elif self.MODEL_TO_USE == "groq":
            from models.groq import GroqClient
            self._client = GroqClient()
            self.llm = self._client.get_llm()
        else:
            raise ValueError(f"Unknown model: {self.MODEL_TO_USE}")
    
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