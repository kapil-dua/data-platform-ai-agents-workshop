"""Ollama model initialization utility."""

from langchain_ollama import OllamaLLM
from config import Config

class OllamaClient:
    """Ollama LLM client wrapper"""
    
    def __init__(self):
        """Initialize Ollama LLM client"""
        self.llm = OllamaLLM(model=Config.OLLAMA_MODEL_ID)
        print(f"[OllamaClient] Initialized Ollama with model: {Config.OLLAMA_MODEL_ID}")
    
    def get_llm(self):
        """Get the LLM instance"""
        return self.llm