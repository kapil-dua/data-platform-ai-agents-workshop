"""
LLM utility functions for Groq API integration
"""
from langchain_groq import ChatGroq
"""from langchain.prompts import ChatPromptTemplate"""
from langchain_core.prompts import ChatPromptTemplate
from config.config import Config


class LLMClient:
    """Groq LLM client wrapper"""
    
    def __init__(self):
        """Initialize Groq LLM client"""
        self.llm = ChatGroq(
            groq_api_key=Config.GROQ_API_KEY,
            model_name=Config.GROQ_MODEL,
            temperature=0.1,
            max_tokens=2000
        )
    
    def get_llm(self):
        """Get the LLM instance"""
        return self.llm
    
    def invoke_with_prompt(self, system_message: str, user_message: str) -> str:
        """Invoke LLM with system and user messages"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            ("user", user_message)
        ])
        
        chain = prompt | self.llm
        response = chain.invoke({})
        
        return response.content