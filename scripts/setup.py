"""
Workshop Setup Script — Medallion Architecture Demo
====================================================
Creates the full demo environment for the FLO 2026 workshop:

  1. Unity Catalog  — catalog: demo_etl, schemas: raw / cleansed / conformed
  2. Raw tables     — seeds sample data into Delta tables
  3. Notebooks      — uploads medallion ETL notebooks to /Shared/demo_etl/
  4. DAB YAMLs      — writes databricks.yml bundle files to .dab/ per job
  5. Jobs           — deploys 5 jobs (3 failing, 2 succeeding)
  6. Runs           — triggers all jobs and waits (generates UC lineage)

Total setup time: ~5-6 minutes (mostly job run cold starts)

Usage:
    python scripts/setup.py

Required environment variables (.env):
    DATABRICKS_WORKSPACE_HOST, DATABRICKS_TOKEN
"""

from __future__ import annotations

import base64
import os
import sys
import time
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import Language, ImportFormat
from databricks.sdk.service import jobs as jobs_sdk
from databricks.sdk.service import sql as sql_sdk

from config import Config

# ── Constants ─────────────────────────────────────────────────────────────────

CATALOG       = "demo_etl"
SCHEMA_RAW    = "raw"
SCHEMA_CL     = "cleansed"
SCHEMA_CF     = "conformed"
NOTEBOOK_BASE = "/Shared/demo_etl"
DAB_BASE      = Path(__file__).resolve().parent.parent / ".dab"

TODAY      = datetime.utcnow().strftime("%Y-%m-%d")
YESTERDAY  = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

# ── Job definitions ───────────────────────────────────────────────────────────

