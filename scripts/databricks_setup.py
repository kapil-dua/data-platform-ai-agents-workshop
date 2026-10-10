"""
Workshop Setup Script — Medallion Architecture Demo
====================================================
Creates the full demo environment for the FLO 2026 workshop:

  1. Unity Catalog  — catalog: demo_etl, schemas: raw / cleansed / conformed + landing volume
  2. Raw tables     — seeds sample data into Delta tables
  3. Notebooks      — uploads medallion ETL notebooks to /Shared/demo_etl/
  4. DAB YAML       — writes single .dab/databricks.yml bundle (all 5 jobs)
  5. Jobs           — deploys 5 separate jobs (3 failing, 2 succeeding)
  6. Runs           — triggers all jobs in parallel (generates UC lineage)

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
from datetime import datetime, timedelta, timezone
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

# UC Volume path — modern replacement for DBFS, works even when DBFS root is disabled
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA_RAW}/landing"

TODAY      = datetime.now(timezone.utc).strftime("%Y-%m-%d")
YESTERDAY  = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

# ── Job definitions ───────────────────────────────────────────────────────────

JOBS = [
    # ── 1. FAILS — raw → cleansed customers (file not found) ──────────────
    {
        "name":        "etl_raw_to_cleansed_customers",
        "notebook":    "etl_raw_to_cleansed_customers",
        "should_fail": True,
        "layer":       "raw_to_cleansed",
        "upstream_system": "CRM system nightly batch export (02:00 UTC)",
        "source_path":     f"/Volumes/{CATALOG}/{SCHEMA_RAW}/landing/customers/daily/",
        "source_table":    f"{CATALOG}.{SCHEMA_RAW}.customers_raw",
        "target_table":    f"{CATALOG}.{SCHEMA_CL}.customers",
        "target_schema":   f"{CATALOG}.{SCHEMA_CL}",
        "filename_pattern":"customers_YYYY-MM-DD.csv",
        "sla":             "03:00 UTC",
        "description":     "Reads daily CRM customer export CSV from UC Volume. Fails if today's file not yet delivered.",
        "parameters": {
            "source_path":     f"/Volumes/{CATALOG}/{SCHEMA_RAW}/landing/customers/daily/",
            "source_table":    f"{CATALOG}.{SCHEMA_RAW}.customers_raw",
            "target_table":    f"{CATALOG}.{SCHEMA_CL}.customers",
            "filename_pattern":"customers_YYYY-MM-DD.csv",
            "FORCE_SUCCESS":   "false",
        },
    },
    # ── 2. SUCCEEDS — raw → cleansed inventory ────────────────────────────
    {
        "name":        "etl_raw_to_cleansed_inventory",
        "notebook":    "etl_raw_to_cleansed_inventory",
        "should_fail": False,
        "layer":       "raw_to_cleansed",
        "upstream_system": "Warehouse Management System (WMS) — SFTP drop at 01:00 UTC",
        "source_path":     f"/Volumes/{CATALOG}/{SCHEMA_RAW}/landing/inventory/daily/",
        "source_table":    f"{CATALOG}.{SCHEMA_RAW}.inventory_raw",  # UC lineage registration table
        "target_table":    f"{CATALOG}.{SCHEMA_CL}.inventory_daily",
        "target_schema":   f"{CATALOG}.{SCHEMA_CL}",
        "archive_path":    f"/Volumes/{CATALOG}/{SCHEMA_RAW}/landing/inventory/archive/",
        "filename_pattern":"inventory_YYYY-MM-DD.csv",
        "sla":             "02:00 UTC",
        "description":     "Reads daily inventory CSV from UC Volume landing zone, validates and writes to cleansed.inventory_daily.",
        "parameters": {
            "source_path":     f"/Volumes/{CATALOG}/{SCHEMA_RAW}/landing/inventory/daily/",
            "target_table":    f"{CATALOG}.{SCHEMA_CL}.inventory_daily",
            "filename_pattern":"inventory_YYYY-MM-DD.csv",
            "archive_path":    f"/Volumes/{CATALOG}/{SCHEMA_RAW}/landing/inventory/archive/",
        },
    },
    # ── 3. SUCCEEDS — raw → cleansed sales ───────────────────────────────
    {
        "name":        "etl_raw_to_cleansed_sales",
        "notebook":    "etl_raw_to_cleansed_sales",
        "should_fail": False,
        "layer":       "raw_to_cleansed",
        "upstream_system": "POS system (real-time CDC via Kafka → Delta)",
        "source_table":    f"{CATALOG}.{SCHEMA_RAW}.sales_raw",
        "target_table":    f"{CATALOG}.{SCHEMA_CL}.sales_transactions",
        "target_schema":   f"{CATALOG}.{SCHEMA_CL}",
        "sla":             "04:00 UTC",
        "description":     "Reads raw sales transactions, applies business rules, writes to cleansed.sales_transactions.",
        "parameters": {
            "source_table":  f"{CATALOG}.{SCHEMA_RAW}.sales_raw",
            "target_table":  f"{CATALOG}.{SCHEMA_CL}.sales_transactions",
            "target_schema": f"{CATALOG}.{SCHEMA_CL}",
        },
    },
    # ── 4. FAILS — cleansed → conformed revenue (schema mismatch) ────────
    {
        "name":        "etl_cleansed_to_conformed_revenue",
        "notebook":    "etl_cleansed_to_conformed_revenue",
        "should_fail": True,
        "layer":       "cleansed_to_conformed",
        "upstream_system": "Finance system revenue export (cleansed by etl_raw_to_cleansed_sales)",
        "source_table":    f"{CATALOG}.{SCHEMA_CL}.revenue_export",
        "target_table":    f"{CATALOG}.{SCHEMA_CF}.fact_revenue_daily",
        "target_schema":   f"{CATALOG}.{SCHEMA_CF}",
        "sla":             "05:00 UTC",
        "description":     "Aggregates cleansed revenue by region/product into conformed fact table. Fails when cleansed schema has unexpected columns.",
        "parameters": {
            "source_table":     f"{CATALOG}.{SCHEMA_CL}.revenue_export",
            "target_table":     f"{CATALOG}.{SCHEMA_CF}.fact_revenue_daily",
            "expected_schema":  "revenue_id,region,product_line,gross_revenue,net_revenue,export_date",
            "FORCE_SUCCESS":    "false",
        },
    },
    # ── 5. FAILS — cleansed → conformed inventory (data quality) ─────────
    {
        "name":        "etl_cleansed_to_conformed_inventory",
        "notebook":    "etl_cleansed_to_conformed_inventory",
        "should_fail": True,
        "layer":       "cleansed_to_conformed",
        "upstream_system": "cleansed.inventory_daily (written by etl_raw_to_cleansed_inventory)",
        "source_table":    f"{CATALOG}.{SCHEMA_CL}.inventory_daily",
        "target_table":    f"{CATALOG}.{SCHEMA_CF}.fact_inventory_summary",
        "target_schema":   f"{CATALOG}.{SCHEMA_CF}",
        "sla":             "06:00 UTC",
        "description":     "Aggregates cleansed inventory by warehouse and date. Enforces warehouse_id not null as grain key for conformed fact table.",
        "parameters": {
            "source_table":  f"{CATALOG}.{SCHEMA_CL}.inventory_daily",
            "target_table":  f"{CATALOG}.{SCHEMA_CF}.fact_inventory_summary",
            "required_key":  "warehouse_id",
            "aggregation":   "daily_by_warehouse",
            "FORCE_SUCCESS": "false",
        },
    },
]


# ── Notebook code ─────────────────────────────────────────────────────────────


def _nb_raw_to_cleansed_customers() -> str:
    return textwrap.dedent(f"""\
