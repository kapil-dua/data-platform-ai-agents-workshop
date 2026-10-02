"""
Create demo Databricks notebooks and jobs for the workshop.

Each job simulates a realistic ETL pipeline failure with a clear, descriptive
error message so the RCA agent has meaningful content to analyse.

Demo jobs created:
  1. etl_ingest_customer_data       -> SUCCEEDS  (baseline healthy job)
  2. etl_ingest_sales_transactions  -> FAILS     (wrong schema name / AnalysisException)
  3. etl_ingest_daily_inventory     -> FAILS     (file not found for today's date)
  4. etl_transform_revenue_summary  -> FAILS     (wrong filename / date in path)
  5. etl_load_product_dimension     -> SUCCEEDS  (baseline healthy job)

Usage:
    python scripts/create_demo_jobs.py

Required environment variables (already in .env):
    DATABRICKS_WORKSPACE_HOST, DATABRICKS_TOKEN
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import Language, ImportFormat
from databricks.sdk.service import jobs as jobs_sdk

from config import Config


# ---------------------------------------------------------------------------
# Notebook definitions
# Each notebook is a list of cells: (cell_type, source)
# cell_type: "code" | "markdown"
# ---------------------------------------------------------------------------

NOTEBOOKS: list[dict] = [
    # ── 1. SUCCEEDS ────────────────────────────────────────────────────────
    {
        "path": "/Shared/demo_etl/etl_ingest_customer_data",
        "job_name": "etl_ingest_customer_data",
        "should_fail": False,
        "cells": [
            ("markdown", "## ETL: Ingest Customer Data\nReads customer records from the cleansed layer and loads into the conformed layer."),
            ("code", """\
import datetime
print(f"[{datetime.datetime.utcnow()}] Starting customer data ingestion...")
print("Reading from: abfss://cleansed@datalake.dfs.core.windows.net/customers/")

# Simulate successful read + write
record_count = 142_350
print(f"Records read from cleansed layer  : {record_count:,}")
print(f"Records written to conformed layer: {record_count:,}")
print(f"Duplicate records dropped         : 0")
print(f"Null primary keys found           : 0")
print(f"[{datetime.datetime.utcnow()}] Customer data ingestion completed successfully.")
"""),
        ],
    },

    # ── 2. FAILS — wrong schema name (AnalysisException) ──────────────────
    {
        "path": "/Shared/demo_etl/etl_ingest_sales_transactions",
        "job_name": "etl_ingest_sales_transactions",
        "should_fail": True,
        "cells": [
            ("markdown", "## ETL: Ingest Sales Transactions\nReads daily sales transactions and loads into the conformed schema."),
            ("code", """\
import datetime
print(f"[{datetime.datetime.utcnow()}] Starting sales transaction ingestion...")
print("Target schema: confromed_sales  (note: typo in schema name)")

# Simulate AnalysisException caused by wrong schema name
raise Exception(
    "AnalysisException: Schema 'confromed_sales' does not exist. "
    "Verify the target schema name in the pipeline configuration. "
    "Available schemas: raw, cleansed, conformed, commercial. "
    "Pipeline config key: TARGET_SCHEMA=confromed_sales"
)
"""),
        ],
    },

    # ── 3. FAILS — file not found for today's date ─────────────────────────
    {
        "path": "/Shared/demo_etl/etl_ingest_daily_inventory",
        "job_name": "etl_ingest_daily_inventory",
        "should_fail": True,
        "cells": [
            ("markdown", "## ETL: Ingest Daily Inventory\nExpects a daily CSV drop from the warehouse system at midnight UTC."),
            ("code", """\
import datetime
today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
expected_path = f"abfss://raw@datalake.dfs.core.windows.net/inventory/daily/inventory_{today}.csv"

print(f"[{datetime.datetime.utcnow()}] Starting daily inventory ingestion...")
print(f"Expected file path: {expected_path}")

# Simulate file not yet landed
raise FileNotFoundError(
    f"FileNotFoundError: The specified path does not exist: {expected_path}. "
    f"The upstream warehouse system may not have delivered today's file yet. "
    f"Last successful delivery was for date: {(datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')}. "
    f"Check the SFTP landing zone or contact the warehouse operations team."
)
"""),
        ],
    },

    # ── 4. FAILS — wrong date format in filename ───────────────────────────
    {
        "path": "/Shared/demo_etl/etl_transform_revenue_summary",
        "job_name": "etl_transform_revenue_summary",
        "should_fail": True,
        "cells": [
            ("markdown", "## ETL: Transform Revenue Summary\nReads raw revenue export (YYYYMMDD format) and transforms into the conformed fact table."),
            ("code", """\
import datetime
import re

print(f"[{datetime.datetime.utcnow()}] Starting revenue summary transformation...")

# Pipeline is hardcoded to look for YYYY-MM-DD format but file uses YYYYMMDD
expected_pattern = r"revenue_export_(\\d{4}-\\d{2}-\\d{2})\\.csv"
actual_filename   = "revenue_export_20261002.csv"  # YYYYMMDD — no dashes