JOBS = [
    # ── 1. SUCCEEDS — raw → cleansed customers ────────────────────────────
    {
        "name":        "etl_raw_to_cleansed_customers",
        "notebook":    "etl_raw_to_cleansed_customers",
        "should_fail": False,
        "layer":       "raw_to_cleansed",
        "upstream_system": "CRM export (nightly)",
        "source_table":    f"{CATALOG}.{SCHEMA_RAW}.customers_raw",
        "target_table":    f"{CATALOG}.{SCHEMA_CL}.customers",
        "target_schema":   f"{CATALOG}.{SCHEMA_CL}",
        "sla":             "03:00 UTC",
        "description":     "Reads raw customer records, validates schema, deduplicates, writes to cleansed layer.",
        "parameters": {
            "source_table":    f"{CATALOG}.{SCHEMA_RAW}.customers_raw",
            "target_table":    f"{CATALOG}.{SCHEMA_CL}.customers",
            "primary_key":     "customer_id",
            "partition_col":   "load_date",
        },
    },
    # ── 2. FAILS — raw → cleansed inventory (file not found) ─────────────
    {
        "name":        "etl_raw_to_cleansed_inventory",
        "notebook":    "etl_raw_to_cleansed_inventory",
        "should_fail": True,
        "layer":       "raw_to_cleansed",
        "upstream_system": "Warehouse Management System (WMS) — SFTP drop at 01:00 UTC",
        "source_path":     f"abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/inventory/daily/inventory_YYYY-MM-DD.csv",
        "source_table":    f"{CATALOG}.{SCHEMA_RAW}.inventory_raw",
        "target_table":    f"{CATALOG}.{SCHEMA_CL}.inventory_daily",
        "target_schema":   f"{CATALOG}.{SCHEMA_CL}",
        "archive_path":    f"abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/inventory/archive/",
        "filename_pattern":"inventory_YYYY-MM-DD.csv",
        "sla":             "02:00 UTC",
        "description":     "Reads daily inventory CSV from ADLS, validates and writes to cleansed.inventory_daily.",
        "parameters": {
            "source_path":     f"abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/inventory/daily/",
            "target_table":    f"{CATALOG}.{SCHEMA_CL}.inventory_daily",
            "filename_pattern":"inventory_YYYY-MM-DD.csv",
            "archive_path":    f"abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/inventory/archive/",
        },
    },
    # ── 3. FAILS — raw → cleansed sales (schema typo) ────────────────────
    {
        "name":        "etl_raw_to_cleansed_sales",
        "notebook":    "etl_raw_to_cleansed_sales",
        "should_fail": True,
        "layer":       "raw_to_cleansed",
        "upstream_system": "POS system (real-time CDC via Kafka → Delta)",
        "source_table":    f"{CATALOG}.{SCHEMA_RAW}.sales_raw",
        "target_table":    f"{CATALOG}.{SCHEMA_CL}.sales_transactions",
        "target_schema":   f"{CATALOG}.{SCHEMA_CL}",
        "sla":             "04:00 UTC",
        "description":     "Reads raw sales transactions, applies business rules, writes to cleansed.sales_transactions.",
        "parameters": {
            "source_table":  f"{CATALOG}.{SCHEMA_RAW}.sales_raw",
            "target_schema": f"{CATALOG}.confromed_sales",   # intentional typo
            "target_table":  f"{CATALOG}.confromed_sales.sales_transactions",
        },
    },
    # ── 4. FAILS — cleansed → conformed revenue (filename format) ─────────
    {
        "name":        "etl_cleansed_to_conformed_revenue",
        "notebook":    "etl_cleansed_to_conformed_revenue",
        "should_fail": True,
        "layer":       "cleansed_to_conformed",
        "upstream_system": "Finance system revenue export (daily batch)",
        "source_table":    f"{CATALOG}.{SCHEMA_CL}.revenue_export",
        "target_table":    f"{CATALOG}.{SCHEMA_CF}.fact_revenue_daily",
        "target_schema":   f"{CATALOG}.{SCHEMA_CF}",
        "source_path":     f"abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/finance/revenue/",
        "filename_pattern":"revenue_export_YYYY-MM-DD.csv",
        "sla":             "05:00 UTC",
        "description":     "Reads cleansed revenue export, aggregates by region/product, writes to conformed.fact_revenue_daily.",
        "parameters": {
            "source_path":     f"abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/finance/revenue/",
            "source_table":    f"{CATALOG}.{SCHEMA_CL}.revenue_export",
            "target_table":    f"{CATALOG}.{SCHEMA_CF}.fact_revenue_daily",
            "filename_pattern":"revenue_export_YYYY-MM-DD.csv",
        },
    },
    # ── 5. SUCCEEDS — cleansed → conformed inventory ─────────────────────
    {
        "name":        "etl_cleansed_to_conformed_inventory",
        "notebook":    "etl_cleansed_to_conformed_inventory",
        "should_fail": False,
        "layer":       "cleansed_to_conformed",
        "upstream_system": "cleansed.inventory_daily (internal)",
        "source_table":    f"{CATALOG}.{SCHEMA_CL}.inventory_daily",
        "target_table":    f"{CATALOG}.{SCHEMA_CF}.fact_inventory_summary",
        "target_schema":   f"{CATALOG}.{SCHEMA_CF}",
        "sla":             "06:00 UTC",
        "description":     "Aggregates cleansed inventory data into daily summary fact table.",
        "parameters": {
            "source_table": f"{CATALOG}.{SCHEMA_CL}.inventory_daily",
            "target_table": f"{CATALOG}.{SCHEMA_CF}.fact_inventory_summary",
            "aggregation":  "daily_by_warehouse",
        },
    },
]


# ── Notebook code ─────────────────────────────────────────────────────────────

