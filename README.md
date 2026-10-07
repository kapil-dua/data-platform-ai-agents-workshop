# Data Engineering Platform — AI Agents

A LangGraph-based multi-agent application that monitors Databricks ETL pipelines, performs root cause analysis on failures using DAB context and Unity Catalog lineage, and creates Jira incidents — with a human-in-the-loop approval step and full Langfuse observability.

---

## Architecture

```
Supervisor Agent (ReAct — LLM-driven routing)
    │
    ├─► Worker 1: Monitor Agent
    │     Fetches all Databricks job/pipeline statuses via SDK.
    │     Surfaces each failed task individually for multi-task pipelines.
    │
    ├─► Worker 2: RCA Fan-Out
    │     Dispatches one RCA execution per failed task in parallel (Send API).
    │     Results merge via Annotated reducer (shared memory pattern).
    │
    ├─► Worker 3: RCA Evaluator
    │     Scores each RCA on Clarity, Actionability, Completeness (1-10, threshold 9.0).
    │     Context-aware: checks whether DAB context and UC lineage were actually used.
    │     Enforces WHAT + WHERE + ACCESS in every fix step.
    │     Retries below-threshold RCAs with per-criterion targeted feedback (max 3 iterations).
    │
    └─► Worker 4: Incident Agent
          Pauses for per-incident human review (HITL interrupt).
          Supports approve/reject per incident, severity override, context note.
          Creates Jira tickets via Atlassian Rovo MCP.
```

### RCA Context Sources

The RCA agent enriches every analysis with two context sources:

| Source | What it provides |
|---|---|
| **DAB YAML** (`.dab/etl_nightly_medallion/databricks.yml`) | Job design intent: source paths, filename patterns, upstream system, target tables, SLA, archive paths |
| **Unity Catalog Lineage** (`system.access.table_lineage`) | Runtime history: which tables were read/written, last successful write time, downstream consumers affected |

---

## Project Structure

```
data-platform-ai-agents/
├── app.py                          # Streamlit web interface
├── config.py                       # Configuration loader
├── ticker.py                       # Background scheduler (interval or cron)
├── ticker_manager.py               # Start/stop ticker from UI as subprocess
├── requirements.txt
├── .env.example
│
├── agents/
│   ├── supervisor_agent.py         # ReAct supervisor + LangGraph workflow
│   ├── monitor_agent.py            # Databricks job/pipeline monitoring
│   ├── rca_agent.py                # LLM root cause analysis (DAB + UC enriched)
│   ├── rca_evaluator_agent.py      # Context-aware evaluator-optimizer
│   └── incident_agent.py           # Jira incident creation (Rovo MCP)
│
├── tools/
│   ├── databricks_tools.py         # Databricks Jobs SDK (multi-task pipeline aware)
│   ├── dab_context_loader.py       # Reads DAB YAML for job context
│   ├── uc_lineage_fetcher.py       # Queries system.access.table_lineage
│   └── jira_tools.py              # Atlassian Rovo MCP client
│
├── models/
│   ├── llm_client.py               # LLM provider factory
│   ├── databricks.py               # Databricks AI Gateway
│   ├── groq.py                     # Groq (with rate-limit retry)
│   └── ollama.py                   # Ollama (local)
│
├── utils/
│   ├── langfuse_tracing.py         # Langfuse tracing + prompt management
│   └── durable_memory.py           # SQLite workflow audit store
│
├── scripts/
│   ├── setup.py                    # One-time workshop environment setup
│   ├── migrate_prompts_to_langfuse.py
│   └── test_jira_mcp.py
│
└── .dab/
    └── etl_nightly_medallion/
        └── databricks.yml          # DAB bundle — pipeline context for RCA agent
```

---

## Accounts & Tokens Required

### Quick Reference

| Service | Required | If Skipping |
|---|---|---|
| **Databricks** | ✅ Yes | Cannot run without it |
| **Groq** | ✅ Yes (if not using Databricks AI Gateway) | Set `MODEL_PROVIDER=databricks` |
| **Langfuse** | ⚪ Optional | Set `LANGFUSE_ENABLED=false` |
| **Atlassian Jira** | ⚪ Optional | Set `JIRA_ENABLED=false` |

**Minimum to run: Databricks workspace + one LLM provider.**

### 1. Databricks

**Sign up:** https://www.databricks.com/try-databricks — any email, no credit card, $400 DBU free credit.

- **Workspace URL** — shown on dashboard after provisioning. Format: `https://dbc-XXXXXXXX.cloud.databricks.com` → `DATABRICKS_WORKSPACE_HOST`
- **Personal Access Token** — User Settings → Developer → Access Tokens → Generate New Token → `DATABRICKS_TOKEN`
- **AI Gateway** — left sidebar → AI/ML → AI Gateway tab. Foundation models appear automatically ~5 mins after signup. Click a model → Make your first request → Python → copy `base_url` and `model` → `DATABRICKS_AI_GATEWAY` and `DATABRICKS_MODEL_ID`

### 2. Groq (free alternative LLM)

**Sign up:** https://console.groq.com → API Keys → Create API Key → `GROQ_API_KEY`

Recommended model: `openai/gpt-oss-20b` → `GROQ_MODEL_ID`

> If you hit rate limits (250K TPM on free tier), reduce `RCA_MAX_PARALLEL=1` in `.env`.

### 3. Langfuse (optional observability)

**Sign up:** https://cloud.langfuse.com → Settings → API Keys → `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY`

### 4. Atlassian Jira (optional incident creation)

