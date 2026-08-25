"""Ollama model initialization utility."""

from langchain_ollama import OllamaLLM


def create_model_instance(model_name: str = "llama3.2:1b-instruct-q4_K_M") -> OllamaLLM:
    """
    Create and return an Ollama LLM instance.

    Args:
        model_name: The Ollama model to use.

    Returns:
        An ``OllamaLLM`` instance.
    """
    return OllamaLLM(model=model_name)
