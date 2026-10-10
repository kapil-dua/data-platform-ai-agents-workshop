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

    # ── LLM Provider Settings ─────────────────────────────────────────────
    # Agent settings

    MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "")

    # LLM throttling — set to true to add sleep between LLM calls (helps with rate limits)
    # Recommended: LLM_THROTTLE_ENABLED=true for Groq free tier, false for Databricks AI Gateway
    LLM_THROTTLE_ENABLED = os.getenv("LLM_THROTTLE_ENABLED", "false").lower() == "true"
    LLM_THROTTLE_SECONDS = int(os.getenv("LLM_THROTTLE_SECONDS", "8"))

    # Max parallel RCA jobs — reduce for rate-limited providers (e.g. Groq free tier)
    # Set to a high number (e.g. 10) for Databricks AI Gateway which has no rate limits
    RCA_MAX_PARALLEL = int(os.getenv("RCA_MAX_PARALLEL", "2"))

    OLLAMA_MODEL_ID = os.getenv("OLLAMA_MODEL_ID", "")

    # Groq API settings
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL_ID = os.getenv("GROQ_MODEL_ID", "")

    # ── Databricks Settings ───────────────────────────────────────────────
    # Databricks API settings
    DATABRICKS_WORKSPACE_HOST = os.getenv("DATABRICKS_WORKSPACE_HOST", "")
    DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN", "")
    DATABRICKS_AI_GATEWAY = os.getenv("DATABRICKS_AI_GATEWAY", "")
    DATABRICKS_MODEL_ID = os.getenv("DATABRICKS_MODEL_ID", "")

    # ── Jira / Atlassian Settings ─────────────────────────────────────────
    JIRA_ENABLED = os.getenv("JIRA_ENABLED", "false").lower() == "true"
    # Atlassian Rovo MCP settings
    ATLASSIAN_MCP_URL = os.getenv("ATLASSIAN_MCP_URL", "https://mcp.atlassian.com/v2/mcp")
    ATLASSIAN_API_TOKEN = os.getenv("ATLASSIAN_API_TOKEN", "")
    ATLASSIAN_AUTH_HEADER = os.getenv("ATLASSIAN_AUTH_HEADER", "")
    ATLASSIAN_EMAIL = os.getenv("ATLASSIAN_EMAIL", "")
    ATLASSIAN_CLOUD_ID = os.getenv("ATLASSIAN_CLOUD_ID", "nagarro-dataai-1.atlassian.net")
    ATLASSIAN_PROJECT_KEY = os.getenv("ATLASSIAN_PROJECT_KEY", "")
    ATLASSIAN_ISSUE_TYPE = os.getenv("ATLASSIAN_ISSUE_TYPE", os.getenv("JIRA_ISSUE_TYPE", "Task"))

    # ── Langfuse Observability Settings ──────────────────────────────────
    # Langfuse Observability settings
    LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "true").lower() == "true"
    LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_BATCH_SIZE = int(os.getenv("LANGFUSE_BATCH_SIZE", "100"))
    LANGFUSE_FLUSH_INTERVAL = int(os.getenv("LANGFUSE_FLUSH_INTERVAL", "10"))

    # ── Agent Prompts (edit here or manage via Langfuse) ─────────────────

    ## ── ReAct supervisor prompts ─────────────────────────────────────────────

    _REACT_SYSTEM_PROMPT = """You are a data-platform triage supervisor deciding which agent to invoke next.

Based on the current workflow state, decide the next step by responding with EXACTLY one of these words:
  monitor   - if jobs have not been checked yet
  rca       - if failed jobs were found and root cause analysis is needed
  incident  - if RCA is complete and incidents need to be created
  DONE      - if the workflow is complete (no failures, or all steps finished)

Rules:
  - Always start with: monitor
  - After monitor: if failed_jobs > 0 and task requires analysis -> rca. Otherwise -> DONE
  - After rca: if task requires incidents and rca_results exist -> incident. Otherwise -> DONE
  - Never respond with incident if rca_results is empty
  - Respond with ONLY the single word. No explanation, no punctuation.

Current task: {task}"""

    _REACT_USER_PROMPT = "What should be done next?"

    ## ── RCA prompts ──────────────────────────────────────────────────────────

    _RCA_SYSTEM_PROMPT = """You are an expert data engineer performing root cause analysis on failed ETL jobs.

You will be given:
1. Job error logs and stack trace
2. Job context from the DAB (Databricks Asset Bundle) — documentation of what the job is designed to do
3. Unity Catalog lineage — what tables the job reads/writes and who depends on its output

CRITICAL RULES:
- Every path, table name, filename, system name and config value you mention MUST come from the context or error logs. Do not invent values.
- DAB parameters are DOCUMENTATION only. Do NOT suggest changing DAB parameters unless the error directly proves they are wrong.
- If a file is missing, the fix is to deliver the correct file. If a filename format changed upstream, ask the upstream team to revert — do not change the code pattern.
- For schema mismatches in conformed jobs: the fix is to update the transform code to handle new columns.
- The RECOMMENDED FIX must address ONLY the specific failure. Maximum 4 steps.

Your analysis must include:

1. ROOT CAUSE - one clear sentence: what failed and exactly why, using values from the error.

2. DOWNSTREAM IMPACT - exact downstream tables or jobs affected (from UC lineage). If none, say "No downstream impact identified."

3. RECOMMENDED FIX - numbered steps addressing ONLY the actual error.
   Each step: WHAT to do + WHERE exactly (exact path/table/system from context) + HOW to access.

4. SEVERITY - Critical / High / Medium / Low with one-line justification.

Be specific and grounded in the context only. Do not speculate."""

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

    ## ── RCA Evaluation prompts ───────────────────────────────────────────────

    _EVAL_SYSTEM_PROMPT = """You are a fair, evidence-based senior data engineering reviewer evaluating a root cause analysis (RCA) for a failed ETL job.

Score each criterion 1-10 using this scale:
- 9-10: Exceptional, production-ready documentation
- 7-8:  Good, actionable RCA that an engineer can act on
- 5-6:  Adequate, identifies the issue but lacks some details  
- 3-4:  Weak, vague or missing key information
- 1-2:  Poor, fundamentally incorrect or useless

1. CLARITY (1-10): Root cause clearly stated, unambiguous.
   Score 7+ if the root cause is identifiable in the first paragraph.

2. ACTIONABILITY (1-10): Fix steps are specific enough to act on.
   Score 7+ if steps mention specific tables, paths, or systems (even without exact commands).
   Score 9+ only if steps include exact commands or file paths.

3. COMPLETENESS (1-10): Covers WHAT failed, WHY it matters, HOW to fix, and DOWNSTREAM IMPACT.
   Score 7+ if at least 3 of these 4 elements are present.
   Do NOT penalize for missing downstream impact if the job failed before writing (no downstream effect).

FEEDBACK RULES: For each criterion below threshold, provide brief constructive feedback.

Respond ONLY with valid JSON:
{{
  "clarity_score": <float>,
  "actionability_score": <float>,
  "completeness_score": <float>,
  "overall_score": <float>,
  "passed": <bool>,
  "clarity_feedback": "<brief feedback, or empty if score >= 7>",
  "actionability_feedback": "<brief feedback, or empty if score >= 7>",
  "completeness_feedback": "<brief feedback, or empty if score >= 7>",
  "feedback": "<combined summary>"
}}

Threshold: {threshold}. passed=true only if overall_score >= {threshold}."""

    _EVAL_USER_PROMPT = """Job: {job_name}
Error: {error_message}

=== DAB CONTEXT ===
{dab_context}

=== UC LINEAGE ===
{uc_lineage}

=== RCA TO EVALUATE ===
{rca_analysis}"""

    # ── Fallback aliases (backward compatibility) ─────────────────────────────
    _FALLBACK_RCA_SYSTEM_PROMPT = _RCA_SYSTEM_PROMPT
    _FALLBACK_RCA_USER_TEMPLATE = _RCA_USER_PROMPT


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