# Databricks notebook source
# MAGIC %md
# MAGIC ## ETL: Raw -> Cleansed Customers
# MAGIC Reads CRM daily export CSV from UC Volume. Fails when today's file is not delivered.
# MAGIC Set FORCE_SUCCESS=true to bypass (writes from raw Delta table instead).

# COMMAND ----------

dbutils.widgets.text("FORCE_SUCCESS", "false", "Force Success")
FORCE_SUCCESS = dbutils.widgets.get("FORCE_SUCCESS").lower() == "true"

from datetime import datetime, timedelta, timezone
from pyspark.sql import functions as F

# Dates computed at runtime — NOT hardcoded
today         = datetime.now(timezone.utc).strftime("%Y-%m-%d")
yesterday_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

VOLUME_PATH  = "/Volumes/{CATALOG}/{SCHEMA_RAW}/landing/customers/daily"
SOURCE_TABLE = "{CATALOG}.{SCHEMA_RAW}.customers_raw"
TARGET_TABLE = "{CATALOG}.{SCHEMA_CL}.customers"
TODAY_FILE   = f"{{VOLUME_PATH}}/customers_{{today}}.csv"

print(f"Expected file  : {{TODAY_FILE}}")
print(f"FORCE_SUCCESS  : {{FORCE_SUCCESS}}")