def _nb_raw_to_cleansed_customers() -> str:
    return textwrap.dedent(f"""\
# Databricks notebook source
# MAGIC %md
# MAGIC ## ETL: Raw → Cleansed Customers
# MAGIC Reads raw customer records, validates schema, deduplicates, writes to cleansed layer.

# COMMAND ----------

import datetime
from pyspark.sql import functions as F

params = {{
    "source_table": "{CATALOG}.{SCHEMA_RAW}.customers_raw",
    "target_table": "{CATALOG}.{SCHEMA_CL}.customers",
    "primary_key":  "customer_id",
}}

print(f"[{{datetime.datetime.utcnow()}}] Starting: raw → cleansed customers")
print(f"Source: {{params['source_table']}}")
print(f"Target: {{params['target_table']}}")

# COMMAND ----------

df = spark.table(params["source_table"])
print(f"Records read from raw: {{df.count():,}}")

# Validate schema
assert "customer_id" in df.columns, "Missing required column: customer_id"
assert "email" in df.columns, "Missing required column: email"

# Deduplication
df_clean = df.dropDuplicates(["customer_id"]) \\
             .filter(F.col("customer_id").isNotNull()) \\
             .withColumn("load_date", F.current_date()) \\
             .withColumn("_ingested_at", F.current_timestamp())

print(f"Records after dedup/validation: {{df_clean.count():,}}")

# COMMAND ----------

df_clean.write.format("delta") \\
    .mode("overwrite") \\
    .option("overwriteSchema", "true") \\
    .saveAsTable(params["target_table"])

print(f"[{{datetime.datetime.utcnow()}}] Completed successfully. Written to {{params['target_table']}}")
""")


def _nb_raw_to_cleansed_inventory() -> str:
    return textwrap.dedent(f"""\
# Databricks notebook source
# MAGIC %md
# MAGIC ## ETL: Raw → Cleansed Inventory
# MAGIC Reads daily inventory CSV from ADLS, validates and writes to cleansed.inventory_daily.
# MAGIC Expected file: inventory_YYYY-MM-DD.csv delivered by WMS at 01:00 UTC.

# COMMAND ----------

import datetime, re
from pyspark.sql import functions as F

today     = datetime.datetime.utcnow().strftime("%Y-%m-%d")
yesterday = (datetime.datetime.utcnow() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

SOURCE_PATH      = "abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/inventory/daily/"
FILENAME_PATTERN = f"inventory_{{today}}.csv"
EXPECTED_PATH    = f"{{SOURCE_PATH}}{{FILENAME_PATTERN}}"
TARGET_TABLE     = "{CATALOG}.{SCHEMA_CL}.inventory_daily"
ARCHIVE_PATH     = "abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/inventory/archive/"

print(f"[{{datetime.datetime.utcnow()}}] Starting: raw → cleansed inventory")
print(f"Expected file  : {{EXPECTED_PATH}}")
print(f"Target table   : {{TARGET_TABLE}}")
print(f"Delivery SLA   : 01:00 UTC (WMS automated export)")
print(f"Last successful: inventory_{{yesterday}}.csv")

# COMMAND ----------

# Read existing raw table to register UC lineage for this job
df_raw = spark.table("{CATALOG}.{SCHEMA_RAW}.inventory_raw")
print(f"Raw table records available: {{df_raw.count():,}}")

# COMMAND ----------

# Simulate: today's file has not yet landed from WMS
raise FileNotFoundError(
    f"FileNotFoundError: File not found: {{EXPECTED_PATH}}\\n"
    f"The WMS export job for {{today}} has not delivered the file yet.\\n"
    f"Last confirmed delivery: inventory_{{yesterday}}.csv\\n"
    f"Check: SFTP landing zone /inbound/inventory/daily/ for today's file."
)
""")


