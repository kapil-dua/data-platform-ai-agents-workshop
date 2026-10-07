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
            ("markdown", "## ETL: Ingest Sales Transactions\nReads daily sales transactions from the cleansed layer and writes to the conformed schema."),
            ("code", """\
import datetime

run_ts = datetime.datetime.utcnow()
print(f"[{run_ts}] Starting sales transaction ingestion...")

# ── Pipeline configuration ──────────────────────────────────────────────────
SOURCE_PATH   = "abfss://cleansed@datalake.dfs.core.windows.net/sales/transactions/"
TARGET_SCHEMA = "confromed_sales"    # <── typo introduced in config change on 2026-10-01
TARGET_TABLE  = "fact_sales_transactions"
FULL_TARGET   = f"{TARGET_SCHEMA}.{TARGET_TABLE}"

print(f"Source path   : {SOURCE_PATH}")
print(f"Target schema : {TARGET_SCHEMA}")
print(f"Target table  : {FULL_TARGET}")
print()

# ── Schema existence check (simulated) ─────────────────────────────────────
AVAILABLE_SCHEMAS = ["raw", "cleansed", "conformed", "commercial"]
print(f"Available schemas in Unity Catalog: {AVAILABLE_SCHEMAS}")
print(f"Checking if schema '{TARGET_SCHEMA}' exists...")

if TARGET_SCHEMA not in AVAILABLE_SCHEMAS:
    raise Exception(
        f"AnalysisException: [SCHEMA_NOT_FOUND] Schema '{TARGET_SCHEMA}' does not exist "
        f"in Unity Catalog. "
        f"\\n\\nDiagnostics:"
        f"\\n  Configured schema : {TARGET_SCHEMA}"
        f"\\n  Available schemas : {AVAILABLE_SCHEMAS}"
        f"\\n  Likely cause      : Typo in TARGET_SCHEMA config — 'confromed' should be 'conformed'"
        f"\\n  Config location   : Pipeline config key TARGET_SCHEMA in job parameters"
        f"\\n  Last successful run: 2026-09-30 (schema was 'conformed' at that time)"
        f"\\n\\nRecommended fix:"
        f"\\n  1. Update job parameter TARGET_SCHEMA from 'confromed_sales' to 'conformed_sales'"
        f"\\n  2. Verify schema exists: SELECT * FROM information_schema.schemata WHERE schema_name = 'conformed_sales'"
        f"\\n  3. Confirm the schema was not accidentally dropped or renamed"
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
            ("markdown", "## ETL: Ingest Daily Inventory\nExpects a daily CSV drop from the warehouse management system (WMS) at 01:00 UTC every day."),
            ("code", """\
import datetime

run_ts  = datetime.datetime.utcnow()
today   = run_ts.strftime("%Y-%m-%d")
yesterday = (run_ts - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

# ── File convention and storage layout ─────────────────────────────────────
STORAGE_ACCOUNT    = "datalake"
CONTAINER          = "raw"
BASE_PATH          = f"abfss://{CONTAINER}@{STORAGE_ACCOUNT}.dfs.core.windows.net/inventory/daily/"
EXPECTED_FILENAME  = f"inventory_{today}.csv"
EXPECTED_FULL_PATH = f"{BASE_PATH}{EXPECTED_FILENAME}"
FILE_NAMING_FORMAT = "inventory_YYYY-MM-DD.csv"
DELIVERY_SLA       = "01:00 UTC daily (delivered by WMS automated export)"
SFTP_LANDING_ZONE  = "/inbound/inventory/daily/"
ARCHIVE_PATH       = f"{BASE_PATH}archive/"

# Files found in archive for last 7 days (simulated directory listing)
RECENT_ARCHIVE = [
    f"archive/inventory_{(run_ts - datetime.timedelta(days=i)).strftime('%Y-%m-%d')}.csv"
    for i in range(1, 8)
]

print(f"[{run_ts}] Starting daily inventory ingestion...")
print(f"Expected file  : {EXPECTED_FULL_PATH}")
print(f"File format    : {FILE_NAMING_FORMAT}")
print(f"Delivery SLA   : {DELIVERY_SLA}")
print(f"SFTP zone      : {SFTP_LANDING_ZONE}")
print()
print(f"Checking storage path: {EXPECTED_FULL_PATH}")
print(f"Last 7 successfully archived files:")
for f in RECENT_ARCHIVE:
    print(f"  ✅ {f}")
print()

# Simulate file not yet landed (WMS delivery delayed)
raise FileNotFoundError(
    f"FileNotFoundError: File not found at expected path."
    f"\\n\\nDiagnostics:"
    f"\\n  Expected path     : {EXPECTED_FULL_PATH}"
    f"\\n  Expected filename : {EXPECTED_FILENAME}"
    f"\\n  Naming convention : {FILE_NAMING_FORMAT}"
    f"\\n  Delivery SLA      : {DELIVERY_SLA}"
    f"\\n  Current UTC time  : {run_ts.strftime('%Y-%m-%d %H:%M:%S')}"
    f"\\n  Last successful   : inventory_{yesterday}.csv (processed {yesterday} 01:14 UTC)"
    f"\\n  Files in archive  : {RECENT_ARCHIVE}"
    f"\\n  SFTP landing zone : {SFTP_LANDING_ZONE}"
    f"\\n\\nPossible causes:"
    f"\\n  1. WMS export job delayed or failed — check WMS scheduler for {today}"
    f"\\n  2. SFTP transfer failed — file may be in landing zone but not copied to ADLS"
    f"\\n  3. File naming changed by WMS team (check if today's file uses a different format)"
    f"\\n\\nRecommended fix:"
    f"\\n  1. Check SFTP landing zone {SFTP_LANDING_ZONE} for inventory_{today}.csv"
    f"\\n  2. Check WMS export logs for job scheduled at 01:00 UTC on {today}"
    f"\\n  3. If file exists on SFTP but not in ADLS, re-trigger the SFTP→ADLS copy pipeline"
    f"\\n  4. If WMS export failed, contact warehouse operations team to re-run the export"
    f"\\n  5. If this pipeline can tolerate delay, increase the job schedule retry window"
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
            ("markdown", "## ETL: Transform Revenue Summary\nReads the daily revenue export from the finance system and transforms it into the conformed fact table."),
            ("code", """\
import datetime
import re

run_ts = datetime.datetime.utcnow()
today  = run_ts.strftime("%Y-%m-%d")

# ── File configuration ──────────────────────────────────────────────────────
SOURCE_PATH         = "abfss://raw@datalake.dfs.core.windows.net/finance/revenue/"
EXPECTED_PATTERN    = r"revenue_export_(\\d{4}-\\d{2}-\\d{2})\\.csv"   # YYYY-MM-DD format (historic format)
EXPECTED_EXAMPLE    = f"revenue_export_{today}.csv"
TARGET_TABLE        = "conformed.fact_revenue_daily"

# Files actually present in the source directory (simulated listing)
# Finance system changed export format from YYYY-MM-DD to YYYYMMDD on 2026-10-01
FILES_IN_SOURCE = [
    "revenue_export_20261005.csv",   # new YYYYMMDD format (no dashes)
    "revenue_export_20261004.csv",
    "revenue_export_20261003.csv",
    "revenue_export_2026-10-02.csv", # last file in old YYYY-MM-DD format
    "revenue_export_2026-10-01.csv",
]
ACTUAL_FILE_TODAY = "revenue_export_20261005.csv"  # what the finance system dropped

print(f"[{run_ts}] Starting revenue summary transformation...")
print(f"Source path       : {SOURCE_PATH}")
print(f"Expected pattern  : {EXPECTED_PATTERN}")
print(f"Expected filename : {EXPECTED_EXAMPLE}")
print(f"Target table      : {TARGET_TABLE}")
print()
print(f"Files found in source directory:")
for f in FILES_IN_SOURCE:
    print(f"  {'✅' if re.match(EXPECTED_PATTERN, f) else '❌'} {f}")
print()
print(f"Attempting to match: {ACTUAL_FILE_TODAY}")

match = re.match(EXPECTED_PATTERN, ACTUAL_FILE_TODAY)
if not match:
    raise ValueError(
        f"ValueError: Filename pattern mismatch — cannot extract date from filename."
        f"\\n\\nDiagnostics:"
        f"\\n  Actual filename   : {ACTUAL_FILE_TODAY}"
        f"\\n  Expected pattern  : {EXPECTED_PATTERN}  (YYYY-MM-DD with dashes)"
        f"\\n  Expected example  : {EXPECTED_EXAMPLE}"
        f"\\n  Source path       : {SOURCE_PATH}"
        f"\\n  Last matching file: revenue_export_2026-10-02.csv (old YYYY-MM-DD format, processed 2026-10-02)"
        f"\\n  First non-matching: revenue_export_20261003.csv (new YYYYMMDD format, started 2026-10-03)"
        f"\\n\\nRoot cause:"
        f"\\n  Finance system changed export filename format from 'YYYY-MM-DD' to 'YYYYMMDD' (no dashes)"
        f"\\n  starting from 2026-10-03. No change notification was sent to the data engineering team."
        f"\\n  The date extraction regex in this pipeline still expects the old 'YYYY-MM-DD' format."
        f"\\n\\nRecommended fix:"
        f"\\n  Option A (preferred): Update the filename pattern in this pipeline to accept both formats:"
        f"\\n    EXPECTED_PATTERN = r'revenue_export_(\\d{{4}}-?\\d{{2}}-?\\d{{2}})\\\\.csv'"
        f"\\n  Option B: Ask the finance team to revert to 'YYYY-MM-DD' format (reference: FIN-4821)"
        f"\\n  Option C: Update pattern to new format only:"
        f"\\n    EXPECTED_PATTERN = r'revenue_export_(\\d{{8}})\\\\.csv'"
        f"\\n  After fix, reprocess backlog: 20261003, 20261004, 20261005"
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
