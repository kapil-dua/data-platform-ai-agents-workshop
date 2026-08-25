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
Analyze the job failure information and logs to determine:
1. The root cause - Brief explanation of why the job failed (2-3 sentences)
2. Specific recommendation - Actionable steps to prevent this failure in the future
3. Suggest Issue Severity level like Critical, High, Medium, Low

Provide your RCA analysis in a structured format with concise info and focused, Severity level summary less than 20 words."""

RCA_USER_PROMPT = """Job Name: {{job_name}}
Run ID: {{run_id}}
Status: {{status}}
Error Message: {{error_message}}

Job Logs:
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