**API Token:** https://id.atlassian.com/manage-profile/security/api-tokens → `ATLASSIAN_API_TOKEN`

Also needed: `ATLASSIAN_EMAIL`, `ATLASSIAN_CLOUD_ID` (e.g. `yourcompany.atlassian.net`), `ATLASSIAN_PROJECT_KEY`, `ATLASSIAN_ISSUE_TYPE`

---

## Setup Instructions

### Windows (Native — No WSL Required)

> Python 3.12 required. Download from https://www.python.org/downloads/ — check **"Add Python to PATH"**.

```powershell
# 1. Clone and enter the project
cd "path\to\data-platform-ai-agents"

# 2. Create virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env
notepad .env
```

Minimum `.env` values:
```env
MODEL_PROVIDER=groq
GROQ_API_KEY=gsk_xxxx
GROQ_MODEL_ID=openai/gpt-oss-20b
RCA_MAX_PARALLEL=2

DATABRICKS_WORKSPACE_HOST=https://dbc-XXXXXXXX.cloud.databricks.com
DATABRICKS_TOKEN=dapi_xxxx

JIRA_ENABLED=false
LANGFUSE_ENABLED=false
```

```powershell
# 4. Run the one-time demo environment setup (~5-6 minutes)
python scripts\setup.py

# 5. (Optional) Upload RCA prompt to Langfuse if LANGFUSE_ENABLED=true
python scripts\migrate_prompts_to_langfuse.py

# 6. Run the app
streamlit run app.py
```

---

### macOS / Linux / WSL

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env

python scripts/setup.py
streamlit run app.py
```

---

## Demo Environment Setup (`scripts/setup.py`)

Run once per workspace. Creates the full medallion architecture demo environment:

| Step | What it does | Time |
|---|---|---|
| 1 | Creates Unity Catalog: `demo_etl` catalog + `raw` / `cleansed` / `conformed` schemas | ~5s |
| 2 | Creates 5 Delta tables (customers, inventory, sales in raw; revenue_export, inventory_daily in cleansed) | ~30s |
| 3 | Seeds tables with realistic sample data | ~30s |
| 4 | Uploads 5 medallion notebooks to `/Shared/demo_etl/` | ~10s |
| 5 | Generates DAB YAML bundle to `.dab/etl_nightly_medallion/databricks.yml` | instant |
| 6 | Creates and runs the `etl_nightly_medallion` multi-task pipeline | ~5 min |

**Pipeline task layout:**
```
raw_to_cleansed_customers    ──────────────────────────────────────► (no downstream — succeeds)
raw_to_cleansed_inventory    ──────────────────► cleansed_to_conformed_inventory (succeeds)
raw_to_cleansed_sales        ──────────────────► cleansed_to_conformed_revenue   (succeeds)
         ↑ FAILS                                           ↑ FAILS
   0 incoming records                             0 files matching
   (WMS delivery issue)                           revenue_export_YYYY-MM-DD.csv
                                                  (filename format changed)
raw_to_cleansed_sales → FAILS
   AnalysisException: schema 'confromed_sales' does not exist (typo in config)
```

The failing tasks raise realistic premature-exit errors (0 records found, schema not found). The RCA agent derives the root cause from the DAB context and UC lineage — not from hardcoded error messages.

---

## Running the Application

### Manual mode
Click **▶️ Run Monitoring Now** in the sidebar. The full pipeline runs end to end.

### Background ticker mode
The ticker runs on a schedule and writes results to SQLite. The UI reads from SQLite.

```powershell
# Configure schedule in UI sidebar → ⏱️ Background Ticker
# Then click ▶ Start Ticker — launches as a detached subprocess
# Or run manually:
python ticker.py --interval 10   # every 10 minutes
python ticker.py --once          # run once immediately
```

---

## Agent Workflow

```
Supervisor [ReAct] ──► Monitor ──► RCA Fan-Out ──► rca_evaluator ──► [HITL] ──► Incident
                                      (×N parallel)   (retry loop)    (approve/reject
                                                                        per incident)
```

**Human Review controls (when `monitor_analyze_incident` runs):**
- Approve or reject each incident individually
- Override LLM-assigned severity
- Add a context note (appended to the Jira ticket description)

---

## Key Configuration

```env
# LLM provider
MODEL_PROVIDER=groq | databricks | ollama

# Parallel RCA — reduce if hitting rate limits
RCA_MAX_PARALLEL=2

# Evaluator quality threshold (1-10)
RCA_EVAL_THRESHOLD=9.0
RCA_EVAL_MAX_ITERATIONS=3

# Background ticker
TICKER_MODE=interval | cron
TICKER_INTERVAL_MIN=30
TICKER_CRON_TIME=06:00

# Optional services
JIRA_ENABLED=false
LANGFUSE_ENABLED=false
```

---

## Agentic Patterns Demonstrated

| Pattern | Where |
|---|---|
| **ReAct** — LLM decides routing | `supervisor_agent.py` `_react_supervisor_node` |
| **Shared Memory** — Annotated reducers | `SupervisorState` in `supervisor_agent.py` |
| **Parallel Fan-out** — Send API | `_fan_out_rca` in `supervisor_agent.py` |
| **Evaluator-Optimizer** — critique loop | `rca_evaluator_agent.py` + `_rca_evaluator_node` |
| **Human-in-the-Loop** — interrupt/resume | `_incident_node` in `supervisor_agent.py` |
| **DAB Context** — job design intent | `tools/dab_context_loader.py` |
| **UC Lineage** — runtime upstream/downstream | `tools/uc_lineage_fetcher.py` |
