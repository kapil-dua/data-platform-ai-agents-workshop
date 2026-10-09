"""
Token Usage Tracker
====================
Tracks LLM token consumption and estimated cost per workflow run,
with breakdown by node (supervisor, rca, evaluator).

Usage:
    tracker = TokenTracker()

    with tracker.track("rca"):
        result = llm.invoke(messages)

    print(tracker.summary())

The tracker accumulates usage across multiple calls within the same context.
Call tracker.reset() between workflow runs.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from langchain_community.callbacks import get_openai_callback


# ── Cost per 1M tokens (USD) — update as pricing changes ─────────────────────
# Groq pricing (as of Oct 2026)
_GROQ_COSTS = {
    "openai/gpt-oss-20b":  {"input": 0.075, "output": 0.30},
    "openai/gpt-oss-120b": {"input": 0.150, "output": 0.60},
    "default":             {"input": 0.100, "output": 0.40},
}
# Databricks AI Gateway — varies by model, use approximate
_DATABRICKS_COSTS = {
    "default": {"input": 0.100, "output": 0.30},
}


@dataclass
class NodeUsage:
    """Token usage for a single node."""
    node:          str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens:  int = 0
    calls:         int = 0

    @property
    def estimated_cost_usd(self) -> float:
        from config import Config
        model = getattr(Config, "GROQ_MODEL_ID", "") or getattr(Config, "DATABRICKS_MODEL_ID", "")
        provider = getattr(Config, "MODEL_PROVIDER", "groq")
        costs = _GROQ_COSTS if provider == "groq" else _DATABRICKS_COSTS
        rates = costs.get(model, costs["default"])
        return (
            self.prompt_tokens * rates["input"] / 1_000_000
            + self.completion_tokens * rates["output"] / 1_000_000
        )


@dataclass
class TokenTracker:
    """Accumulates token usage across all LLM calls in a workflow run."""

    _nodes: dict[str, NodeUsage] = field(default_factory=dict)

    def reset(self) -> None:
        """Clear all accumulated usage — call between workflow runs."""
        self._nodes.clear()

    @contextmanager
    def track(self, node: str):
        """Context manager — track token usage for a named node.

        Usage:
            with tracker.track("rca"):
                llm.invoke(messages)
        """
        if node not in self._nodes:
            self._nodes[node] = NodeUsage(node=node)

        try:
            with get_openai_callback() as cb:
                yield
            # Accumulate after the context exits
            usage = self._nodes[node]
            usage.prompt_tokens     += cb.prompt_tokens
            usage.completion_tokens += cb.completion_tokens
            usage.total_tokens      += cb.total_tokens
            usage.calls             += 1
        except ImportError:
            # get_openai_callback not available — track nothing, don't break
            yield
        except Exception:
            # Never let token tracking break the actual workflow
            yield

    def get_node(self, node: str) -> NodeUsage | None:
        return self._nodes.get(node)

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