# Register UC lineage
df_raw = spark.table(SOURCE_TABLE)
print(f"Raw table      : {{df_raw.count()}} records")

try:
    df_incoming = spark.read.format("csv").option("header", "true").option("inferSchema", "true").load(TODAY_FILE)
    incoming_count = df_incoming.count()
    print(f"Today file found: {{incoming_count}} records")
except Exception:
    df_incoming = None
    incoming_count = 0
    print(f"Today file NOT found: {{TODAY_FILE}}")
    print(f"Last delivery: {{VOLUME_PATH}}/customers_{{yesterday_str}}.csv")

if not FORCE_SUCCESS and incoming_count == 0:
    raise FileNotFoundError(
        f"FileNotFoundError: CRM export not found for {{today}} at {{TODAY_FILE}}. "
        f"Last delivery: {{VOLUME_PATH}}/customers_{{yesterday_str}}.csv. "
        f"Possible causes: CRM nightly batch delayed, SFTP transfer failed. "
        f"Aborting to avoid stale data in {{TARGET_TABLE}}."
    )

# Use volume file if found, else fall back to raw Delta table (FORCE_SUCCESS path)
df_to_write = df_incoming if (df_incoming is not None and incoming_count > 0) else df_raw
if incoming_count == 0:
    print("FORCE_SUCCESS: falling back to raw Delta table as source")

df_clean = (df_to_write
    .filter(F.col("customer_id").isNotNull())
    .dropDuplicates(["customer_id"])
    .withColumn("load_date", F.current_date())
    .withColumn("_ingested_at", F.current_timestamp())
)

df_clean.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET_TABLE)
print(f"Completed. Written to {{TARGET_TABLE}}")
""")


def _nb_raw_to_cleansed_inventory() -> str:
    return textwrap.dedent(f"""\
# Databricks notebook source
# MAGIC %md
# MAGIC ## ETL: Raw -> Cleansed Inventory
# MAGIC Reads yesterday's inventory CSV from UC Volume (today's not yet arrived from WMS).
# MAGIC This job SUCCEEDS using yesterday's delivery.

# COMMAND ----------

from datetime import datetime, timedelta, timezone
from pyspark.sql import functions as F

yesterday_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
VOLUME_PATH   = "/Volumes/{CATALOG}/{SCHEMA_RAW}/landing/inventory/daily"
SOURCE_TABLE  = "{CATALOG}.{SCHEMA_RAW}.inventory_raw"
TARGET_TABLE  = "{CATALOG}.{SCHEMA_CL}.inventory_daily"

print(f"Reading: {{VOLUME_PATH}}/inventory_{{yesterday_str}}.csv")
print(f"Target : {{TARGET_TABLE}}")

