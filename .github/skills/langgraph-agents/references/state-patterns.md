# State Management Patterns

Effective state design is critical for multi-agent workflows. Use TypedDict for all state definitions.

## Pattern 1: Simple Task Agent State

For agents that process data sequentially without complex routing.

```python
from typing import TypedDict

class MonitorAgentState(TypedDict):
    """State for job monitoring workflow"""
    # Input
    job_ids: list[str]
    
    # Processing
    jobs_data: dict
    failed_jobs: list
    
    # Output
    monitor_summary: str
```

**When to use**: Single-purpose agents with linear workflows (gather → analyze → report).

---

## Pattern 2: Conditional Routing State

For agents that need to route between multiple paths based on intermediate results.

```python
from typing import TypedDict, Literal

class RCAAgentState(TypedDict):
    """State with routing information"""
    # Input
    failed_job_id: str
    
    # Processing
    job_details: dict
    error_logs: list[str]
    root_causes: list[str]
    
    # Routing field (used by conditional_edges)
    next_step: Literal["analyze_logs", "check_dependencies", "format_report", "end"]
```

**When to use**: Agents with multiple decision points that route between different analysis paths.

---

## Pattern 3: Supervisor Orchestration State

For supervisor agents coordinating multiple task agents.

```python
from typing import TypedDict, Literal

class SupervisorState(TypedDict):
    """State for multi-agent supervision"""
    # Initial request
    task: str  # "monitor" | "rca" | "create_incident"
    user_query: str
    
    # Task-specific data (flexible)
    data: dict
    
    # Results from task agents
    task_results: dict
    monitor_summary: str
    rca_results: list
    
    # Routing
    next_agent: Literal["monitor", "rca", "incident", "report", "end"]
    
    # Final output
    final_report: str
```

**When to use**: Multi-level orchestration where supervisor delegates to specialized agents.

---

## Pattern 4: Progressive Data Enrichment

For workflows that gather, enrich, then transform data.

```python
from typing import TypedDict
from datetime import datetime

class DataEnrichmentState(TypedDict):
    """Progressive enrichment workflow"""
    # Original data
    raw_data: dict
    
    # Enrichment layers (added progressively)
    with_metadata: dict
    with_analysis: dict
    with_recommendations: dict
    
    # Timestamps for tracking
    started_at: datetime
    enriched_at: datetime
    
    # Quality metrics
    data_quality_score: float
    warning_count: int
```

**When to use**: Complex data pipelines where each step adds value.

---

## Pattern 5: Error Handling & Recovery

For workflows that need detailed error tracking.

```python
from typing import TypedDict
from dataclasses import dataclass

@dataclass
class ErrorRecord:
    step: str
    message: str
    timestamp: str
    recoverable: bool

class RobustAgentState(TypedDict):
    """State with comprehensive error tracking"""
    # Normal fields
    task: str
    results: dict
    
    # Error tracking
    errors: list[ErrorRecord]
    warnings: list[str]
    
    # Recovery strategy
    retry_count: int
    recovery_action: str  # "retry" | "skip" | "fail"
```

**When to use**: Production workflows where reliability and debuggability are critical.

---

## Pattern 6: Batch Processing State

For agents processing collections of items.

```python
from typing import TypedDict

class BatchProcessingState(TypedDict):
    """State for parallel/batch operations"""
    # Batch info
    total_items: int
    batch_size: int
    
    # Processing
    pending_items: list
    processing_items: list
    completed_items: list
    failed_items: list
    
    # Results
    results: dict  # item_id -> result
    failure_reasons: dict  # item_id -> reason
    
    # Progress
    progress_percent: float
    eta_seconds: int
```

**When to use**: Workflows that process multiple jobs/records with progress tracking.

---

## Design Principles

### 1. Make State Explicit
```python
# ✅ Good: All fields documented
class State(TypedDict):
    """State for job monitoring"""
    job_ids: list[str]          # Input: IDs to monitor
    jobs_data: dict             # Output: Job details from AWS
    failed_count: int           # Derived: Count of failures
    next_step: Literal[...]     # Routing: Where to go next

# ❌ Bad: Vague, undocumented fields
class State(TypedDict):
    data: dict
    result: dict
    status: str
```

### 2. Use Literal for Routing
```python
# ✅ Good: Type-safe routing
next_step: Literal["analyze", "format", "end"]

def route_function(state: State) -> str:
    if state.get("errors"):
        return "format"
    return "analyze"

# ❌ Bad: String errors at runtime
next_step: str  # Could be anything
```

### 3. Separate Input/Output/Internal
```python
# ✅ Good: Clear data flow
class State(TypedDict):
    # Input (from caller)
    user_request: str
    
    # Processing (intermediate)
    parsed_request: dict
    search_results: list
    
    # Output (for caller)
    final_answer: str
    confidence: float

# ❌ Bad: Mixed concerns
class State(TypedDict):
    request: str
    data: dict
    answer: str
```

### 4. Track State Transitions
```python
# ✅ Good: Know where we are
from datetime import datetime

class State(TypedDict):
    task: str
    current_step: str  # e.g., "gathering_data", "analyzing", "done"
    step_start_time: datetime
    previous_steps: list[str]

# ❌ Bad: No visibility into flow
class State(TypedDict):
    task: str
    data: dict
```

---

## Common Mistakes

| Mistake | Problem | Fix |
|---------|---------|-----|
| Mutating state in nodes | Breaks immutability assumption | Always return `{**state, "field": new_value}` |
| dict instead of TypedDict | No type checking, harder to debug | Define TypedDict with all fields |
| Too many fields in state | Confusing data flow, hard to reason about | Split into multiple focused states |
| Missing routing field | Can't conditionally route | Add `Literal` field for decision points |
| Storing functions in state | StateGraph can't serialize | Store data, call functions in nodes |
| No error fields | Silent failures | Include `errors: list` for tracking issues |

---

## Validation Checklist

When designing agent state, verify:

- ✅ All fields documented with purpose
- ✅ Input fields clearly marked
- ✅ Output fields for downstream use
- ✅ Routing field (if conditional edges used)
- ✅ Error tracking fields
- ✅ No function/object references
- ✅ Immutable field types only
- ✅ TypedDict, not plain dict