def _nb_raw_to_cleansed_sales() -> str:
    return textwrap.dedent(f"""\
# Databricks notebook source
# MAGIC %md
# MAGIC ## ETL: Raw → Cleansed Sales Transactions
# MAGIC Reads raw POS sales data, applies business rules, writes to cleansed layer.

# COMMAND ----------

import datetime
from pyspark.sql import functions as F

SOURCE_TABLE  = "{CATALOG}.{SCHEMA_RAW}.sales_raw"
TARGET_SCHEMA = "{CATALOG}.confromed_sales"          # typo: confromed not conformed
TARGET_TABLE  = f"{{TARGET_SCHEMA}}.sales_transactions"

print(f"[{{datetime.datetime.utcnow()}}] Starting: raw → cleansed sales transactions")
print(f"Source : {{SOURCE_TABLE}}")
print(f"Target : {{TARGET_TABLE}}")

# COMMAND ----------

# Read raw table — registers UC lineage for this job
df_raw = spark.table(SOURCE_TABLE)
print(f"Raw records read: {{df_raw.count():,}}")

# Apply business rules
df_clean = df_raw \\
    .filter(F.col("transaction_id").isNotNull()) \\
    .filter(F.col("amount") > 0) \\
    .withColumn("_ingested_at", F.current_timestamp())

print(f"Records after validation: {{df_clean.count():,}}")

# COMMAND ----------

# Write to target — schema 'confromed_sales' does not exist (typo in config)
df_clean.write.format("delta") \\
    .mode("overwrite") \\
    .saveAsTable(TARGET_TABLE)
""")


def _nb_cleansed_to_conformed_revenue() -> str:
    return textwrap.dedent(f"""\
# Databricks notebook source
# MAGIC %md
# MAGIC ## ETL: Cleansed → Conformed Revenue
# MAGIC Reads cleansed revenue export, aggregates by region/product, writes to conformed fact table.

# COMMAND ----------

import datetime, re
from pyspark.sql import functions as F

SOURCE_TABLE     = "{CATALOG}.{SCHEMA_CL}.revenue_export"
TARGET_TABLE     = "{CATALOG}.{SCHEMA_CF}.fact_revenue_daily"
SOURCE_PATH      = "abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/finance/revenue/"
EXPECTED_PATTERN = r"revenue_export_(\\d{{4}}-\\d{{2}}-\\d{{2}})\\.csv"

# Finance system changed format from YYYY-MM-DD to YYYYMMDD on 2026-10-03
ACTUAL_FILE = "revenue_export_20261005.csv"

print(f"[{{datetime.datetime.utcnow()}}] Starting: cleansed → conformed revenue")
print(f"Source table   : {{SOURCE_TABLE}}")
print(f"Target table   : {{TARGET_TABLE}}")
print(f"Expected format: revenue_export_YYYY-MM-DD.csv")
print(f"File found     : {{ACTUAL_FILE}}")

# COMMAND ----------

# Read cleansed table — registers UC lineage
df_cleansed = spark.table(SOURCE_TABLE)
print(f"Cleansed records read: {{df_cleansed.count():,}}")

# COMMAND ----------

# Validate filename format before processing
if not re.match(EXPECTED_PATTERN, ACTUAL_FILE):
    raise ValueError(
        f"ValueError: Filename '{{ACTUAL_FILE}}' does not match expected pattern "
        f"'revenue_export_YYYY-MM-DD.csv'.\\n"
        f"Finance system changed export format from YYYY-MM-DD to YYYYMMDD on 2026-10-03.\\n"
        f"Last file in old format: revenue_export_2026-10-02.csv"
    )
""")


def _nb_cleansed_to_conformed_inventory() -> str:
    return textwrap.dedent(f"""\
# Databricks notebook source
# MAGIC %md
# MAGIC ## ETL: Cleansed → Conformed Inventory Summary
# MAGIC Aggregates cleansed inventory data into daily summary fact table.

# COMMAND ----------

import datetime
from pyspark.sql import functions as F

SOURCE_TABLE = "{CATALOG}.{SCHEMA_CL}.inventory_daily"
TARGET_TABLE = "{CATALOG}.{SCHEMA_CF}.fact_inventory_summary"

print(f"[{{datetime.datetime.utcnow()}}] Starting: cleansed → conformed inventory summary")
print(f"Source: {{SOURCE_TABLE}}")
print(f"Target: {{TARGET_TABLE}}")

# COMMAND ----------

df = spark.table(SOURCE_TABLE)
print(f"Cleansed inventory records: {{df.count():,}}")

df_agg = df.groupBy("warehouse_id", "load_date") \\
           .agg(
               F.sum("quantity").alias("total_quantity"),
               F.countDistinct("sku").alias("distinct_skus"),
               F.sum("unit_value").alias("total_value"),
           ) \\
           .withColumn("_processed_at", F.current_timestamp())

print(f"Aggregated rows: {{df_agg.count():,}}")

# COMMAND ----------

df_agg.write.format("delta") \\
    .mode("overwrite") \\
    .option("overwriteSchema", "true") \\
    .saveAsTable(TARGET_TABLE)

print(f"[{{datetime.datetime.utcnow()}}] Completed. Written to {{TARGET_TABLE}}")
""")


