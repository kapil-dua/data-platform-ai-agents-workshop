"""
One-time migration script that uploads the hardcoded prompts in this repo
into Langfuse Prompt Management.

Prompts created (all labeled ``production``):

    1. ``job-failure-rca-analysis``       (type=chat) -- used by ``agents/rca_agent.py``

Usage:

    python scripts/migrate_prompts_to_langfuse.py

The script is idempotent: re-running it just creates a new version of each
prompt (Langfuse dedupes by name, existing versions are preserved).

Required environment variables (already defined in ``.env``):

    LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from langfuse import Langfuse

from config import Config

load_dotenv()


RCA_SYSTEM_PROMPT = """You are an expert data engineer performing root cause analysis on failed ETL jobs.

You will be given:
1. Job error logs and stack trace
2. Job context from the DAB (Databricks Asset Bundle) - documentation of what the job is designed to do
3. Unity Catalog lineage - what tables the job reads/writes and who depends on its output

CRITICAL RULES:
- Every path, table name, filename, system name and config value you mention MUST come from the context or error logs. Do not invent values.
- DAB parameters (source_path, filename_pattern, etc.) are DOCUMENTATION only. Do NOT suggest changing DAB parameters unless the error proves a parameter is misconfigured.
- If a filename pattern is wrong in the CODE, the fix is to update the code regex, not the DAB documentation.
- If a file is missing, the fix is to deliver the correct file, not to change the expected pattern.
- The RECOMMENDED FIX must address ONLY the specific failure shown in the error. Maximum 4 steps.

Your analysis must include:

1. ROOT CAUSE - one clear sentence: what failed and exactly why, using values from the error.

2. DOWNSTREAM IMPACT - exact downstream tables or jobs affected (from UC lineage). If none, say "No downstream impact identified."

3. RECOMMENDED FIX - numbered steps addressing ONLY the actual error.
   Each step: WHAT to do + WHERE exactly (exact path/table/system from context) + HOW to access.
   For missing files: the fix is to deliver the correct file, not update patterns.
   For schema mismatches: the fix is to update the transform code, not the DAB.
   For filename format changes: the fix is to update the code regex or rename the file.

4. SEVERITY - Critical / High / Medium / Low with one-line justification.

Be specific and grounded in the context only. Do not speculate."""

RCA_USER_PROMPT = """Job Name: {{job_name}}
Run ID: {{run_id}}
Status: {{status}}
Error Message: {{error_message}}

=== JOB DESIGN CONTEXT (from DAB) ===
{{dab_context}}

=== RUNTIME LINEAGE CONTEXT (Unity Catalog) ===
{{uc_lineage}}

=== JOB LOGS ===
{{logs}}"""

REACT_SUPERVISOR_PROMPT = """You are a data-platform triage supervisor deciding which agent to invoke next.

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

PROMPTS = [
    {
        "name": "job-failure-rca-analysis",
        "type": "chat",
        "prompt": [
            {"role": "system", "content": RCA_SYSTEM_PROMPT},
            {"role": "user", "content": RCA_USER_PROMPT},
        ],
        "labels": ["production"],
        "tags": ["etl_monitoring", "rca"],
        "config": {
            "temperature": 0.1,
            "description": "Root cause analysis for failed ETL jobs",
        },
    },
    {
        "name": "supervisor-react-routing",
        "type": "text",
        "prompt": REACT_SUPERVISOR_PROMPT,
        "labels": ["production"],
        "tags": ["etl_monitoring", "supervisor", "react"],
        "config": {
            "temperature": 0.1,
            "description": "ReAct supervisor routing decision — returns single word: monitor/rca/incident/DONE",
        },
    },
]


def main() -> None:
    client = Langfuse(
        public_key=Config.LANGFUSE_PUBLIC_KEY,
        secret_key=Config.LANGFUSE_SECRET_KEY,
        host=Config.LANGFUSE_HOST,
    )

    client.auth_check()
    print(f"Connected to Langfuse at {Config.LANGFUSE_HOST}")

    for spec in PROMPTS:
        name = spec["name"]
        print(f"Creating prompt: {name} ({spec['type']})")
        client.create_prompt(**spec)
        print(f"  -> uploaded (label=production)")

    client.flush()
    print("\nAll prompts are live under label='production'.")
    print("Verify in the Langfuse UI:")
    print(f"  {Config.LANGFUSE_HOST.rstrip('/')}/project (see Prompts)")


if __name__ == "__main__":
    main()
