"""
Groq LLM client implementation with rate-limit retry.
"""
import time
from langchain_groq import ChatGroq
from config import Config


class GroqClient:
    """Groq LLM client wrapper with automatic rate-limit retry."""

    def __init__(self):
        base_llm = ChatGroq(
            groq_api_key=Config.GROQ_API_KEY,
            model=Config.GROQ_MODEL_ID,
            temperature=0.1,
        )
        # Use LangChain's built-in retry — handles 429s transparently
        # while keeping the LLM as a proper Runnable for chaining
        self.llm = base_llm.with_retry(
            retry_if_exception_type=(Exception,),
            wait_exponential_jitter=True,
            stop_after_attempt=4,
        )
        print(f"[GroqClient] Initialized Groq with model: {Config.GROQ_MODEL_ID}")

    def get_llm(self):
        return self.llm