df_raw = spark.table(SOURCE_TABLE)
print(f"Raw table: {{df_raw.count():,}} records (for UC lineage)")

try:
    df = spark.read.format("csv").option("header", "true").option("inferSchema", "true") \\
        .load(f"{{VOLUME_PATH}}/inventory_{{yesterday_str}}.csv")
    print(f"File found: {{df.count():,}} records")
except Exception as e:
    print(f"Volume file not found, reading from raw table: {{e}}")
    df = df_raw

df_clean = df \\
    .filter(F.col("inventory_id").isNotNull()) \\
    .withColumn("load_date", F.lit(yesterday_str).cast("date")) \\
    .withColumn("_ingested_at", F.current_timestamp())

df_clean.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET_TABLE)
print(f"Completed. Written to {{TARGET_TABLE}}")
""")


def _nb_raw_to_cleansed_sales() -> str:
    return textwrap.dedent(f"""\
# Databricks notebook source
# MAGIC %md
# MAGIC ## ETL: Raw -> Cleansed Sales Transactions
# MAGIC Reads raw POS sales from Delta table. This job SUCCEEDS.

# COMMAND ----------

from pyspark.sql import functions as F

SOURCE_TABLE = "{CATALOG}.{SCHEMA_RAW}.sales_raw"
TARGET_TABLE = "{CATALOG}.{SCHEMA_CL}.sales_transactions"

print(f"Source: {{SOURCE_TABLE}}")
print(f"Target: {{TARGET_TABLE}}")

df_raw = spark.table(SOURCE_TABLE)
print(f"Raw records: {{df_raw.count():,}}")

df_clean = df_raw \\
    .filter(F.col("transaction_id").isNotNull()) \\
    .filter(F.col("amount") > 0) \\
    .withColumn("_ingested_at", F.current_timestamp())

df_clean.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET_TABLE)
print(f"Completed. Written to {{TARGET_TABLE}}")
""")


def _nb_cleansed_to_conformed_revenue() -> str:
    return textwrap.dedent(f"""\
# Databricks notebook source
# MAGIC %md
# MAGIC ## ETL: Cleansed -> Conformed Revenue
# MAGIC Finance team added 'currency' column to cleansed layer — not in conformed schema.
# MAGIC This job FAILS due to schema mismatch. Set FORCE_SUCCESS=true to bypass.

# COMMAND ----------

dbutils.widgets.text("FORCE_SUCCESS", "false", "Force Success")
FORCE_SUCCESS = dbutils.widgets.get("FORCE_SUCCESS").lower() == "true"

from pyspark.sql import functions as F

SOURCE_TABLE    = "{CATALOG}.{SCHEMA_CL}.revenue_export"
TARGET_TABLE    = "{CATALOG}.{SCHEMA_CF}.fact_revenue_daily"
EXPECTED_SCHEMA = ["revenue_id", "region", "product_line", "gross_revenue", "net_revenue", "export_date"]

print(f"Source: {{SOURCE_TABLE}}")
print(f"Target: {{TARGET_TABLE}}")
print(f"Expected schema: {{EXPECTED_SCHEMA}}")

df_cleansed = spark.table(SOURCE_TABLE)
actual_cols = df_cleansed.columns
print(f"Actual schema: {{actual_cols}}")

unexpected = [c for c in actual_cols if c not in EXPECTED_SCHEMA and not c.startswith("_")]

if not FORCE_SUCCESS and unexpected:
    raise Exception(
        f"AnalysisException: Schema mismatch in {{SOURCE_TABLE}}. "
        f"Unexpected columns: {{unexpected}}. "
        f"Expected schema: {{EXPECTED_SCHEMA}}. "
        f"The cleansed layer was updated with new columns not handled by the conformed transform. "
        f"Aborting to protect data integrity of {{TARGET_TABLE}}."
    )

