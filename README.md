# Data Engineering Platform AI Agents Application

## Project Structure
```
data-ops-ai-agents/
├── README.md                   # Project documentation
├── requirements.txt            # Python dependencies
├── .env.example                # Environment template
├── app.py                      # Streamlit web interface
├── config.py                   # Configuration settings
├── agents/
│   ├── __init__.py
│   ├── agents-readme.md        # Agent-specific documentation
│   ├── supervisor_agent.py     # Supervisor with LangGraph workflow
│   ├── monitor_agent.py        # Databricks job monitoring agent
│   ├── rca_agent.py            # Root cause analysis agent
│   └── incident_agent.py       # Incident creation agent
├── tools/
│   ├── __init__.py
│   ├── databricks_tools.py     # Databricks Jobs API utilities
│   └── llm_utils.py            # Groq LLM wrapper
├── models/
│   └── ollama.py               # Ollama model integration
│   └── databricks.py           # Databricks model integration
├── tests/
│   └── test_agents.py          # Agent tests
└── scripts/                    # Utility scripts for setup and deployment
```

## Accounts & Tokens Required

Before running the application, you need to create accounts and generate tokens for the following services. All are free to sign up.

### Quick Reference

| Service | Required for Demo | If Skipping |
|---|---|---|
| **Databricks** | ✅ Yes — data platform + LLM | Cannot run without it |
| **Groq** | ✅ Yes — alternative LLM (use if no Databricks AI Gateway) | Set `MODEL_PROVIDER=databricks` to skip |
| **Langfuse** | ⚪ Optional | Set `LANGFUSE_ENABLED=false` |
| **Atlassian Jira** | ⚪ Optional | Set `JIRA_ENABLED=false` |

**Minimum setup to get the demo running: Databricks + one LLM provider (Databricks AI Gateway or Groq).**
Set `LANGFUSE_ENABLED=false` and `JIRA_ENABLED=false` and skip those sections entirely if short on time.

### 1. Databricks (Data Platform + LLM)

**Sign up:** https://www.databricks.com/try-databricks
- Use any email (personal or work), no credit card required
- Choose AWS as the cloud provider
- Workspace provisions in ~10 minutes
- Free trial includes $400 in DBU credits

**Get the Workspace URL:**
- Visible on your Databricks dashboard after provisioning
- Format: `https://dbc-XXXXXXXX.cloud.databricks.com`
- → `DATABRICKS_WORKSPACE_HOST` in `.env`

**Generate a Personal Access Token:**
- Top-right corner → your username → **Settings**
- **Developer** → **Access Tokens** → **Generate New Token**
- Give it a name (e.g. `workshop`), set expiry to 90 days
- Copy immediately — shown only once
- → `DATABRICKS_TOKEN` in `.env`

**Get the AI Gateway URL + Model ID:**
- Left sidebar → **Machine Learning** → **Serving** → **AI Gateway** tab
- Databricks pre-provisions Foundation Models automatically — wait ~10 mins after signup for them to appear
- Look for `system.ai.meta-llama-3-1-8b-instruct` (or any `*-instruct` chat model)
- Click on the model to view its endpoint details
- Gateway base URL format: `https://dbc-XXXXXXXX.cloud.databricks.com/ai-gateway/mlflow/v1`
- → `DATABRICKS_AI_GATEWAY` and `DATABRICKS_MODEL_ID` in `.env`

**Create some jobs (so Monitor Agent has data):**
- Left sidebar → **Workflows** → **Create Job**
- Create 2-3 simple jobs — run one successfully, let one fail (e.g. point it to a non-existent notebook path)
- This gives the Monitor and RCA agents real data to work with

---

### 2. Groq (Alternative LLM Provider — Free)

Use this if Databricks AI Gateway is not available or as a backup.

**Sign up:** https://console.groq.com
- Google or GitHub login supported

**Generate API Key:**
- Left sidebar → **API Keys** → **Create API Key**
- Give it a name (e.g. `flo-workshop`)
- Copy immediately — shown only once
- → Set MODEL_PROVIDER=groq and `GROQ_API_KEY` in `.env`

**Recommended model:** `llama-3.1-8b-instant`
- → `GROQ_MODEL_ID` in `.env`

---

### 3. Langfuse (Observability — Optional)

Used for tracing agent execution and managing LLM prompts. The app runs fine without it — set `LANGFUSE_ENABLED=false` to skip.

**Sign up:** https://cloud.langfuse.com
- Free tier available, no credit card required

**Get API Keys:**
- After login → **Settings** → **API Keys**
- Copy the **Public Key** → `LANGFUSE_PUBLIC_KEY` in `.env`
- Copy the **Secret Key** → `LANGFUSE_SECRET_KEY` in `.env`

**Upload the RCA prompt (one-time, after setting keys in `.env`):**
```bash
# macOS / Linux / WSL
python scripts/migrate_prompts_to_langfuse.py

# Windows
python scripts\migrate_prompts_to_langfuse.py
```

---

