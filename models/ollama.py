"""
Model connection utility for querying Ollama models using LangChain.
Handles initialization and invocation of LLM models.
"""

from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate


def get_model_response(query: str, model_name: str = "llama3.2:1b-instruct-q4_K_M", system_prompt: str = None) -> str:
    """
    Query the Ollama model and get a response.
    
    Args:
        query: The user's question or query
        model_name: The Ollama model to use (default: llama3.2:1b-instruct-q4_K_M)
        system_prompt: Optional system prompt template. If None, uses default helpful assistant prompt.
        
    Returns:
        The model's response as a string
    """
    # Initialize the model
    llm = OllamaLLM(model=model_name)
    
    # Use provided system prompt or default
    if system_prompt is None:
        system_prompt = "You are a helpful AI assistant. Answer the following query:\n\n{query}"
    
    # Create prompt template
    prompt_template = ChatPromptTemplate.from_template(system_prompt)
    
    # Create and invoke the chain
    chain = prompt_template | llm
    response = chain.invoke({"query": query})
    
    return response


def create_model_instance(model_name: str = "llama3.2:1b-instruct-q4_K_M") -> OllamaLLM:
    """
    Create and return an Ollama LLM instance.
    
    Args:
        model_name: The Ollama model to use
        
    Returns:
        An OllamaLLM instance
    """
    return OllamaLLM(model=model_name)


def create_prompt_template(system_prompt: str = None) -> ChatPromptTemplate:
    """
    Create a ChatPromptTemplate with optional custom system prompt.
    
    Args:
        system_prompt: Optional system prompt. If None, uses default.
        
    Returns:
        A ChatPromptTemplate instance
    """
    if system_prompt is None:
        system_prompt = "You are a helpful AI assistant. Answer the following query:\n\n{query}"
    
    return ChatPromptTemplate.from_template(system_prompt)