match = re.match(expected_pattern, actual_filename)
if not match:
    raise ValueError(
        f"ValueError: Filename '{actual_filename}' does not match expected pattern "
        f"'revenue_export_YYYY-MM-DD.csv'. "
        f"The upstream finance system changed the export filename format from "
        f"'YYYY-MM-DD' to 'YYYYMMDD' without notifying the data engineering team. "
        f"Update the filename parser in the ingestion config or ask the finance team "
        f"to revert the export format."
    )
"""),
        ],
    },

    # ── 5. SUCCEEDS ────────────────────────────────────────────────────────
    {
        "path": "/Shared/demo_etl/etl_load_product_dimension",
        "job_name": "etl_load_product_dimension",
        "should_fail": False,
        "cells": [
            ("markdown", "## ETL: Load Product Dimension\nMerges product catalogue updates into the conformed dimension table using SCD Type 2."),
            ("code", """\
import datetime
print(f"[{datetime.datetime.utcnow()}] Starting product dimension load (SCD Type 2)...")

new_records    = 38
updated_records = 12
expired_records = 5

print(f"New product records inserted    : {new_records}")
print(f"Existing records updated (SCD2) : {updated_records}")
print(f"Records expired (end-dated)     : {expired_records}")
print(f"Total active dimension rows     : 9_847")
print(f"[{datetime.datetime.utcnow()}] Product dimension load completed successfully.")
"""),
        ],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _notebook_source(cells: list[tuple[str, str]]) -> str:
    """Combine cells into a single Python source using Databricks cell magic."""
    parts: list[str] = []
    for cell_type, source in cells:
        if cell_type == "markdown":
            parts.append(f"# MAGIC %md\n# MAGIC {source.strip()}")
        else:
            parts.append(source.strip())
    return "\n\n# COMMAND ----------\n\n".join(parts)


def upload_notebook(client: WorkspaceClient, path: str, source: str) -> None:
    """Upload (or overwrite) a Python notebook."""
    import base64
    encoded = base64.b64encode(source.encode("utf-8")).decode("utf-8")
    client.workspace.import_(
        path=path,
        language=Language.PYTHON,
        content=encoded,
        overwrite=True,
        format=ImportFormat.SOURCE,
    )
    print(f"  ✅ Notebook uploaded: {path}")


def create_job(client: WorkspaceClient, job_name: str, notebook_path: str) -> int:
    """Create (or recreate) a single-task notebook job."""
    # Delete existing job with same name to avoid duplicates
    existing = list(client.jobs.list(name=job_name))
    for job in existing:
        client.jobs.delete(job_id=job.job_id)
        print(f"  🗑  Deleted existing job: {job_name} (id={job.job_id})")

    created = client.jobs.create(
        name=job_name,
        tasks=[
            jobs_sdk.Task(
                task_key="main",
                notebook_task=jobs_sdk.NotebookTask(notebook_path=notebook_path),
                # Free trial workspaces only support serverless compute — no cluster spec needed
            )
        ],
    )
    print(f"  ✅ Job created: {job_name} (id={created.job_id})")
    return created.job_id


def run_and_wait(client: WorkspaceClient, job_id: int, job_name: str) -> None:
    """Trigger a job run and wait for it to reach a terminal state."""
    run = client.jobs.run_now(job_id=job_id)
    run_id = run.run_id
    print(f"  ▶  Run triggered: {job_name} (run_id={run_id}) — waiting...", end="", flush=True)

    while True:
        time.sleep(10)
        details = client.jobs.get_run(run_id=run_id)
        state = details.state
        lc = getattr(state.life_cycle_state, "value", state.life_cycle_state)
        if lc in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
            rs = getattr(state.result_state, "value", state.result_state)
            print(f" {rs}")
            return
        print(".", end="", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Connecting to Databricks workspace...")
    client = WorkspaceClient(
        host=Config.DATABRICKS_WORKSPACE_HOST,
        token=Config.DATABRICKS_TOKEN,
    )
    print(f"Connected: {Config.DATABRICKS_WORKSPACE_HOST}\n")

    # Ensure the shared folder exists
    try:
        client.workspace.mkdirs(path="/Shared/demo_etl")
        print("📁 Created folder: /Shared/demo_etl\n")
    except Exception:
        print("📁 Folder /Shared/demo_etl already exists\n")

    job_ids: list[tuple[int, bool]] = []

    for spec in NOTEBOOKS:
        print(f"── {spec['job_name']}")
        source = _notebook_source(spec["cells"])
        upload_notebook(client, spec["path"], source)
        job_id = create_job(client, spec["job_name"], spec["path"])
        job_ids.append((job_id, spec["should_fail"], spec["job_name"]))
        print()

    print("=" * 60)
    print("All notebooks and jobs created. Triggering runs...\n")

    for job_id, should_fail, job_name in job_ids:
        run_and_wait(client, job_id, job_name)

    print("\n" + "=" * 60)
    print("✅ Demo jobs setup complete.\n")
    print("Expected results:")
    for _, should_fail, job_name in job_ids:
        status = "FAILED  ❌" if should_fail else "SUCCEEDED ✅"
        print(f"  {status}  {job_name}")
    print("\nRun the app and trigger 'monitor_analyze_incident' to see the agents in action.")


if __name__ == "__main__":
    main()