df_agg = df_cleansed.select(EXPECTED_SCHEMA) \\
    .groupBy("region", "product_line", "export_date") \\
    .agg(
        F.sum("gross_revenue").alias("total_gross_revenue"),
        F.sum("net_revenue").alias("total_net_revenue"),
        F.count("revenue_id").alias("record_count"),
    ) \\
    .withColumn("_processed_at", F.current_timestamp())

df_agg.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET_TABLE)
print(f"Completed. Written to {{TARGET_TABLE}}")
""")


def _nb_cleansed_to_conformed_inventory() -> str:
    return textwrap.dedent(f"""\
# Databricks notebook source
# MAGIC %md
# MAGIC ## ETL: Cleansed -> Conformed Inventory Summary
# MAGIC Fails because cleansed.inventory_daily contains null warehouse_id values (5% of records).
# MAGIC warehouse_id is the grain key for the conformed fact table — nulls cause data integrity issues.
# MAGIC Set FORCE_SUCCESS=true to bypass.

# COMMAND ----------

dbutils.widgets.text("FORCE_SUCCESS", "false", "Force Success")
FORCE_SUCCESS = dbutils.widgets.get("FORCE_SUCCESS").lower() == "true"

from pyspark.sql import functions as F

SOURCE_TABLE = "{CATALOG}.{SCHEMA_CL}.inventory_daily"
TARGET_TABLE = "{CATALOG}.{SCHEMA_CF}.fact_inventory_summary"
REQUIRED_KEY = "warehouse_id"

print(f"Source: {{SOURCE_TABLE}}")
print(f"Target: {{TARGET_TABLE}}")

df = spark.table(SOURCE_TABLE)
total = df.count()
print(f"Total records: {{total:,}}")

null_count = df.filter(F.col(REQUIRED_KEY).isNull() | (F.col(REQUIRED_KEY) == "")).count()
null_pct = round(null_count / total * 100, 1) if total > 0 else 0
print(f"Null/empty {{REQUIRED_KEY}}: {{null_count}} ({{null_pct}}%)")

if not FORCE_SUCCESS and null_count > 0:
    raise Exception(
        f"DataQualityException: {{null_count}} records ({{null_pct}}%) in {{SOURCE_TABLE}} "
        f"have null/empty {{REQUIRED_KEY}}. Required as grain key for {{TARGET_TABLE}}. "
        f"Null grain key causes incorrect aggregations and duplicate rows. "
        f"Aborting to protect data integrity of {{TARGET_TABLE}}."
    )

df_agg = df.filter(F.col(REQUIRED_KEY).isNotNull() & (F.col(REQUIRED_KEY) != "")) \\
    .groupBy("warehouse_id", "load_date") \\
    .agg(
        F.sum("quantity").alias("total_quantity"),
        F.countDistinct("sku").alias("distinct_skus"),
        F.sum("unit_value").alias("total_value"),
    ) \\
    .withColumn("_processed_at", F.current_timestamp())

