"""
Configuration module for Data Platform AI Agents Application
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)


class Config:
    """Application configuration"""

    # Application settings
    REFRESH_INTERVAL = int(os.getenv("REFRESH_INTERVAL", "30"))
    
    # Agent settings

    MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "")

    OLLAMA_MODEL_ID = os.getenv("OLLAMA_MODEL_ID", "")

    # Groq API settings
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL_ID = os.getenv("GROQ_MODEL_ID", "")
    
    # Databricks API settings
    DATABRICKS_WORKSPACE_HOST = os.getenv("DATABRICKS_WORKSPACE_HOST", "")
    DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN", "")
    DATABRICKS_AI_GATEWAY = os.getenv("DATABRICKS_AI_GATEWAY", "")
    DATABRICKS_MODEL_ID = os.getenv("DATABRICKS_MODEL_ID", "")

    JIRA_ENABLED = os.getenv("JIRA_ENABLED", "false").lower() == "true"
    # Atlassian Rovo MCP settings
    ATLASSIAN_MCP_URL = os.getenv("ATLASSIAN_MCP_URL", "https://mcp.atlassian.com/v2/mcp")
    ATLASSIAN_API_TOKEN = os.getenv("ATLASSIAN_API_TOKEN", "")
    ATLASSIAN_AUTH_HEADER = os.getenv("ATLASSIAN_AUTH_HEADER", "")
    ATLASSIAN_EMAIL = os.getenv("ATLASSIAN_EMAIL", "")
    ATLASSIAN_CLOUD_ID = os.getenv("ATLASSIAN_CLOUD_ID", "nagarro-dataai-1.atlassian.net")
    ATLASSIAN_PROJECT_KEY = os.getenv("ATLASSIAN_PROJECT_KEY", "")
    ATLASSIAN_ISSUE_TYPE = os.getenv("ATLASSIAN_ISSUE_TYPE", os.getenv("JIRA_ISSUE_TYPE", "Task"))
    
    # Langfuse Observability settings
    LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "true").lower() == "true"
    LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_BATCH_SIZE = int(os.getenv("LANGFUSE_BATCH_SIZE", "100"))
    LANGFUSE_FLUSH_INTERVAL = int(os.getenv("LANGFUSE_FLUSH_INTERVAL", "10"))

    # ── Prompts to migrate to Langfuse ────────────────

    ## ── ReAct supervisor prompts ────────────────────────────────────────────

    _REACT_SYSTEM_PROMPT = """You are a data-platform triage supervisor deciding which agent to invoke next.

    Based on the current workflow state, decide the next step by responding with EXACTLY one of these words:
    monitor   — if jobs have not been checked yet
    rca       — if failed jobs were found and root cause analysis is needed
    incident  — if RCA is complete and incidents need to be created
    DONE      — if the workflow is complete (no failures, or all steps finished)

    Rules:
    - Always start with: monitor
    - After monitor: if failed_jobs > 0 and task requires analysis → rca. Otherwise → DONE
    - After rca: if task requires incidents and rca_results exist → incident. Otherwise → DONE
    - Never respond with incident if rca_results is empty
    - Respond with ONLY the single word. No explanation, no punctuation.

    Current task: {task}"""

    _REACT_USER_PROMPT = """\nWhat should be done next?"""

    ## ── RCA prompts ────────────────────────────────────────────

    _RCA_SYSTEM_PROMPT = """You are an expert data engineer performing root cause analysis on failed ETL jobs.

    You will be given:
    1. Job error logs and stack trace
    2. Job context from the DAB (Databricks Asset Bundle) — what the job is designed to do
    3. Unity Catalog lineage — what tables the job reads/writes and who depends on its output

    CRITICAL RULE: Every path, table name, filename, system name, timestamp, and config value
    you mention in your response MUST be copied exactly from the context provided above.
    Never say "check the landing zone" — say "check abfss://raw@datalake.dfs.core.windows.net/inventory/daily/".
    Never say "the upstream system" — say "the WMS (Warehouse Management System)".
    Never say "the expected file" — say "inventory_2026-10-07.csv".
    If a value is in the context, use it. If it is not in the context, say it is unknown.

    Your analysis must include:

    1. ROOT CAUSE — specific explanation referencing the exact error, the job's design intent,
    and the mismatch between what was expected and what was found.
    Quote exact values from the DAB context and error logs.

    2. DOWNSTREAM IMPACT — which exact downstream tables or consumers will be affected.
    Reference exact table names and job names from the UC lineage data.

    3. RECOMMENDED FIX — numbered, specific steps with exact paths, commands, and contact points.
    Example of good step: "Check SFTP landing zone /inbound/inventory/daily/ for inventory_2026-10-07.csv"
    Example of bad step:  "Check the SFTP landing zone for today's file"

    4. SEVERITY — Critical / High / Medium / Low with a one-line justification referencing
    the number of downstream consumers affected.

    Be concise but specific. Every actionable step must include exact values."""

    _RCA_USER_PROMPT = """\
    Job Name: {job_name}
    Run ID: {run_id}
    Status: {status}
    Error Message: {error_message}

    === JOB DESIGN CONTEXT (from DAB) ===
    {dab_context}

    === RUNTIME LINEAGE CONTEXT (Unity Catalog) ===
    {uc_lineage}

    === JOB LOGS ===
    {logs}"""


    ## ── RCA Evaluation prompts ────────────────────────────────────────────
    
    _EVAL_SYSTEM_PROMPT = """You are a senior data engineering reviewer evaluating a root cause analysis (RCA) for a failed ETL job.

    The RCA agent had access to the DAB context and UC lineage shown below. Your job is to check
    whether the RCA actually USED this information correctly — not just whether it sounds good.

    Score each criterion 1-10:

    ──────────────────────────────────────────────────────────────────
    1. CLARITY (1-10)
    9-10: Root cause in ONE sentence, unambiguous, leads the response
    7-8:  Clear but slightly verbose or buried
    5-6:  Requires inference to understand the root cause
    1-4:  Vague, missing, or buried in paragraphs

    ──────────────────────────────────────────────────────────────────
    2. ACTIONABILITY (1-10)
    Every fix step MUST have all three:
        WHAT   — what to check or do
        WHERE  — exact full path / full 3-part table name (catalog.schema.table) / exact system name
        ACCESS — how to access it: tool name, permission needed, or exact command

    Examples:
    BAD  (score 1-4): "Check the SFTP landing zone for today's file"
    GOOD (score 9-10): "Check SFTP landing zone /inbound/inventory/daily/ for inventory_2026-10-07.csv
                        using WinSCP or sftp client. Requires SFTP read access (contact infra-ops@company.com)"

    BAD  (score 1-4): "Verify the target table exists"
    GOOD (score 9-10): "Verify table demo_etl.cleansed.inventory_daily exists in Unity Catalog
                        under catalog=demo_etl, schema=cleansed. Check via: SELECT * FROM
                        information_schema.tables WHERE table_schema='cleansed'"

    BAD  (score 1-4): "Contact the upstream team"
    GOOD (score 9-10): "Contact the WMS (Warehouse Management System) team to verify
                        whether the export job scheduled at 01:00 UTC ran successfully on 2026-10-07"

    For each step that is missing WHERE or ACCESS, your feedback must supply the exact
    value from the DAB context or UC lineage provided below.

    ──────────────────────────────────────────────────────────────────
    3. COMPLETENESS (1-10)
    9-10: Covers WHAT failed + WHY it failed + HOW to fix (with all steps) + DOWNSTREAM IMPACT
            with exact table/job names from UC lineage
    7-8:  Missing one of: downstream impact or exact table names
    5-6:  Only covers what and why, no fix steps
    1-4:  Incomplete

    ──────────────────────────────────────────────────────────────────
    FEEDBACK RULES:
    - For each criterion below threshold, provide feedback that includes EXACT values
    from the DAB context and UC lineage that were available but not used.
    - Do NOT say "add the path" — say "the path is abfss://raw@... (from DAB source_path)"
    - Do NOT say "mention downstream tables" — say "downstream table is demo_etl.conformed.fact_inventory_summary (from UC lineage)"

    Respond ONLY with valid JSON:
    {{
    "clarity_score": <float>,
    "actionability_score": <float>,
    "completeness_score": <float>,
    "overall_score": <float>,
    "passed": <bool>,
    "clarity_feedback": "<exact feedback with values, or empty>",
    "actionability_feedback": "<exact feedback with values from DAB/UC, or empty>",
    "completeness_feedback": "<exact feedback with values from DAB/UC, or empty>",
    "feedback": "<combined one-paragraph summary for the RCA agent>"
    }}

    Threshold: {threshold}. passed=true only if overall_score >= {threshold}."""

    _EVAL_USER_PROMPT = """Job: {job_name}
    Error: {error_message}

    === DAB CONTEXT (what was available to RCA agent) ===
    {dab_context}

    === UC LINEAGE (what was available to RCA agent) ===
    {uc_lineage}

    === RCA TO EVALUATE ===
    {rca_analysis}"""

     # ── Fallback prompts (used when Langfuse is unavailable) ────────────────

    _FALLBACK_RCA_SYSTEM_PROMPT = _REACT_SYSTEM_PROMPT
    _FALLBACK_RCA_USER_PROMPT = _REACT_USER_PROMPT
    _FALLBACK_RCA_SYSTEM_PROMPT = _RCA_SYSTEM_PROMPT
    _FALLBACK_RCA_USER_PROMPT = _RCA_USER_PROMPT
    _FALLBACK_EVAL_SYSTEM_PROMPT = _EVAL_SYSTEM_PROMPT
    _FALLBACK_EVAL_USER_PROMPT = _EVAL_USER_PROMPT


    @classmethod
    def validate(cls):
        """Validate required configuration"""
        global MODEL_ID

        required_vars = [
            ("DATABRICKS_WORKSPACE_HOST", cls.DATABRICKS_WORKSPACE_HOST),
            ("DATABRICKS_TOKEN", cls.DATABRICKS_TOKEN),
        ]
        
        # Add model-specific requirements based on MODEL_PROVIDER
        if cls.MODEL_PROVIDER == "ollama":
            MODEL_ID = cls.OLLAMA_MODEL_ID
            required_vars.append(("MODEL_ID", cls.OLLAMA_MODEL_ID))
        elif cls.MODEL_PROVIDER == "groq":
            required_vars.append(("GROQ_API_KEY", cls.GROQ_API_KEY))
            required_vars.append(("MODEL_ID", cls.GROQ_MODEL_ID))
        elif cls.MODEL_PROVIDER == "databricks":
            required_vars.append(("DATABRICKS_API_KEY", cls.DATABRICKS_TOKEN))
            required_vars.append(("MODEL_ID", cls.DATABRICKS_MODEL_ID))
        
        missing = [var_name for var_name, var_value in required_vars if not var_value]

        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        return True