NOTEBOOK_CODE = {
    "etl_raw_to_cleansed_customers":       _nb_raw_to_cleansed_customers,
    "etl_raw_to_cleansed_inventory":       _nb_raw_to_cleansed_inventory,
    "etl_raw_to_cleansed_sales":           _nb_raw_to_cleansed_sales,
    "etl_cleansed_to_conformed_revenue":   _nb_cleansed_to_conformed_revenue,
    "etl_cleansed_to_conformed_inventory": _nb_cleansed_to_conformed_inventory,
}


# ── SQL helpers ───────────────────────────────────────────────────────────────

RAW_TABLE_DDL = [
    # customers_raw
    f"""CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA_RAW}.customers_raw (
        customer_id   STRING NOT NULL,
        first_name    STRING,
        last_name     STRING,
        email         STRING,
        country       STRING,
        signup_date   DATE
    ) USING DELTA COMMENT 'Raw customer records from CRM nightly export'""",

    # inventory_raw
    f"""CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA_RAW}.inventory_raw (
        inventory_id  STRING NOT NULL,
        warehouse_id  STRING,
        sku           STRING,
        quantity      BIGINT,
        unit_value    DOUBLE,
        load_date     DATE
    ) USING DELTA COMMENT 'Raw inventory records from WMS SFTP drop'""",

    # sales_raw
    f"""CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA_RAW}.sales_raw (
        transaction_id STRING NOT NULL,
        store_id       STRING,
        product_id     STRING,
        amount         DOUBLE,
        currency       STRING,
        transaction_ts TIMESTAMP
    ) USING DELTA COMMENT 'Raw POS sales transactions from Kafka CDC'""",

    # revenue_export (cleansed source for revenue job)
    f"""CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA_CL}.revenue_export (
        revenue_id    STRING NOT NULL,
        region        STRING,
        product_line  STRING,
        gross_revenue DOUBLE,
        net_revenue   DOUBLE,
        export_date   DATE
    ) USING DELTA COMMENT 'Cleansed revenue export from finance system'""",

    # inventory_daily (cleansed — for the conformed job to read)
    f"""CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA_CL}.inventory_daily (
        inventory_id  STRING NOT NULL,
        warehouse_id  STRING,
        sku           STRING,
        quantity      BIGINT,
        unit_value    DOUBLE,
        load_date     DATE,
        _ingested_at  TIMESTAMP
    ) USING DELTA COMMENT 'Cleansed daily inventory snapshot'""",
]

