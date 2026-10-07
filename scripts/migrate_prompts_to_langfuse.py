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
2. Job context from the DAB (Databricks Asset Bundle) — what the job is designed to do
3. Unity Catalog lineage — what tables the job reads/writes and who depends on its output

CRITICAL RULE: Every path, table name, filename, system name, timestamp, and config value
you mention in your response MUST be copied exactly from the context provided above.
Never say "check the landing zone" — say the exact path.
Never say "the upstream system" — say the exact system name.
Never say "the expected file" — say the exact filename with date.
If a value is in the context, use it. If it is not in the context, say it is unknown.

Your analysis must include:

1. ROOT CAUSE — specific explanation referencing the exact error, the job's design intent,
   and the mismatch between what was expected and what was found.
   Quote exact values from the DAB context and error logs.

2. DOWNSTREAM IMPACT — which exact downstream tables or consumers will be affected.
   Reference exact table names and job names from the UC lineage data.

3. RECOMMENDED FIX — numbered, specific steps with exact paths, commands, and contact points.
   Example of good: "Check SFTP landing zone /inbound/inventory/daily/ for inventory_2026-10-07.csv"
   Example of bad:  "Check the SFTP landing zone for today's file"

4. SEVERITY — Critical / High / Medium / Low with a one-line justification.

Be concise but specific. Every actionable step must include exact values."""

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