df_agg.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET_TABLE)
print(f"Completed. Written to {{TARGET_TABLE}}")
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

    # revenue_export (cleansed source for revenue job) — includes currency column
    f"""CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA_CL}.revenue_export (
        revenue_id    STRING NOT NULL,
        region        STRING,
        product_line  STRING,
        gross_revenue DOUBLE,
        net_revenue   DOUBLE,
        export_date   DATE,
        currency      STRING
    ) USING DELTA COMMENT 'Cleansed revenue export from finance system — currency column added by finance team Oct 2026'""",

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

    # inventory_raw — ~5% rows with null warehouse_id
    # These flow through etl_raw_to_cleansed_inventory into cleansed.inventory_daily
    # and trigger the DataQualityException in etl_cleansed_to_conformed_inventory
    f"""INSERT INTO {CATALOG}.{SCHEMA_RAW}.inventory_raw
    SELECT
        CONCAT('INV-NULL-', LPAD(CAST(id AS STRING), 4, '0'))        AS inventory_id,
        NULL                                                           AS warehouse_id,
        CONCAT('SKU-', LPAD(CAST((id % 200) + 1 AS STRING), 4,'0'))  AS sku,
        CAST(id * 5 AS BIGINT)                                         AS quantity,
        ROUND(CAST(id * 1.5 AS DOUBLE), 2)                            AS unit_value,
        CURRENT_DATE()                                                 AS load_date
    FROM (SELECT EXPLODE(SEQUENCE(1, 50)) AS id)""",

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
    # Add currency column before inserting (finance team added this column)
    f"ALTER TABLE {CATALOG}.{SCHEMA_CL}.revenue_export ADD COLUMNS (currency STRING)",

    f"""INSERT INTO {CATALOG}.{SCHEMA_CL}.revenue_export
    SELECT
        CONCAT('REV-', LPAD(CAST(id AS STRING), 5, '0'))            AS revenue_id,
        CASE WHEN id % 4 = 0 THEN 'UK' WHEN id % 4 = 1 THEN 'DE'
             WHEN id % 4 = 2 THEN 'SI' ELSE 'AT' END                AS region,
        CASE WHEN id % 3 = 0 THEN 'Bus' WHEN id % 3 = 1 THEN 'Rail' ELSE 'Coach' END AS product_line,
        ROUND(CAST(id * 150.0 + 500.0 AS DOUBLE), 2)                AS gross_revenue,
        ROUND(CAST(id * 120.0 + 400.0 AS DOUBLE), 2)                AS net_revenue,
        CURRENT_DATE()                                                AS export_date,
        CASE WHEN id % 3 = 0 THEN 'GBP' WHEN id % 3 = 1 THEN 'EUR' ELSE 'EUR' END AS currency
    FROM (SELECT EXPLODE(SEQUENCE(1, 300)) AS id)""",

    # inventory_daily is written by etl_raw_to_cleansed_inventory job (not seeded here)
    # The null warehouse_id records come from inventory_raw and flow through the cleansed job
]


# ── DAB YAML generator — single bundle, all jobs ─────────────────────────────
BUNDLE_NAME = "demo_etl_medallion"

def _dab_bundle_yaml() -> str:
    """Single databricks.yml covering all 5 medallion jobs per DAB convention."""
    jobs_block = ""
    for job in JOBS:
        params_lines = "\n".join(
            f"              {k}: \"{v}\""
            for k, v in job.get("parameters", {}).items()
        )
        jobs_block += textwrap.dedent(f"""
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
{params_lines}
      tags:
        layer:            "{job['layer']}"
        upstream_system:  "{job.get('upstream_system', '')}"
        source_table:     "{job.get('source_table', '')}"
        target_table:     "{job.get('target_table', '')}"
        target_schema:    "{job.get('target_schema', '')}"
        sla:              "{job.get('sla', '')}"
""")

    return textwrap.dedent(f"""\
# Databricks Asset Bundle — generated by scripts/databricks_setup.py
# One file, all medallion jobs. Deploy with: databricks bundle deploy

bundle:
  name: {BUNDLE_NAME}

variables:
  catalog:
    default: {CATALOG}

resources:
  jobs:
{jobs_block}
""")


# Per-task context map — used by DABContextLoader and RCA agent
TASK_CONTEXT = {job["name"]: job for job in JOBS}
TASK_KEY_MAP = {
    "etl_raw_to_cleansed_customers":       "raw_to_cleansed_customers",
    "etl_raw_to_cleansed_inventory":       "raw_to_cleansed_inventory",
    "etl_raw_to_cleansed_sales":           "raw_to_cleansed_sales",
    "etl_cleansed_to_conformed_revenue":   "cleansed_to_conformed_revenue",
    "etl_cleansed_to_conformed_inventory": "cleansed_to_conformed_inventory",
}


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
        wait_timeout="50s",
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
    """Create (or recreate) a single-task notebook job."""
    for existing in list(client.jobs.list(name=job_name)):
        client.jobs.delete(job_id=existing.job_id)
    created = client.jobs.create(
        name=job_name,
        tasks=[jobs_sdk.Task(
            task_key="main",
            notebook_task=jobs_sdk.NotebookTask(notebook_path=notebook_path),
        )],
    )
    return created.job_id