RAW_SEED_DML = [
    # customers_raw — 500 rows
    f"""INSERT INTO {CATALOG}.{SCHEMA_RAW}.customers_raw
    SELECT
        CONCAT('CUST-', LPAD(CAST(id AS STRING), 5, '0'))          AS customer_id,
        CONCAT('FirstName', CAST(id AS STRING))                     AS first_name,
        CONCAT('LastName',  CAST(id AS STRING))                     AS last_name,
        CONCAT('user', CAST(id AS STRING), '@example.com')          AS email,
        CASE WHEN id % 3 = 0 THEN 'UK' WHEN id % 3 = 1 THEN 'DE' ELSE 'SI' END AS country,
        DATE_SUB(CURRENT_DATE(), CAST(id * 2 AS INT))               AS signup_date
    FROM (SELECT EXPLODE(SEQUENCE(1, 500)) AS id)""",

    # inventory_raw — 1000 rows
    f"""INSERT INTO {CATALOG}.{SCHEMA_RAW}.inventory_raw
    SELECT
        CONCAT('INV-', LPAD(CAST(id AS STRING), 6, '0'))            AS inventory_id,
        CONCAT('WH-', CAST((id % 5) + 1 AS STRING))                 AS warehouse_id,
        CONCAT('SKU-', LPAD(CAST((id % 200) + 1 AS STRING), 4,'0')) AS sku,
        CAST(id * 3 + 10 AS BIGINT)                                  AS quantity,
        ROUND(CAST(id * 0.75 + 5.0 AS DOUBLE), 2)                   AS unit_value,
        CURRENT_DATE()                                                AS load_date
    FROM (SELECT EXPLODE(SEQUENCE(1, 1000)) AS id)""",

    # sales_raw — 2000 rows
    f"""INSERT INTO {CATALOG}.{SCHEMA_RAW}.sales_raw
    SELECT
        CONCAT('TXN-', LPAD(CAST(id AS STRING), 7, '0'))            AS transaction_id,
        CONCAT('STORE-', CAST((id % 20) + 1 AS STRING))             AS store_id,
        CONCAT('PROD-', LPAD(CAST((id % 100) + 1 AS STRING),4,'0')) AS product_id,
        ROUND(CAST(id * 1.25 + 9.99 AS DOUBLE), 2)                  AS amount,
        'EUR'                                                         AS currency,
        TIMESTAMPADD(MINUTE, -id, CURRENT_TIMESTAMP())               AS transaction_ts
    FROM (SELECT EXPLODE(SEQUENCE(1, 2000)) AS id)""",

    # revenue_export (cleansed layer) — 300 rows
    f"""INSERT INTO {CATALOG}.{SCHEMA_CL}.revenue_export
    SELECT
        CONCAT('REV-', LPAD(CAST(id AS STRING), 5, '0'))            AS revenue_id,
        CASE WHEN id % 4 = 0 THEN 'UK' WHEN id % 4 = 1 THEN 'DE'
             WHEN id % 4 = 2 THEN 'SI' ELSE 'AT' END                AS region,
        CASE WHEN id % 3 = 0 THEN 'Bus' WHEN id % 3 = 1 THEN 'Rail' ELSE 'Coach' END AS product_line,
        ROUND(CAST(id * 150.0 + 500.0 AS DOUBLE), 2)                AS gross_revenue,
        ROUND(CAST(id * 120.0 + 400.0 AS DOUBLE), 2)                AS net_revenue,
        CURRENT_DATE()                                                AS export_date
    FROM (SELECT EXPLODE(SEQUENCE(1, 300)) AS id)""",

    # inventory_daily (cleansed layer) — 500 rows (for conformed job to succeed)
    f"""INSERT INTO {CATALOG}.{SCHEMA_CL}.inventory_daily
    SELECT
        CONCAT('INV-', LPAD(CAST(id AS STRING), 6, '0'))            AS inventory_id,
        CONCAT('WH-', CAST((id % 5) + 1 AS STRING))                 AS warehouse_id,
        CONCAT('SKU-', LPAD(CAST((id % 200) + 1 AS STRING),4,'0'))  AS sku,
        CAST(id * 3 + 10 AS BIGINT)                                  AS quantity,
        ROUND(CAST(id * 0.75 + 5.0 AS DOUBLE), 2)                   AS unit_value,
        CURRENT_DATE()                                                AS load_date,
        CURRENT_TIMESTAMP()                                           AS _ingested_at
    FROM (SELECT EXPLODE(SEQUENCE(1, 500)) AS id)""",
]


# ── DAB YAML generator ────────────────────────────────────────────────────────

