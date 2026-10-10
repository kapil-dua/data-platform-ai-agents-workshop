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

# ── Re-seed inventory Volume CSV with null warehouse_id rows ──────────────────
print('Re-seeding inventory Volume CSV with null warehouse_id rows...')

reseed = r"""# Databricks notebook source
from datetime import datetime, timedelta, timezone

yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
path = f"/Volumes/demo_etl/raw/landing/inventory/daily/inventory_{yesterday}.csv"

rows = "inventory_id,warehouse_id,sku,quantity,unit_value,load_date\n"
rows += "\n".join(
    f"INV-{i:06d},WH-{(i%5)+1},SKU-{(i%200)+1:04d},{i*3+10},{round(i*0.75+5,2)},{yesterday}"
    for i in range(1, 201)
)
# 10 rows with null warehouse_id (~5%) — trigger DataQualityException in conformed job
rows += "\n" + "\n".join(
    f"INV-NULL-{i:04d},,SKU-{(i%200)+1:04d},{i*5},{round(i*1.5,2)},{yesterday}"
    for i in range(1, 11)
)

dbutils.fs.put(path, rows, overwrite=True)
print(f"Written: {path} (200 valid + 10 null warehouse_id rows)")

# Trigger etl_raw_to_cleansed_inventory to regenerate inventory_daily with nulls
print("Now trigger etl_raw_to_cleansed_inventory to propagate nulls to cleansed layer")
"""

from databricks.sdk.service import jobs as jobs_sdk
reseed_nb = '/Shared/demo_etl/_reseed_volume'
encoded = base64.b64encode(reseed.encode()).decode()
client.workspace.import_(path=reseed_nb, language=Language.PYTHON, content=encoded, overwrite=True, format=ImportFormat.SOURCE)

for existing in list(client.jobs.list(name='_reseed_volume')):
    client.jobs.delete(job_id=existing.job_id)
reseed_job = client.jobs.create(
    name='_reseed_volume',
    tasks=[jobs_sdk.Task(task_key='main', notebook_task=jobs_sdk.NotebookTask(notebook_path=reseed_nb))]
)
import time
reseed_run = client.jobs.run_now(job_id=reseed_job.job_id)
run_id = reseed_run.run_id
print(f'Volume reseed triggered (run_id={run_id})...')
while True:
    time.sleep(8)
    details = client.jobs.get_run(run_id=run_id)
    lc = getattr(details.state.life_cycle_state, 'value', str(details.state.life_cycle_state))
    if lc in {'TERMINATED', 'SKIPPED', 'INTERNAL_ERROR'}:
        rs = getattr(details.state.result_state, 'value', str(details.state.result_state))
        print(f'Volume reseed: {rs}')
        break
    print('.', end='', flush=True)
client.jobs.delete(job_id=reseed_job.job_id)

print()
print('Done. Now run etl_raw_to_cleansed_inventory to propagate nulls to inventory_daily,')
print('then etl_cleansed_to_conformed_inventory should fail with DataQualityException.')
print('Or just re-run the full setup script.')

