"""Shared contracts for data-platform agents."""
from typing import Any, Protocol, TypedDict


class AgentResult(TypedDict):
    """Structured record describing one agent execution."""
    agent: str
    status: str
    message: str
    data: dict[str, Any]


class Agent(Protocol):
    """Contract implemented by every worker agent."""
    name: str
    description: str

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent using the shared workflow state."""
        ...