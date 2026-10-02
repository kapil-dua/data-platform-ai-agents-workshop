"""
Langfuse Tracing Utility Module

Provides simple helper functions for integrating Langfuse observability
with LangChain/LangGraph using CallbackHandler, and for pulling prompts
from Langfuse Prompt Management with automatic trace linking.
"""
from typing import Optional, Dict, Any, List, Tuple, Sequence, Union
from datetime import datetime
import uuid

from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
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


_LANGFUSE_CLIENT: Optional[Langfuse] = None


def _get_langfuse_client() -> Optional[Langfuse]:
    """Return a cached Langfuse client, or ``None`` if the SDK is disabled/misconfigured."""
    global _LANGFUSE_CLIENT

    if not Config.LANGFUSE_ENABLED:
        print("⚠️  Langfuse is disabled; no Langfuse client will be created")
        return None
    if not Config.LANGFUSE_PUBLIC_KEY or not Config.LANGFUSE_SECRET_KEY:
        print("⚠️  Langfuse is misconfigured; missing public or secret key")
        return None

    if _LANGFUSE_CLIENT is None:
        try:
            _LANGFUSE_CLIENT = Langfuse(
                public_key=Config.LANGFUSE_PUBLIC_KEY,
                secret_key=Config.LANGFUSE_SECRET_KEY,
                host=Config.LANGFUSE_HOST,
            )
        except Exception as e:
            print(f"⚠️  Could not initialize Langfuse client: {e}")
            _LANGFUSE_CLIENT = None

    return _LANGFUSE_CLIENT


def get_prompt_and_template(
    name: str,
    prompt_type: str = "text",
    label: str = "production",
    fallback_template: Optional[str] = None,
    fallback_messages: Optional[Sequence[Tuple[str, str]]] = None,
) -> Tuple[Optional[Any], Union[PromptTemplate, ChatPromptTemplate]]:
    """
    Fetch a prompt from Langfuse and wrap it in a LangChain template linked
    to the Langfuse prompt version for tracing.

    Follows the pattern documented at
    https://langfuse.com/docs/prompt-management/features/link-to-traces
    (LangChain Python) — passing ``metadata={"langfuse_prompt": ...}`` on
    the PromptTemplate lets the ``langfuse.langchain.CallbackHandler``
    associate every generation produced through the template with the
    correct prompt name and version in Langfuse.

    Args:
        name: Prompt name in Langfuse (e.g. ``"job-failure-rca-analysis"``).
        prompt_type: ``"text"`` or ``"chat"``.
        label: Which Langfuse label to fetch. Defaults to ``"production"``.
        fallback_template: LangChain template string used when Langfuse is
            unavailable and ``prompt_type == "text"``. Uses single-brace
            ``{var}`` LangChain syntax.
        fallback_messages: List of ``(role, template)`` tuples used when
            Langfuse is unavailable and ``prompt_type == "chat"``. Uses
            single-brace ``{var}`` LangChain syntax.

    Returns:
        Tuple of ``(langfuse_prompt, langchain_template)``. The first item
        is ``None`` when Langfuse is disabled or the fetch fails; in that
        case ``langchain_template`` is built from the fallback and no
        trace linking will occur (as documented for fallback prompts).
    """
    client = _get_langfuse_client()

    if client is not None:
        try:
            langfuse_prompt = client.get_prompt(name, label=label, type=prompt_type)

            if prompt_type == "chat":
                template = ChatPromptTemplate(
                    langfuse_prompt.get_langchain_prompt(),
                    metadata={"langfuse_prompt": langfuse_prompt},
                )
            else:
                template = PromptTemplate.from_template(
                    langfuse_prompt.get_langchain_prompt(),
                    metadata={"langfuse_prompt": langfuse_prompt},
                )

            print(
                f"✅ Loaded Langfuse prompt '{name}' "
                f"(version={langfuse_prompt.version}, label={label})"
            )
            return langfuse_prompt, template
        except Exception as e:
            print(
                f"⚠️  Falling back to hardcoded template for prompt '{name}' — "
                f"could not fetch from Langfuse: {e}"
            )

    if prompt_type == "chat":
        if not fallback_messages:
            raise ValueError(
                f"No Langfuse prompt available for '{name}' and no fallback_messages provided."
            )
        return None, ChatPromptTemplate.from_messages(list(fallback_messages))

    if not fallback_template:
        raise ValueError(
            f"No Langfuse prompt available for '{name}' and no fallback_template provided."
        )
    return None, PromptTemplate.from_template(fallback_template)

