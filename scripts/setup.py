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

# COMMAND ----------

import datetime
from pyspark.sql import functions as F

today        = datetime.datetime.utcnow().strftime("%Y-%m-%d")
SOURCE_PATH  = "abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/inventory/daily/"
TARGET_TABLE = "{CATALOG}.{SCHEMA_CL}.inventory_daily"

print(f"[{{datetime.datetime.utcnow()}}] Starting: raw → cleansed inventory")
print(f"Partition date : {{today}}")
print(f"Source path    : {{SOURCE_PATH}}")
print(f"Target table   : {{TARGET_TABLE}}")

# COMMAND ----------

# Register UC lineage — read raw table before attempting file ingest
df_raw = spark.table("{CATALOG}.{SCHEMA_RAW}.inventory_raw")
print(f"Raw table records available: {{df_raw.count():,}}")

# COMMAND ----------

# Attempt to read today's incoming file
try:
    df_incoming = spark.read.format("csv") \\
        .option("header", "true") \\
        .option("inferSchema", "true") \\
        .load(SOURCE_PATH)
    incoming_count = df_incoming.filter(F.col("load_date") == today).count()
except Exception as e:
    incoming_count = 0
    print(f"Warning: could not read source path — {{e}}")

print(f"Incoming records for {{today}}: {{incoming_count}}")

# COMMAND ----------