def _dab_yaml(job: dict) -> str:
    params_block = "\n".join(
        f"              {k}: \"{v}\""
        for k, v in job.get("parameters", {}).items()
    )
    return textwrap.dedent(f"""\
# Databricks Asset Bundle — generated by scripts/setup.py
# Deploy with: databricks bundle deploy

bundle:
  name: {job['name']}

variables:
  catalog:
    default: {CATALOG}

resources:
  jobs:
    {job['name']}:
      name: {job['name']}
      description: "{job['description']}"

      schedule:
        quartz_cron_expression: "0 0 2 * * ?"
        timezone_id: UTC
        pause_status: PAUSED

      tasks:
        - task_key: main
          notebook_task:
            notebook_path: {NOTEBOOK_BASE}/{job['notebook']}
            base_parameters:
{params_block}

      # Pipeline metadata — used by RCA agent for context
      tags:
        layer:            "{job['layer']}"
        upstream_system:  "{job.get('upstream_system', '')}"
        source_table:     "{job.get('source_table', '')}"
        target_table:     "{job['target_table']}"
        target_schema:    "{job.get('target_schema', '')}"
        sla:              "{job['sla']}"
""")


# ── SDK helpers ───────────────────────────────────────────────────────────────

def _sql_exec(client: WorkspaceClient, statement: str) -> None:
    """Execute a SQL statement via the Databricks SQL Statement API."""
    warehouses = list(client.warehouses.list())
    if not warehouses:
        raise RuntimeError("No SQL warehouse found. Create one in your workspace first.")
    warehouse_id = warehouses[0].id

    response = client.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=statement,
        wait_timeout="60s",
    )
    status = response.status.state.value if response.status and response.status.state else "UNKNOWN"
    if status not in ("SUCCEEDED",):
        err = response.status.error.message if response.status and response.status.error else "unknown error"
        raise RuntimeError(f"SQL failed ({status}): {err}\nSQL: {statement[:200]}")


def _upload_notebook(client: WorkspaceClient, path: str, source: str) -> None:
    encoded = base64.b64encode(source.encode("utf-8")).decode("utf-8")
    client.workspace.import_(
        path=path,
        language=Language.PYTHON,
        content=encoded,
        overwrite=True,
        format=ImportFormat.SOURCE,
    )


def _create_job(client: WorkspaceClient, job_name: str, notebook_path: str) -> int:
    for existing in list(client.jobs.list(name=job_name)):
        client.jobs.delete(job_id=existing.job_id)
        print(f"    🗑  Deleted existing job: {job_name}")

    created = client.jobs.create(
        name=job_name,
        tasks=[jobs_sdk.Task(
            task_key="main",
            notebook_task=jobs_sdk.NotebookTask(notebook_path=notebook_path),
        )],
    )
    return created.job_id


