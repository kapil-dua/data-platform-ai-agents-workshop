"""
Unity Catalog Lineage Fetcher
==============================
Queries system.access.table_lineage to retrieve upstream/downstream
context for a failed job.

Approach: query by the job's target/source TABLE NAMES, not job_id.
This works reliably even when jobs are recreated (new job_ids) because
UC lineage is recorded against tables, not job objects.

The job_id is used as a hint when available, but we don't rely on it.
"""

from __future__ import annotations
from typing import Any
from databricks.sdk import WorkspaceClient


class UCLineageFetcher:
    """Fetches Unity Catalog lineage context for a failed job."""

    def __init__(self, client: WorkspaceClient) -> None:
        self.client = client
        self._warehouse_id: str | None = None

    def _get_warehouse_id(self) -> str:
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
        source_table: str | None = None,
        target_table: str | None = None,
    ) -> dict[str, Any]:
        """Fetch lineage for a job using table names as the primary key.

        UC lineage is queried purely from system.access.table_lineage —
        no DAB context is used here. DAB context is added separately by
        the RCA agent for job design intent.

        Args:
            job_name:     Job name (display only)
            job_id:       Job ID — used as a filter hint, not primary key
            lookback_days: Days of history to search
            source_table: Source table hint (from DAB, for fallback)
            target_table: Target table hint (from DAB, for fallback)
        """
        context: dict[str, Any] = {
            "job_name":            job_name,
            "job_id":              str(job_id) if job_id else None,
            "lineage_available":   False,
            "tables_read":         [],
            "tables_written":      [],
            "downstream_consumers": [],
            "last_write_time":     None,
        }

        # ── Step 1: find what this job wrote (by job_id first, table name fallback) ──
        written = self._find_tables_written(job_id, target_table, lookback_days)
        context["tables_written"] = written
        if written:
            context["last_write_time"] = written[0].get("last_write")

        # ── Step 2: find what this job read (by job_id first, table name fallback) ──
        read = self._find_tables_read(job_id, source_table, lookback_days)
        context["tables_read"] = read

        # ── Step 3: find downstream consumers of what this job wrote ─────────────
        if written:
            written_names = [w["table"] for w in written if w["table"]]
            context["downstream_consumers"] = self._find_downstream(
                written_names, job_id, lookback_days
            )

        context["lineage_available"] = bool(written or read)
        return context

    def _find_tables_written(
        self, job_id, target_hint: str | None, days: int
    ) -> list[dict]:
        """Find tables this job wrote — try job_id first, then target hint."""
        # Try by job_id
        if job_id:
            rows = self._run_sql(f"""
                SELECT DISTINCT target_table_full_name, target_type,
                    MAX(event_time) AS last_write
                FROM system.access.table_lineage
                WHERE entity_type = 'JOB' AND entity_id = '{job_id}'
                  AND target_table_full_name IS NOT NULL
                  AND event_date >= DATE_SUB(CURRENT_DATE(), {days})
                GROUP BY target_table_full_name, target_type
                ORDER BY last_write DESC
            """)
            if rows:
                return [{"table": r.get("target_table_full_name",""),
                         "type": r.get("target_type",""),
                         "last_write": r.get("last_write","")} for r in rows]

        # Fallback: find any job that recently wrote to the target hint table
        if target_hint:
            rows = self._run_sql(f"""
                SELECT DISTINCT target_table_full_name, target_type,
                    MAX(event_time) AS last_write
                FROM system.access.table_lineage
                WHERE target_table_full_name = '{target_hint}'
                  AND entity_type = 'JOB'
                  AND event_date >= DATE_SUB(CURRENT_DATE(), {days})
                GROUP BY target_table_full_name, target_type
                ORDER BY last_write DESC LIMIT 1
            """)
            if rows:
                return [{"table": r.get("target_table_full_name",""),
                         "type": r.get("target_type",""),
                         "last_write": r.get("last_write","")} for r in rows]
        return []

    def _find_tables_read(
        self, job_id, source_hint: str | None, days: int
    ) -> list[dict]:
        """Find tables this job read — try job_id first, then source hint."""
        if job_id:
            rows = self._run_sql(f"""
                SELECT DISTINCT source_table_full_name, source_type,
                    MAX(event_time) AS last_read
                FROM system.access.table_lineage
                WHERE entity_type = 'JOB' AND entity_id = '{job_id}'
                  AND source_table_full_name IS NOT NULL
                  AND event_date >= DATE_SUB(CURRENT_DATE(), {days})
                GROUP BY source_table_full_name, source_type
                ORDER BY last_read DESC
            """)
            if rows:
                return [{"table": r.get("source_table_full_name",""),
                         "type": r.get("source_type",""),
                         "last_read": r.get("last_read","")} for r in rows]

        if source_hint:
            rows = self._run_sql(f"""
                SELECT DISTINCT source_table_full_name, source_type,
                    MAX(event_time) AS last_read
                FROM system.access.table_lineage
                WHERE source_table_full_name = '{source_hint}'
                  AND entity_type = 'JOB'
                  AND event_date >= DATE_SUB(CURRENT_DATE(), {days})
                GROUP BY source_table_full_name, source_type
                ORDER BY last_read DESC LIMIT 1
            """)
            if rows:
                return [{"table": r.get("source_table_full_name",""),
                         "type": r.get("source_type",""),
                         "last_read": r.get("last_read","")} for r in rows]
        return []

    def _find_downstream(
        self, table_names: list[str], exclude_job_id, days: int
    ) -> list[dict]:
        """Find jobs/notebooks that read from the given tables (downstream consumers)."""
        if not table_names:
            return []
        quoted = ", ".join(f"'{t}'" for t in table_names)
        exclude = f"AND entity_id != '{exclude_job_id}'" if exclude_job_id else ""
        rows = self._run_sql(f"""
            SELECT DISTINCT
                entity_type,
                entity_id,
                entity_metadata.job_info.job_id    AS downstream_job_id,
                entity_metadata.notebook_id        AS downstream_notebook_id,
                source_table_full_name             AS reads_from_table,
                MAX(event_time)                    AS last_seen
            FROM system.access.table_lineage
            WHERE source_table_full_name IN ({quoted})
              {exclude}
              AND event_date >= DATE_SUB(CURRENT_DATE(), {days})
            GROUP BY entity_type, entity_id,
                     entity_metadata.job_info.job_id,
                     entity_metadata.notebook_id,
                     source_table_full_name
            ORDER BY last_seen DESC
            LIMIT 20
        """)
        return [
            {"entity_type": d.get("entity_type",""), "entity_id": d.get("entity_id",""),
             "job_id": d.get("downstream_job_id",""), "notebook_id": d.get("downstream_notebook_id",""),
             "reads_table": d.get("reads_from_table",""), "last_seen": d.get("last_seen","")}
            for d in rows
        ]

    def format_for_prompt(self, context: dict[str, Any]) -> str:
        """Format lineage context as readable text for LLM prompt injection."""
        if not context.get("lineage_available"):
            return (
                "Unity Catalog lineage: No lineage records found for this job. "
                "The job may not have successfully read/written Delta tables yet, "
                "or system.access.table_lineage may not be enabled in this workspace."
            )

        lines = ["Unity Catalog Lineage Context (from actual runtime execution):"]

        if context["tables_read"]:
            lines.append("\nUpstream tables this job reads from:")
            for t in context["tables_read"]:
                lines.append(f"  - {t['table']} (type: {t.get('type','?')}, last read: {t.get('last_read','?')})")

        if context["tables_written"]:
            lines.append("\nDownstream tables this job writes to:")
            for t in context["tables_written"]:
                lines.append(f"  - {t['table']} (type: {t.get('type','?')}, last write: {t.get('last_write','?')})")

        if context.get("last_write_time"):
            lines.append(f"\nLast successful write: {context['last_write_time']}")

        if context["downstream_consumers"]:
            lines.append("\nDownstream consumers (other jobs/notebooks reading this job's output):")
            for d in context["downstream_consumers"]:
                eid = d.get("job_id") or d.get("notebook_id") or d.get("entity_id", "")
                lines.append(f"  - {d.get('entity_type','?')} (id={eid}) reads from {d.get('reads_table','?')}")
            lines.append(
                f"\n  IMPACT: {len(context['downstream_consumers'])} downstream consumer(s) "
                "will be affected if this job's output is stale or missing."
            )

        return "\n".join(lines)
