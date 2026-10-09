"""Fix customers notebook — dynamic dates, proper FORCE_SUCCESS write path."""
import base64, sys
sys.path.insert(0, r'C:\Users\shubhanipandey\OneDrive - Nagarro\Desktop\Workspace\LEARNING\FLO\2026\data-platform-ai-agents')
from dotenv import load_dotenv
load_dotenv(r'C:\Users\shubhanipandey\OneDrive - Nagarro\Desktop\Workspace\LEARNING\FLO\2026\data-platform-ai-agents\.env')
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.workspace import Language, ImportFormat
from config import Config

client = WorkspaceClient(host=Config.DATABRICKS_WORKSPACE_HOST, token=Config.DATABRICKS_TOKEN)

# Build the notebook code using string concatenation to avoid escape issues
lines = [
    "# Databricks notebook source",
    'dbutils.widgets.text("FORCE_SUCCESS", "false", "Force Success")',
    'FORCE_SUCCESS = dbutils.widgets.get("FORCE_SUCCESS").lower() == "true"',
    "",
    "from datetime import datetime, timedelta, timezone",
    "from pyspark.sql import functions as F",
    "",
    "# Dates computed at runtime — NOT hardcoded",
    'today         = datetime.now(timezone.utc).strftime("%Y-%m-%d")',
    'yesterday_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")',
    "",
    'VOLUME_PATH  = "/Volumes/demo_etl/raw/landing/customers/daily"',
    'SOURCE_TABLE = "demo_etl.raw.customers_raw"',
    'TARGET_TABLE = "demo_etl.cleansed.customers"',
    'TODAY_FILE   = f"{VOLUME_PATH}/customers_{today}.csv"',
    "",
    'print(f"Expected file  : {TODAY_FILE}")',
    'print(f"FORCE_SUCCESS  : {FORCE_SUCCESS}")',
    "",
    "# Register UC lineage",
    "df_raw = spark.table(SOURCE_TABLE)",
    'print(f"Raw table      : {df_raw.count()} records")',
    "",
    "try:",
    '    df_incoming = spark.read.format("csv").option("header", "true").option("inferSchema", "true").load(TODAY_FILE)',
    "    incoming_count = df_incoming.count()",
    '    print(f"Today file found: {incoming_count} records")',
    "except Exception:",
    "    df_incoming = None",
    "    incoming_count = 0",
    '    print(f"Today file NOT found: {TODAY_FILE}")',
    '    print(f"Last delivery: {VOLUME_PATH}/customers_{yesterday_str}.csv")',
    "",
    "if not FORCE_SUCCESS and incoming_count == 0:",
    "    raise FileNotFoundError(",
    '        f"FileNotFoundError: CRM export not found for {today} at {TODAY_FILE}. "',
    '        f"Last delivery: {VOLUME_PATH}/customers_{yesterday_str}.csv. "',
    '        f"Possible causes: CRM nightly batch delayed, SFTP transfer failed. "',
    '        f"Aborting to avoid stale data in {TARGET_TABLE}."',
    "    )",
    "",
    "# Use volume file if found, else fall back to raw Delta table (FORCE_SUCCESS path)",
    "df_to_write = df_incoming if (df_incoming is not None and incoming_count > 0) else df_raw",
    "if incoming_count == 0:",
    '    print("FORCE_SUCCESS: falling back to raw Delta table as source")',
    "",
    "df_clean = (df_to_write",
    '    .filter(F.col("customer_id").isNotNull())',
    '    .dropDuplicates(["customer_id"])',
    '    .withColumn("load_date", F.current_date())',
    '    .withColumn("_ingested_at", F.current_timestamp())',
    ")",
    "",
    'df_clean.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(TARGET_TABLE)',
    'print(f"Completed. Written to {TARGET_TABLE}")',
]

code = "\n".join(lines)

encoded = base64.b64encode(code.encode()).decode()
client.workspace.import_(
    path='/Shared/demo_etl/etl_raw_to_cleansed_customers',
    language=Language.PYTHON,
    content=encoded,
    overwrite=True,
    format=ImportFormat.SOURCE,
)
print('Uploaded customers notebook successfully')