def _run_and_wait(client: WorkspaceClient, job_id: int, job_name: str) -> str:
    run = client.jobs.run_now(job_id=job_id)
    run_id = run.run_id
    print(f"    ▶  {job_name} (run_id={run_id}) ...", end="", flush=True)
    while True:
        time.sleep(8)
        details = client.jobs.get_run(run_id=run_id)
        lc = getattr(details.state.life_cycle_state, "value", details.state.life_cycle_state)
        if lc in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
            rs = getattr(details.state.result_state, "value", details.state.result_state)
            print(f" {rs}")
            return rs
        print(".", end="", flush=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 65)
    print("  FLO 2026 Workshop — Medallion Architecture Setup")
    print("=" * 65)

    client = WorkspaceClient(
        host=Config.DATABRICKS_WORKSPACE_HOST,
        token=Config.DATABRICKS_TOKEN,
    )
    print(f"\n✅ Connected: {Config.DATABRICKS_WORKSPACE_HOST}\n")

    # ── Step 1: Unity Catalog ──────────────────────────────────────────────
    print("━" * 65)
    print("Step 1/6 — Unity Catalog: catalog + schemas")
    print("━" * 65)

    for stmt in [
        f"CREATE CATALOG IF NOT EXISTS {CATALOG} COMMENT 'FLO 2026 workshop demo — medallion architecture'",
        f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA_RAW}  COMMENT 'Raw ingestion layer'",
        f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA_CL}   COMMENT 'Cleansed / validated layer'",
        f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA_CF}   COMMENT 'Conformed / business-ready layer'",
    ]:
        _sql_exec(client, stmt)
        obj = stmt.split("IF NOT EXISTS")[1].strip().split()[0]
        print(f"  ✅ {obj}")

    # ── Step 2: Raw tables ─────────────────────────────────────────────────
    print("\n━" * 65)
    print("Step 2/6 — Creating Delta tables")
    print("━" * 65)

    for ddl in RAW_TABLE_DDL:
        table_name = ddl.split("IF NOT EXISTS")[1].strip().split()[0]
        _sql_exec(client, ddl)
        print(f"  ✅ {table_name}")

    # ── Step 3: Seed data ──────────────────────────────────────────────────
    print("\n━" * 65)
    print("Step 3/6 — Seeding raw data")
    print("━" * 65)

    for dml in RAW_SEED_DML:
        target = dml.split("INSERT INTO")[1].strip().split()[0]
        _sql_exec(client, dml)
        print(f"  ✅ {target} — seeded")

    # ── Step 4: Notebooks ──────────────────────────────────────────────────
    print("\n━" * 65)
    print("Step 4/6 — Uploading notebooks")
    print("━" * 65)

    try:
        client.workspace.mkdirs(path=NOTEBOOK_BASE)
    except Exception:
        pass

    for job in JOBS:
        nb_name  = job["notebook"]
        nb_path  = f"{NOTEBOOK_BASE}/{nb_name}"
        nb_code  = NOTEBOOK_CODE[nb_name]()
        _upload_notebook(client, nb_path, nb_code)
        print(f"  ✅ {nb_path}")

    # ── Step 5: DAB YAMLs ─────────────────────────────────────────────────
    print("\n━" * 65)
    print("Step 5/6 — Generating DAB YAML bundle files")
    print("━" * 65)

    DAB_BASE.mkdir(parents=True, exist_ok=True)
    for job in JOBS:
        dab_dir  = DAB_BASE / job["name"]
        dab_dir.mkdir(exist_ok=True)
        dab_file = dab_dir / "databricks.yml"
        dab_file.write_text(_dab_yaml(job), encoding="utf-8")
        print(f"  ✅ .dab/{job['name']}/databricks.yml")

    # ── Step 6: Deploy + run jobs ──────────────────────────────────────────
    print("\n━" * 65)
    print("Step 6/6 — Deploying and running jobs (generates UC lineage)")
    print("━" * 65)
    print("  This takes ~5 minutes (serverless cold start + execution)\n")

    job_results: list[dict] = []
    for job in JOBS:
        print(f"  ── {job['name']}")
        nb_path = f"{NOTEBOOK_BASE}/{job['notebook']}"
        job_id  = _create_job(client, job["name"], nb_path)
        print(f"    ✅ Job created (id={job_id})")
        result  = _run_and_wait(client, job_id, job["name"])
        job_results.append({
            "name":        job["name"],
            "job_id":      job_id,
            "expected":    "FAILED" if job["should_fail"] else "SUCCEEDED",
            "actual":      result,
        })

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  Setup Complete!")
    print("=" * 65)
    print(f"\n  Catalog   : {CATALOG}")
    print(f"  Schemas   : {SCHEMA_RAW}, {SCHEMA_CL}, {SCHEMA_CF}")
    print(f"  Notebooks : {NOTEBOOK_BASE}/")
    print(f"  DAB files : .dab/*/databricks.yml\n")
    print("  Job results:")
    all_ok = True
    for r in job_results:
        ok = r["actual"] == r["expected"]
        if not ok:
            all_ok = False
        icon = "✅" if ok else "⚠️ "
        print(f"    {icon} {r['name']}")
        print(f"       Expected: {r['expected']}  |  Actual: {r['actual']}")

    if all_ok:
        print("\n  ✅ All jobs ran as expected.")
    else:
        print("\n  ⚠️  Some jobs did not match expected outcome — check above.")

    print("\n  Unity Catalog lineage has been recorded for all job runs.")
    print("  Run the app: streamlit run app.py")
    print("  Select 'monitor_analyze_incident' to see the RCA agents in action.\n")


if __name__ == "__main__":
    main()