### 4. Atlassian Jira (Incident Creation — Optional)

Used for creating Jira tickets when job failures are detected. Set `JIRA_ENABLED=false` to skip — demo incidents are created instead.

**Sign up:** https://www.atlassian.com/software/jira
- Free tier available

**Generate API Token:**
- Go to https://id.atlassian.com/manage-profile/security/api-tokens
- **Create API token** → give it a name → copy the token
- → `ATLASSIAN_API_TOKEN` in `.env`

**Other required values:**
- `ATLASSIAN_EMAIL` — the email you use to log into Atlassian
- `ATLASSIAN_CLOUD_ID` — your site URL, format: `yourcompany.atlassian.net`
- `ATLASSIAN_PROJECT_KEY` — short code visible in the Jira project URL (e.g. `DE`, `OPS`)
- `ATLASSIAN_ISSUE_TYPE` — typically `Task` or `Incident`

---

## Setup Instructions

### macOS / Linux / WSL

1. Install dependencies:
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Configure environment variables:
```bash
cp .env.example .env
# Edit .env for Model Provider, Data Platform, Atlassian Jira, and Langfuse configurations
```

3. Run the application:
```bash
streamlit run app.py
```
The application will open in your browser at `http://localhost:8501`

---

### Windows (Native — No WSL Required)

> Use **PowerShell** or **Command Prompt**. Python 3.12 must be installed.
> Download from https://www.python.org/downloads/ — check **"Add Python to PATH"** during install.

1. Install dependencies:
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Configure environment variables:
```powershell
copy .env.example .env
```
Fill in Model Provider, Data Platform, Atlassian Jira, and Langfuse configurations.

3. Run the application:
```powershell
streamlit run app.py
```
The application will open in your browser at `http://localhost:8501`

---

## Demo Jobs Setup

Run this once to create sample Databricks notebooks and jobs that simulate realistic ETL failures. The Monitor and RCA agents will pick these up automatically.

```bash
# macOS / Linux / WSL
python scripts/create_demo_jobs.py

# Windows
python scripts\create_demo_jobs.py
```

**What gets created:**

| Job | Expected Result | Failure Scenario |
|---|---|---|
| `etl_ingest_customer_data` | ✅ SUCCEEDED | — healthy baseline job |
| `etl_ingest_sales_transactions` | ❌ FAILED | Wrong schema name (`confromed_sales` typo → AnalysisException) |
| `etl_ingest_daily_inventory` | ❌ FAILED | Today's file not yet landed in the data lake (FileNotFoundError) |
| `etl_transform_revenue_summary` | ❌ FAILED | Upstream changed filename format from `YYYY-MM-DD` to `YYYYMMDD` |
| `etl_load_product_dimension` | ✅ SUCCEEDED | — healthy baseline job |

The script uploads notebooks to `/Shared/demo_etl/` in your workspace, creates jobs, triggers all runs, and waits for them to complete. Takes ~5 minutes depending on cluster startup time.

---

## Running the Application

### Option A — Manual mode (single terminal)

```powershell
# macOS / Linux / WSL
streamlit run app.py

# Windows
streamlit run app.py
```

Switch the sidebar to **▶️ Manual** mode and click **Run Monitoring Now** to trigger a workflow run.

---

### Option B — Ticker mode (two terminals)

The ticker runs the workflow automatically on a schedule and writes results to SQLite. The UI reads from SQLite and updates without triggering any agent runs itself.

**Terminal 1 — Start the UI**
```powershell
streamlit run app.py
```

**Terminal 2 — Start the background ticker**
```powershell
# Run every 30 minutes (default)
python ticker.py

# Run every 10 minutes
python ticker.py --interval 10

# Run daily at 06:30 UTC
python ticker.py --cron 06:30

# Run once immediately (useful for testing)
python ticker.py --once
```

In the Streamlit sidebar, switch to **⏱️ Background Ticker** mode. You can configure the schedule (interval or cron, task type) and save it — then restart the ticker to apply. Enable **Auto-refresh UI** in the sidebar to have the UI poll SQLite automatically.

**Ticker environment variables (optional — all overridable by CLI flags):**
```env
TICKER_MODE=interval          # interval | cron
TICKER_INTERVAL_MIN=30        # minutes between runs
TICKER_CRON_TIME=06:00        # HH:MM UTC for cron mode
TICKER_TASK=monitor_and_analyze
```

---

### Supervisor Agent
- A data-platform triage agent which coordinates specialized worker agents
- Uses LangGraph to orchestrate workflow

### Monitor Agent
- Queries ETL Jobs API for job statuses
- Identifies failed jobs

### RCA Agent
- Retrieves logs for failed jobs
- Uses LLM to analyze logs and identify root causes
- Provides actionable recommendations

### Incident Agent
- For failed jobs, creates Jira tickets using Atlassian Jira MCP client

### Adding More Agents
1. Create new agent file in `agents/` directory
2. Add to workflow in `supervisor_agent.py`
3. Update Streamlit UI in `app.py`