def _run_job(client: WorkspaceClient, job_id: int, job_name: str) -> tuple[int, str]:
    """Trigger a job run, return (run_id, job_name)."""
    run = client.jobs.run_now(job_id=job_id)
    return run.run_id, job_name


def _wait_for_run(client: WorkspaceClient, run_id: int, job_name: str) -> str:
    """Wait for a run to reach terminal state, return result state string."""
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
        f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA_RAW}.landing COMMENT 'Landing zone for raw file drops — customers and inventory CSVs'",
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
        # Handle ALTER TABLE separately — ignore "column already exists" errors
        if dml.strip().upper().startswith("ALTER TABLE"):
            try:
                _sql_exec(client, dml)
                print(f"  ✅ {dml.strip()[:70]}")
            except RuntimeError as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    print(f"  ⚠️  Column already exists — skipping")
                else:
                    raise
            continue
        _sql_exec(client, dml)
        if "INSERT INTO" in dml:
            target = dml.split("INSERT INTO")[1].strip().split()[0]
            print(f"  ✅ {target} — seeded")

    # ── Step 3.5: Seed Volume files ───────────────────────────────────────
    print("\n━" * 65)
    print("Step 3.5 — Seeding landing zone files in UC Volume")
    print("━" * 65)

    volume_setup_nb = f"{NOTEBOOK_BASE}/_volume_setup"
    volume_setup_code = textwrap.dedent(f"""\
# Databricks notebook source
# Setup: write sample files to Unity Catalog Volume landing zone

from datetime import datetime, timedelta, timezone

yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")

base = "{VOLUME_PATH}"

# ── Create directory structure ──────────────────────────────────────────────
for path in [
    f"{{base}}/customers/daily",
    f"{{base}}/inventory/daily",
    f"{{base}}/inventory/archive",
]:
    dbutils.fs.mkdirs(path)

# ── Customers: only yesterday's file (today's not yet delivered) ────────────
customers_rows = "customer_id,first_name,last_name,email,country,signup_date\\n"
customers_rows += "\\n".join(
    f"CUST-{{i:05d}},First{{i}},Last{{i}},user{{i}}@example.com,{{['UK','DE','SI'][i%3]}},{{yesterday}}"
    for i in range(1, 201)
)
dbutils.fs.put(f"{{base}}/customers/daily/customers_{{yesterday}}.csv", customers_rows, overwrite=True)
print(f"Written: {{base}}/customers/daily/customers_{{yesterday}}.csv (200 rows)")
print(f"NOTE: customers_{{today}}.csv intentionally absent — simulates CRM delivery delay")

# ── Inventory: only yesterday's file (today's not yet delivered) ─────────────
inventory_rows = "inventory_id,warehouse_id,sku,quantity,unit_value,load_date\\n"
inventory_rows += "\\n".join(
    f"INV-{{i:06d}},WH-{{(i%5)+1}},SKU-{{(i%200)+1:04d}},{{i*3+10}},{{round(i*0.75+5,2)}},{{yesterday}}"
    for i in range(1, 301)
)
# Add ~5% rows with empty warehouse_id — these trigger DataQualityException
# in etl_cleansed_to_conformed_inventory (null grain key check)
inventory_rows += "\\n" + "\\n".join(
    f"INV-NULL-{{i:04d}},,SKU-{{(i%200)+1:04d}},{{i*5}},{{round(i*1.5,2)}},{{yesterday}}"
    for i in range(1, 16)
)
dbutils.fs.put(f"{{base}}/inventory/daily/inventory_{{yesterday}}.csv", inventory_rows, overwrite=True)
print(f"Written: {{base}}/inventory/daily/inventory_{{yesterday}}.csv (300 valid + 15 null warehouse rows)")
print(f"NOTE: inventory_{{today}}.csv intentionally absent — simulates WMS delivery delay")

print("Volume seeding complete.")
print(f"Volume path: {{base}}")
""")
    _upload_notebook(client, volume_setup_nb, volume_setup_code)
    for existing in list(client.jobs.list(name="_volume_setup")):
        client.jobs.delete(job_id=existing.job_id)
    vol_job = client.jobs.create(
        name="_volume_setup",
        tasks=[jobs_sdk.Task(
            task_key="main",
            notebook_task=jobs_sdk.NotebookTask(notebook_path=volume_setup_nb),
        )],
    )
    vol_run = client.jobs.run_now(job_id=vol_job.job_id)
    _wait_for_run(client, vol_run.run_id, "_volume_setup")
    client.jobs.delete(job_id=vol_job.job_id)
    print("  ✅ Volume files seeded")

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

    # ── Step 5: DAB YAML ──────────────────────────────────────────────────
    print("\n━" * 65)
    print("Step 5/6 — Generating DAB bundle (single databricks.yml, all jobs)")
    print("━" * 65)

    DAB_BASE.mkdir(parents=True, exist_ok=True)

    # Remove old per-job subdirectories if they exist (legacy from pipeline approach)
    import shutil
    for old_dir in DAB_BASE.iterdir():
        if old_dir.is_dir():
            shutil.rmtree(old_dir)
            print(f"  🗑  Removed old DAB dir: {old_dir.name}/")

    dab_file = DAB_BASE / "databricks.yml"
    dab_file.write_text(_dab_bundle_yaml(), encoding="utf-8")
    print(f"  ✅ .dab/databricks.yml ({len(JOBS)} jobs)")

    # ── Step 6: Deploy + run all jobs in parallel ──────────────────────────
    print("\n━" * 65)
    print("Step 6/6 — Deploying and running all jobs in parallel")
    print("━" * 65)
    print("  Creating jobs...\n")

    job_ids: dict[str, int] = {}
    for job in JOBS:
        nb_path = f"{NOTEBOOK_BASE}/{job['notebook']}"
        job_id  = _create_job(client, job["name"], nb_path)
        job_ids[job["name"]] = job_id
        print(f"  ✅ {job['name']} (id={job_id})")

    print("\n  Triggering all runs simultaneously...\n")

    import concurrent.futures

    # Trigger all runs in parallel
    run_map: dict[int, str] = {}  # run_id → job_name
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(JOBS)) as ex:
        futures = {
            ex.submit(_run_job, client, job_id, job_name): job_name
            for job_name, job_id in job_ids.items()
        }
        for future in concurrent.futures.as_completed(futures):
            run_id, job_name = future.result()
            run_map[run_id] = job_name
            print(f"  ▶  {job_name} → run_id={run_id}")

    print("\n  Waiting for all runs to complete...\n")

    # Wait for all runs in parallel
    results: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(run_map)) as ex:
        futures = {
            ex.submit(_wait_for_run, client, run_id, job_name): job_name
            for run_id, job_name in run_map.items()
        }
        for future in concurrent.futures.as_completed(futures):
            job_name = futures[future]
            results[job_name] = future.result()

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  Setup Complete!")
    print("=" * 65)
    print(f"\n  Catalog   : {CATALOG}")
    print(f"  Schemas   : {SCHEMA_RAW}, {SCHEMA_CL}, {SCHEMA_CF}")
    print(f"  Notebooks : {NOTEBOOK_BASE}/")
    print(f"  DAB file  : .dab/databricks.yml\n")
    print("  Job results:")
    for job in JOBS:
        actual   = results.get(job["name"], "UNKNOWN")
        expected = "FAILED" if job["should_fail"] else "SUCCEEDED"
        ok       = actual == expected
        icon     = "✅" if ok else "⚠️ "
        print(f"    {icon} {job['name']}: {actual} (expected {expected})")

    print("\n  Unity Catalog lineage recorded for all job runs.")
    print("  Run the app: streamlit run app.py\n")


if __name__ == "__main__":
    main()