# Validate: no data to process — raise premature exit
if incoming_count == 0:
    raise ValueError(
        f"PrematureExit: 0 incoming records found for partition {{today}}. "
        f"Expected > 0 records from source path {{SOURCE_PATH}}. "
        f"Possible causes: file not delivered, file format issue, encoding error, or empty export. "
        f"Aborting to avoid writing empty partition to {{TARGET_TABLE}}."
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

today         = datetime.datetime.utcnow().strftime("%Y-%m-%d")
SOURCE_TABLE  = "{CATALOG}.{SCHEMA_RAW}.sales_raw"
TARGET_SCHEMA = "{CATALOG}.confromed_sales"   # typo introduced in config: confromed not conformed
TARGET_TABLE  = f"{{TARGET_SCHEMA}}.sales_transactions"

print(f"[{{datetime.datetime.utcnow()}}] Starting: raw → cleansed sales transactions")
print(f"Source : {{SOURCE_TABLE}}")
print(f"Target : {{TARGET_TABLE}}")

# COMMAND ----------

# Read raw table — registers UC lineage
df_raw = spark.table(SOURCE_TABLE)
print(f"Raw records read: {{df_raw.count():,}}")

df_clean = df_raw \\
    .filter(F.col("transaction_id").isNotNull()) \\
    .filter(F.col("amount") > 0) \\
    .withColumn("_ingested_at", F.current_timestamp())

print(f"Records after validation: {{df_clean.count():,}}")

# COMMAND ----------

# Write to target — will fail if schema does not exist
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

today            = datetime.datetime.utcnow().strftime("%Y-%m-%d")
SOURCE_TABLE     = "{CATALOG}.{SCHEMA_CL}.revenue_export"
TARGET_TABLE     = "{CATALOG}.{SCHEMA_CF}.fact_revenue_daily"
SOURCE_PATH      = "abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/finance/revenue/"
EXPECTED_PATTERN = r"revenue_export_(\\d{{4}}-\\d{{2}}-\\d{{2}})\\.csv"

print(f"[{{datetime.datetime.utcnow()}}] Starting: cleansed → conformed revenue")
print(f"Source table : {{SOURCE_TABLE}}")
print(f"Target table : {{TARGET_TABLE}}")
print(f"Partition    : {{today}}")

# COMMAND ----------

# Read cleansed table — registers UC lineage
df_cleansed = spark.table(SOURCE_TABLE)
print(f"Cleansed records available: {{df_cleansed.count():,}}")

# COMMAND ----------

# Scan source path for today's file
try:
    files = [
        f.name for f in
        spark._jvm.org.apache.hadoop.fs.FileSystem
            .get(spark._jsc.hadoopConfiguration())
            .listStatus(spark._jvm.org.apache.hadoop.fs.Path(SOURCE_PATH))
    ]
except Exception:
    files = []

print(f"Files found in source path: {{files}}")

# Filter to files matching expected pattern
matching = [f for f in files if re.match(EXPECTED_PATTERN, f)]
incoming_count = len(matching)
print(f"Files matching pattern 'revenue_export_YYYY-MM-DD.csv': {{incoming_count}}")
print(f"All files present: {{files}}")

# COMMAND ----------

# Validate: no matching files — raise premature exit
if incoming_count == 0:
    raise ValueError(
        f"PrematureExit: 0 files matched pattern 'revenue_export_YYYY-MM-DD.csv' "
        f"in {{SOURCE_PATH}} for partition {{today}}. "
        f"Files present: {{files}}. "
        f"Possible causes: filename format changed, file not yet delivered, or encoding issue. "
        f"Aborting to avoid writing empty partition to {{TARGET_TABLE}}."
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


# ── DAB YAML generator (single pipeline) ─────────────────────────────────────

PIPELINE_NAME = "etl_nightly_medallion"

def _dab_pipeline_yaml() -> str:
    """Generate a single DAB YAML for the full multi-task medallion pipeline."""
    return textwrap.dedent(f"""\
# Databricks Asset Bundle — generated by scripts/setup.py
# Single pipeline covering the full medallion architecture
# Deploy with: databricks bundle deploy

bundle:
  name: {PIPELINE_NAME}

variables:
  catalog:
    default: {CATALOG}

resources:
  jobs:
    {PIPELINE_NAME}:
      name: {PIPELINE_NAME}
      description: "Nightly medallion ETL pipeline: raw → cleansed → conformed"

      schedule:
        quartz_cron_expression: "0 0 2 * * ?"
        timezone_id: UTC
        pause_status: PAUSED

      # ── Layer 1: Raw → Cleansed (runs in parallel) ──────────────────────
      tasks:
        - task_key: raw_to_cleansed_customers
          description: "Ingest raw customer records from CRM nightly export"
          notebook_task:
            notebook_path: {NOTEBOOK_BASE}/etl_raw_to_cleansed_customers
            base_parameters:
              source_table: "{CATALOG}.{SCHEMA_RAW}.customers_raw"
              target_table: "{CATALOG}.{SCHEMA_CL}.customers"
              primary_key:  "customer_id"
              sla:          "03:00 UTC"

        - task_key: raw_to_cleansed_inventory
          description: "Ingest daily inventory CSV from WMS SFTP drop (01:00 UTC)"
          notebook_task:
            notebook_path: {NOTEBOOK_BASE}/etl_raw_to_cleansed_inventory
            base_parameters:
              source_path:      "abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/inventory/daily/"
              target_table:     "{CATALOG}.{SCHEMA_CL}.inventory_daily"
              filename_pattern: "inventory_YYYY-MM-DD.csv"
              archive_path:     "abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/inventory/archive/"
              upstream_system:  "Warehouse Management System (WMS)"
              sla:              "02:00 UTC"

        - task_key: raw_to_cleansed_sales
          description: "Ingest raw POS sales transactions from Kafka CDC"
          notebook_task:
            notebook_path: {NOTEBOOK_BASE}/etl_raw_to_cleansed_sales
            base_parameters:
              source_table:  "{CATALOG}.{SCHEMA_RAW}.sales_raw"
              target_schema: "{CATALOG}.confromed_sales"
              target_table:  "{CATALOG}.confromed_sales.sales_transactions"
              upstream_system: "POS system (real-time CDC via Kafka)"
              sla:           "04:00 UTC"

        # ── Layer 2: Cleansed → Conformed (depends on Layer 1) ─────────────
        - task_key: cleansed_to_conformed_revenue
          description: "Aggregate revenue export into conformed fact table"
          depends_on:
            - task_key: raw_to_cleansed_sales
          notebook_task:
            notebook_path: {NOTEBOOK_BASE}/etl_cleansed_to_conformed_revenue
            base_parameters:
              source_path:      "abfss://{SCHEMA_RAW}@datalake.dfs.core.windows.net/finance/revenue/"
              source_table:     "{CATALOG}.{SCHEMA_CL}.revenue_export"
              target_table:     "{CATALOG}.{SCHEMA_CF}.fact_revenue_daily"
              filename_pattern: "revenue_export_YYYY-MM-DD.csv"
              upstream_system:  "Finance system revenue export (daily batch)"
              sla:              "05:00 UTC"

        - task_key: cleansed_to_conformed_inventory
          description: "Aggregate cleansed inventory into daily summary fact"
          depends_on:
            - task_key: raw_to_cleansed_inventory
          notebook_task:
            notebook_path: {NOTEBOOK_BASE}/etl_cleansed_to_conformed_inventory
            base_parameters:
              source_table: "{CATALOG}.{SCHEMA_CL}.inventory_daily"
              target_table: "{CATALOG}.{SCHEMA_CF}.fact_inventory_summary"
              aggregation:  "daily_by_warehouse"
              sla:          "06:00 UTC"

      # Pipeline-level tags — used by RCA agent for context
      tags:
        architecture:   "medallion"
        layers:         "raw,cleansed,conformed"
        catalog:        "{CATALOG}"
        pipeline_owner: "data-engineering"
        schedule:       "nightly 02:00 UTC"
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


def _create_pipeline(client: WorkspaceClient) -> int:
    """Create (or recreate) the single multi-task medallion pipeline job."""
    for existing in list(client.jobs.list(name=PIPELINE_NAME)):
        client.jobs.delete(job_id=existing.job_id)
        print(f"    🗑  Deleted existing pipeline: {PIPELINE_NAME}")

    tasks = []
    for job in JOBS:
        nb_path  = f"{NOTEBOOK_BASE}/{job['notebook']}"
        task_key = TASK_KEY_MAP[job["name"]]

        depends_on = []
        if job["layer"] == "cleansed_to_conformed":
            if "inventory" in job["name"]:
                depends_on = [jobs_sdk.TaskDependency(task_key="raw_to_cleansed_inventory")]
            elif "revenue" in job["name"]:
                depends_on = [jobs_sdk.TaskDependency(task_key="raw_to_cleansed_sales")]

        tasks.append(jobs_sdk.Task(
            task_key=task_key,
            description=job["description"],
            notebook_task=jobs_sdk.NotebookTask(
                notebook_path=nb_path,
                base_parameters={k: str(v) for k, v in job.get("parameters", {}).items()},
            ),
            depends_on=depends_on if depends_on else None,
        ))

    created = client.jobs.create(name=PIPELINE_NAME, tasks=tasks)
    return created.job_id



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

    # ── Step 5: DAB YAML ──────────────────────────────────────────────────
    print("\n━" * 65)
    print("Step 5/6 — Generating DAB YAML bundle file (single pipeline)")
    print("━" * 65)

    DAB_BASE.mkdir(parents=True, exist_ok=True)
    dab_dir  = DAB_BASE / PIPELINE_NAME
    dab_dir.mkdir(exist_ok=True)
    dab_file = dab_dir / "databricks.yml"
    dab_file.write_text(_dab_pipeline_yaml(), encoding="utf-8")
    print(f"  ✅ .dab/{PIPELINE_NAME}/databricks.yml")

    # ── Step 6: Deploy + run pipeline ─────────────────────────────────────
    print("\n━" * 65)
    print("Step 6/6 — Deploying and running the medallion pipeline")
    print("━" * 65)
    print("  This takes ~5 minutes (serverless cold start + execution)\n")

    pipeline_id = _create_pipeline(client)
    print(f"  ✅ Pipeline created: {PIPELINE_NAME} (id={pipeline_id})")

    run = client.jobs.run_now(job_id=pipeline_id)
    run_id = run.run_id
    print(f"  ▶  Pipeline triggered (run_id={run_id}) ...", end="", flush=True)

    while True:
        time.sleep(10)
        details = client.jobs.get_run(run_id=run_id, expand_tasks=True)
        lc = getattr(details.state.life_cycle_state, "value", str(details.state.life_cycle_state))
        if lc in {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}:
            rs = getattr(details.state.result_state, "value", str(details.state.result_state))
            print(f" {rs}")
            break
        print(".", end="", flush=True)

    # Show per-task results
    details = client.jobs.get_run(run_id=run_id, expand_tasks=True)
    tasks = getattr(details, "tasks", []) or []

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  Setup Complete!")
    print("=" * 65)
    print(f"\n  Catalog   : {CATALOG}")
    print(f"  Schemas   : {SCHEMA_RAW}, {SCHEMA_CL}, {SCHEMA_CF}")
    print(f"  Notebooks : {NOTEBOOK_BASE}/")
    print(f"  DAB file  : .dab/{PIPELINE_NAME}/databricks.yml")
    print(f"  Pipeline  : {PIPELINE_NAME} (job_id={pipeline_id})\n")
    print("  Task results:")
    for task in tasks:
        task_key = getattr(task, "task_key", "unknown")
        state    = task.state if hasattr(task, "state") else None
        rs       = getattr(state.result_state, "value", str(state.result_state)) if state else "UNKNOWN"
        job_def  = next((j for j in JOBS if TASK_KEY_MAP.get(j["name"]) == task_key), None)
        expected = "FAILED" if (job_def and job_def["should_fail"]) else "SUCCEEDED"
        ok       = rs == expected
        icon     = "✅" if ok else "⚠️ "
        print(f"    {icon} {task_key}: {rs} (expected {expected})")

    print("\n  Unity Catalog lineage recorded for all task runs.")
    print("  Run the app: streamlit run app.py\n")


if __name__ == "__main__":
    main()
