"""
Simple Python script to query the Ollama model using LangChain.
Based on instructions in copilot-instructions.md

Tech Stack:
- Python 3.12
- Model: llama3.2:1b-instruct-q4_K_M via Ollama
- Framework: LangChain
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.ollama import get_model_response


class QueryModel:
    """Simple model querying class using LangChain and Ollama."""
    
    def __init__(self, model_name: str = "llama3.2:1b-instruct-q4_K_M"):
        """
        Initialize the model.
        
        Args:
            model_name: The Ollama model to use
        """
        self.model_name = model_name
    
    def query(self, user_query: str) -> str:
        """
        Send a query to the model and get a response.
        
        Args:
            user_query: The user's question or query
            
        Returns:
            The model's response as a string
        """
        # Use the model connection utility to get response
        response = get_model_response(user_query, model_name=self.model_name)
        
        return response
    
    def interactive_session(self):
        """Start an interactive session to query the model."""
        print(f"Starting interactive session with {self.model_name}")
        print("Type 'exit' to quit.\n")
        
        while True:
            try:
                user_input = input("You: ").strip()
                
                if user_input.lower() == "exit":
                    print("Goodbye!")
                    break
                
                if not user_input:
                    continue
                
                print("Model: ", end="", flush=True)
                response = self.query(user_input)
                print(response)
                print()
                
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break


def main():
    """Main function to demonstrate model querying."""
    # Initialize the model
    model = QueryModel()
    
    # Example queries
    example_queries = [
        "What is India?"
        #,"Explain machine learning in simple terms."
        #,"How does an AI agent work?"
    ]
    
    print("=" * 60)
    print("Simple Model Query Demo")
    print("=" * 60)
    print()
    
    # Run example queries
    for query in example_queries:
        print(f"Query: {query}")
        print("-" * 60)
        response = model.query(query)
        print(f"Response: {response}")
        print()
    
    # Start interactive session
    print("\n" + "=" * 60)
    print("Starting Interactive Session")
    print("=" * 60)
    model.interactive_session()


if __name__ == "__main__":
    main()
