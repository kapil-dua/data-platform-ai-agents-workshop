"""
Langfuse Tracing Utility Module

Provides simple helper functions for integrating Langfuse observability
with LangChain/LangGraph using CallbackHandler.
"""
from typing import Optional, Dict, Any, List
import os
from datetime import datetime
import uuid

from langfuse.langchain import CallbackHandler
from langfuse import Langfuse

from config import Config


def generate_session_id(prefix: str = "session") -> str:
    """
    Generate a clean session ID for Langfuse
    
    Args:
        prefix: Prefix for the session ID (default: "session")
        
    Returns:
        A clean session ID with timestamp and UUID
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    return f"{prefix}_{timestamp}_{unique_id}"


def generate_langfuse_trace_id() -> str:
    """
    Generate a valid Langfuse trace ID (32-character hex string)
    
    Returns:
        A valid trace ID for Langfuse
    """
    try:
        client = Langfuse()
        return client.create_trace_id()
    except Exception:
        # Fallback: generate a random 32-char hex string
        import uuid
        return uuid.uuid4().hex[:32]


def get_langfuse_handler(
    user_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[CallbackHandler]:
    """
    Create a Langfuse CallbackHandler for LangChain integration

    Args:
        session_id: Session ID to group related traces
        user_id: User identifier for tracing
        tags: List of tags for filtering and organization
        metadata: Custom metadata dictionary

    Returns:
        CallbackHandler configured with Langfuse, or None if disabled
    """
    if not Config.LANGFUSE_ENABLED:
        return None

    try:
        # Validate Langfuse credentials
        if not Config.LANGFUSE_PUBLIC_KEY or not Config.LANGFUSE_SECRET_KEY:
            print("❌ Langfuse credentials not configured")
            return None

        # Build trace context with valid trace ID
        trace_context = None
        trace_id = None

        if user_id or tags or metadata:
            # Generate a valid Langfuse trace ID (32-char hex)
            trace_id = generate_langfuse_trace_id()
            
            trace_context = {
                "trace_id": trace_id,
            }
            
            # Add user_id, tags, and metadata to trace context if provided
            if user_id:
                trace_context["user_id"] = user_id
            if tags:
                trace_context["tags"] = tags
            if metadata:
                trace_context["metadata"] = metadata

        # Create handler with public_key and trace_context
        handler_kwargs = {
            "public_key": Config.LANGFUSE_PUBLIC_KEY,
        }
        
        # Add trace_context if available
        if trace_context:
            handler_kwargs["trace_context"] = trace_context
        
        handler = CallbackHandler(**handler_kwargs)
        
        return handler

    except Exception as e:
        print(f"❌ Error creating Langfuse handler: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_agent_handler(
    agent_name: str,
    session_id: Optional[str] = None,
    additional_tags: Optional[List[str]] = None,
) -> Optional[CallbackHandler]:
    """
    Create a CallbackHandler preconfigured for a specific agent

    Args:
        agent_name: Name of the agent (e.g., "Supervisor Agent")
        session_id: Session ID for trace grouping
        additional_tags: Extra tags beyond the agent name

    Returns:
        Configured CallbackHandler or None if Langfuse is disabled
    """
    tags = [agent_name.lower().replace(" ", "_"), "etl_monitoring"]

    if additional_tags:
        tags.extend(additional_tags)

    metadata = {
        "agent_name": agent_name,
        "component": "agent",
    }

    if session_id:
        metadata["langfuse_session_id"] = session_id
        metadata["langfuse_trace_name"] = f"{agent_name}"

    return get_langfuse_handler(
        tags=tags,
        metadata=metadata,
    )


def verify_langfuse_connection() -> bool:
    """
    Verify Langfuse connection and credentials
    
    Returns:
        True if connection is successful, False otherwise
    """
    if not Config.LANGFUSE_ENABLED:
        print("⚪ Langfuse is disabled")
        return True
    
    try:
        from langfuse import Langfuse
        
        client = Langfuse(
            public_key=Config.LANGFUSE_PUBLIC_KEY,
            secret_key=Config.LANGFUSE_SECRET_KEY,
            host=Config.LANGFUSE_HOST
        )
        
        # Verify connection with auth check
        client.auth_check()
        
        print(f"✅ Langfuse connection successful")
        print(f"   Host: {Config.LANGFUSE_HOST}")
        print(f"   Public Key: {Config.LANGFUSE_PUBLIC_KEY[:15]}...")
        
        client.flush()
        return True
        
    except Exception as e:
        print(f"❌ Langfuse connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False
