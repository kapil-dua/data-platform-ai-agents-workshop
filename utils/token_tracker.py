"""
Token Usage Tracker
====================
Tracks LLM token consumption and estimated cost per workflow run,
with breakdown by node (supervisor, rca, evaluator).

Works without langchain_community — reads token counts directly from
AIMessage.response_metadata which all LangChain providers populate.

Usage:
    tracker = TokenTracker()

    # Wrap an LLM invoke call:
    response = llm.invoke(messages)
    tracker.record("rca", response)

    print(tracker.summary())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Cost per 1M tokens (USD) ──────────────────────────────────────────────────
_COSTS: dict[str, dict[str, float]] = {
    # Groq models
    "openai/gpt-oss-20b":       {"input": 0.075,  "output": 0.300},
    "openai/gpt-oss-120b":      {"input": 0.150,  "output": 0.600},
    # Databricks foundation models (approximate)
    "system.ai.meta-llama-3-1-8b-instruct": {"input": 0.100, "output": 0.300},
    # Default fallback
    "default":                  {"input": 0.100,  "output": 0.400},
}


def _get_rates() -> dict[str, float]:
    """Return cost rates for the currently configured model."""
    try:
        from config import Config
        model = getattr(Config, "GROQ_MODEL_ID", "") or getattr(Config, "DATABRICKS_MODEL_ID", "")
        return _COSTS.get(model, _COSTS["default"])
    except Exception:
        return _COSTS["default"]


def _extract_token_counts(response: Any) -> tuple[int, int]:
    """Extract (prompt_tokens, completion_tokens) from an LLM response.

    Reads from response_metadata which all LangChain providers populate.
    Returns (0, 0) if usage data is not available.
    """
    if response is None:
        return 0, 0

    # Standard location: response.response_metadata["token_usage"] or ["usage"]
    meta = getattr(response, "response_metadata", {}) or {}

    # OpenAI / Groq / Databricks AI Gateway
    usage = meta.get("token_usage") or meta.get("usage") or {}
    if usage:
        prompt     = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        completion = usage.get("completion_tokens") or usage.get("output_tokens") or 0
        return int(prompt), int(completion)

    # Fallback: usage_metadata on the message object itself
    usage_meta = getattr(response, "usage_metadata", {}) or {}
    if usage_meta:
        prompt     = usage_meta.get("input_tokens") or 0
        completion = usage_meta.get("output_tokens") or 0
        return int(prompt), int(completion)

    return 0, 0


@dataclass
class NodeUsage:
    """Accumulated token usage for a single graph node."""
    node:               str
    prompt_tokens:      int = 0
    completion_tokens:  int = 0
    total_tokens:       int = 0
    calls:              int = 0

    @property
    def estimated_cost_usd(self) -> float:
        rates = _get_rates()
        return (
            self.prompt_tokens     * rates["input"]  / 1_000_000
            + self.completion_tokens * rates["output"] / 1_000_000
        )


@dataclass
class TokenTracker:
    """Accumulates token usage across all LLM calls in a workflow run."""

    _nodes: dict[str, NodeUsage] = field(default_factory=dict)

    def reset(self) -> None:
        """Clear all accumulated usage — call between workflow runs."""
        self._nodes.clear()

    def record(self, node: str, response: Any) -> None:
        """Record token usage from an LLM response for the given node.

        Args:
            node:     Name of the graph node (e.g. "rca", "evaluator", "supervisor")
            response: The AIMessage returned by llm.invoke()
        """
        prompt, completion = _extract_token_counts(response)
        if node not in self._nodes:
            self._nodes[node] = NodeUsage(node=node)

        usage = self._nodes[node]
        usage.prompt_tokens     += prompt
        usage.completion_tokens += completion
        usage.total_tokens      += prompt + completion
        usage.calls             += 1

    def all_nodes(self) -> list[NodeUsage]:
        return list(self._nodes.values())

    @property
    def total_tokens(self) -> int:
        return sum(n.total_tokens for n in self._nodes.values())

    @property
    def total_cost_usd(self) -> float:
        return sum(n.estimated_cost_usd for n in self._nodes.values())

    def to_dict(self) -> dict[str, Any]:
        """Serialisable summary for storing in workflow state."""
        return {
            "total_tokens":   self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "nodes": {
                n.node: {
                    "calls":              n.calls,
                    "prompt_tokens":      n.prompt_tokens,
                    "completion_tokens":  n.completion_tokens,
                    "total_tokens":       n.total_tokens,
                    "estimated_cost_usd": round(n.estimated_cost_usd, 6),
                }
                for n in self._nodes.values()
            },
        }

    def summary(self) -> str:
        """Human-readable one-line summary."""
        return (
            f"Total: {self.total_tokens:,} tokens "
            f"(~${self.total_cost_usd:.4f} USD) "
            f"across {len(self._nodes)} node(s)"
        )
