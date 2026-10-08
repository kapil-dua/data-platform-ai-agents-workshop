"""
Unity Catalog Lineage Fetcher
==============================
Queries system.access.table_lineage to retrieve upstream/downstream
context for a failed job — who does it depend on, and who depends on it.

This tells the RCA agent:
  - What tables the job historically read from (upstream dependencies)
  - What tables the job historically wrote to (its output)
  - What other jobs/notebooks read from its output (downstream consumers)
  - When the last successful write happened

Uses the Databricks SQL Statement Execution API — no Spark cluster needed.

Usage:
    fetcher = UCLineageFetcher(client)
    context = fetcher.get_lineage_context(job_name="etl_raw_to_cleansed_inventory", job_id=12345)
    prompt_text = fetcher.format_for_prompt(context)
"""

from __future__ import annotations

import json
from typing import Any

from databricks.sdk import WorkspaceClient


class UCLineageFetcher:
    """Fetches Unity Catalog lineage context for a failed job."""

    def __init__(self, client: WorkspaceClient) -> None:
        self.client = client
        self._warehouse_id: str | None = None

    def _get_warehouse_id(self) -> str:
        """Get the first available SQL warehouse (cached)."""
        if self._warehouse_id:
            return self._warehouse_id
        warehouses = list(self.client.warehouses.list())
        if not warehouses:
            raise RuntimeError("No SQL warehouse found in workspace.")
        self._warehouse_id = warehouses[0].id
        return self._warehouse_id

    def _run_sql(self, sql: str) -> list[dict[str, Any]]:
        """Execute SQL via Statement API and return rows as list of dicts."""
        try:
            response = self.client.statement_execution.execute_statement(
                warehouse_id=self._get_warehouse_id(),
                statement=sql,
                wait_timeout="30s",
            )
            state = getattr(response.status.state, "value", str(response.status.state))
            if state != "SUCCEEDED":
                return []

            result = response.result
            if not result or not result.data_array:
                return []

            # Build column name list from schema
            cols = []
            if response.manifest and response.manifest.schema and response.manifest.schema.columns:
                cols = [c.name for c in response.manifest.schema.columns]

            return [dict(zip(cols, row)) for row in result.data_array]

        except Exception as e:
            print(f"[UCLineageFetcher] SQL query failed: {e}")
            return []

    def get_lineage_context(
        self,
        job_name: str,
        job_id: int | str | None = None,
        lookback_days: int = 30,
    ) -> dict[str, Any]:
        """
        Fetch lineage context for a job from system.access.table_lineage.

        Args:
            job_name:      Databricks job name (for display)
            job_id:        Databricks job ID (used to filter lineage by entity_id)
            lookback_days: How many days of lineage history to search

        Returns:
            Dict with tables_read, tables_written, downstream_consumers,
            last_write_time, and lineage_available flag.
        """
        context: dict[str, Any] = {
            "job_name":            job_name,
            "job_id":              str(job_id) if job_id else None,
            "lineage_available":   False,
            "tables_read":         [],
            "tables_written":      [],
            "downstream_consumers":[],
            "last_write_time":     None,
        }

        if not job_id:
            return context

        # ── What tables did this job READ? ─────────────────────────────────
        reads_sql = f"""
        SELECT DISTINCT
            source_table_full_name,
            source_path,
            source_type,
            MAX(event_time) AS last_read_time
        FROM system.access.table_lineage
        WHERE entity_type = 'JOB'
          AND entity_id   = '{job_id}'
          AND source_table_full_name IS NOT NULL
          AND event_date >= DATE_SUB(CURRENT_DATE(), {lookback_days})
        GROUP BY source_table_full_name, source_path, source_type
        ORDER BY last_read_time DESC
        """
        reads = self._run_sql(reads_sql)
        context["tables_read"] = [
            {
                "table": r.get("source_table_full_name", ""),
                "path":  r.get("source_path", ""),
                "type":  r.get("source_type", ""),
                "last_read": r.get("last_read_time", ""),
            }
            for r in reads
        ]

        # ── What tables did this job WRITE? ────────────────────────────────
        writes_sql = f"""
        SELECT DISTINCT
            target_table_full_name,
            target_path,
            target_type,
            MAX(event_time) AS last_write_time
        FROM system.access.table_lineage
        WHERE entity_type = 'JOB'
          AND entity_id   = '{job_id}'
          AND target_table_full_name IS NOT NULL
          AND event_date >= DATE_SUB(CURRENT_DATE(), {lookback_days})
        GROUP BY target_table_full_name, target_path, target_type
        ORDER BY last_write_time DESC
        """
        writes = self._run_sql(writes_sql)
        context["tables_written"] = [
            {
                "table": w.get("target_table_full_name", ""),
                "path":  w.get("target_path", ""),
                "type":  w.get("target_type", ""),
                "last_write": w.get("last_write_time", ""),
            }
            for w in writes
        ]

        # Last write time (most recent)
        if writes:
            context["last_write_time"] = writes[0].get("last_write_time")

        # ── Who reads from this job's OUTPUT? (downstream consumers) ───────
        if context["tables_written"]:
            written_tables = [
                f"'{w['table']}'"
                for w in context["tables_written"]
                if w["table"]
            ]
            if written_tables:
                tables_in = ", ".join(written_tables)
                downstream_sql = f"""
                SELECT DISTINCT
                    entity_type,
                    entity_id,
                    entity_metadata.job_info.job_id    AS downstream_job_id,
                    entity_metadata.notebook_id        AS downstream_notebook_id,
                    source_table_full_name             AS reads_from_table,
                    MAX(event_time)                    AS last_seen
                FROM system.access.table_lineage
                WHERE source_table_full_name IN ({tables_in})
                  AND (entity_id IS NULL OR entity_id != '{job_id}')
                  AND event_date >= DATE_SUB(CURRENT_DATE(), {lookback_days})
                GROUP BY entity_type, entity_id,
                         entity_metadata.job_info.job_id,
                         entity_metadata.notebook_id,
                         source_table_full_name
                ORDER BY last_seen DESC
                LIMIT 20
                """
                downstream = self._run_sql(downstream_sql)
                context["downstream_consumers"] = [
                    {
                        "entity_type": d.get("entity_type", ""),
                        "entity_id":   d.get("entity_id", ""),
                        "job_id":      d.get("downstream_job_id", ""),
                        "notebook_id": d.get("downstream_notebook_id", ""),
                        "reads_table": d.get("reads_from_table", ""),
                        "last_seen":   d.get("last_seen", ""),
                    }
                    for d in downstream
                ]

        context["lineage_available"] = bool(
            context["tables_read"] or context["tables_written"]
        )
        return context

    def format_for_prompt(self, context: dict[str, Any]) -> str:
        """Format lineage context as readable text for LLM prompt injection."""
        if not context.get("lineage_available"):
            return (
                "Unity Catalog lineage: No lineage records found for this job in the last 30 days. "
                "This may mean the job has never successfully read/written a Delta table, "
                "or system.access.table_lineage is not enabled in this workspace."
            )

        lines = ["Unity Catalog Lineage Context:"]

        if context["tables_read"]:
            lines.append("\nUpstream tables this job reads from:")
            for t in context["tables_read"]:
                lines.append(f"  - {t['table']} (type: {t['type']}, last read: {t['last_read']})")

        if context["tables_written"]:
            lines.append("\nDownstream tables this job writes to:")
            for t in context["tables_written"]:
                lines.append(f"  - {t['table']} (type: {t['type']}, last write: {t['last_write']})")

        if context["last_write_time"]:
            lines.append(f"\nLast successful write: {context['last_write_time']}")

        if context["downstream_consumers"]:
            lines.append("\nDownstream consumers (jobs/notebooks reading this job's output):")
            for d in context["downstream_consumers"]:
                entity = d.get("entity_type", "unknown")
                eid    = d.get("job_id") or d.get("notebook_id") or d.get("entity_id", "")
                table  = d.get("reads_table", "")
                lines.append(f"  - {entity} (id={eid}) reads from {table}")
            lines.append(
                f"\n  ⚠️  IMPACT: {len(context['downstream_consumers'])} downstream consumer(s) "
                "will be affected if this job's output is stale or missing."
            )

        return "\n".join(lines)
