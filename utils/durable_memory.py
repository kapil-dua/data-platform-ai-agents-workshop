"""SQLite-backed durable memory for a lightweight operational agent demo."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any


class   WorkflowStore:
    """Persist workflow metadata and agent events in a local SQLite database.

    This is intentionally lightweight: it gives the demo durable state without
    introducing a full production storage stack.
    """

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            data_dir = os.path.join(os.getcwd(), ".sqlite")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "app_audit.db")
        self.db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    final_summary TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    job_name TEXT NOT NULL,
                    databricks_run_id TEXT,
                    severity TEXT,
                    status TEXT NOT NULL DEFAULT 'created',
                    payload_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (run_id) REFERENCES workflow_runs(run_id)
                )
                """
            )
            # Single-row table holding the most recent completed workflow result.
            # The ticker writes here; the UI reads from here.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS latest_result (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    run_id TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def start_run(self, run_id: str, task: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_runs (run_id, task, status, created_at, updated_at)
                VALUES (?, ?, 'queued', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(run_id) DO UPDATE SET
                    task = excluded.task,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (run_id, task),
            )
            conn.commit()

    def update_run(self, run_id: str, status: str | None = None, final_summary: str | None = None) -> None:
        payload: dict[str, Any] = {"updated_at": "CURRENT_TIMESTAMP"}
        if status is not None:
            payload["status"] = status
        if final_summary is not None:
            payload["final_summary"] = final_summary

        assignments = ["updated_at = CURRENT_TIMESTAMP"]
        values: list[Any] = []
        for key, value in payload.items():
            if key == "updated_at":
                continue
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(run_id)

        with self._connect() as conn:
            conn.execute(
                f"UPDATE workflow_runs SET {', '.join(assignments)} WHERE run_id = ?",
                values,
            )
            conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_id, task, status, final_summary, created_at, updated_at FROM workflow_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()

        if row is None:
            return None
        return dict(row)

    def record_event(self, run_id: str, agent_name: str, event_type: str, payload: dict[str, Any] | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_events (run_id, agent_name, event_type, payload_json)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, agent_name, event_type, json.dumps(payload or {}, ensure_ascii=False)),
            )
            conn.commit()

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, run_id, agent_name, event_type, payload_json, created_at FROM agent_events WHERE run_id = ? ORDER BY created_at ASC, id ASC",
                (run_id,),
            ).fetchall()

        events: list[dict[str, Any]] = []
        for row in rows:
            payload = row["payload_json"]
            events.append(
                {
                    "id": row["id"],
                    "run_id": row["run_id"],
                    "agent_name": row["agent_name"],
                    "event_type": row["event_type"],
                    "payload": json.loads(payload) if payload else {},
                    "created_at": row["created_at"],
                }
            )
        return events

    def record_incident(
        self,
        run_id: str,
        job_name: str,
        severity: str | None,
        payload: dict[str, Any] | None = None,
        databricks_run_id: str | None = None,
        status: str = "created",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO incidents (run_id, job_name, databricks_run_id, severity, status, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    job_name,
                    databricks_run_id,
                    severity,
                    status,
                    json.dumps(payload or {}, ensure_ascii=False),
                ),
            )
            conn.commit()

    def save_latest_result(self, run_id: str, result: dict[str, Any]) -> None:
        """Persist the most recent workflow result for the UI to read.

        Uses an upsert on id=1 so there is always at most one row — the
        latest completed run. The ticker calls this after every run.
        """
        # LangGraph interrupt objects are not JSON-serialisable — strip them.
        serialisable = {
            k: v for k, v in result.items()
            if k != "__interrupt__" and _is_json_serialisable(v)
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO latest_result (id, run_id, result_json, saved_at)
                VALUES (1, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    run_id     = excluded.run_id,
                    result_json = excluded.result_json,
                    saved_at   = CURRENT_TIMESTAMP
                """,
                (run_id, json.dumps(serialisable, ensure_ascii=False, default=str)),
            )
            conn.commit()

    def get_latest_result(self) -> dict[str, Any] | None:
        """Return the most recent workflow result saved by the ticker, or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_id, result_json, saved_at FROM latest_result WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        result = json.loads(row["result_json"])
        result["_saved_at"] = row["saved_at"]
        return result

    def get_ticker_schedule(self) -> dict[str, Any]:
        """Read the ticker schedule config persisted by the UI."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ticker_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    mode TEXT NOT NULL DEFAULT 'interval',
                    interval_min INTEGER NOT NULL DEFAULT 30,
                    cron_time TEXT NOT NULL DEFAULT '06:00',
                    task TEXT NOT NULL DEFAULT 'monitor_and_analyze',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
            row = conn.execute(
                "SELECT mode, interval_min, cron_time, task, updated_at FROM ticker_config WHERE id = 1"
            ).fetchone()
        if row is None:
            return {"mode": "interval", "interval_min": 30, "cron_time": "06:00", "task": "monitor_and_analyze"}
        return dict(row)

    def save_ticker_schedule(
        self,
        mode: str,
        interval_min: int,
        cron_time: str,
        task: str,
    ) -> None:
        """Persist ticker schedule config from the UI so the ticker can read it."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ticker_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    mode TEXT NOT NULL DEFAULT 'interval',
                    interval_min INTEGER NOT NULL DEFAULT 30,
                    cron_time TEXT NOT NULL DEFAULT '06:00',
                    task TEXT NOT NULL DEFAULT 'monitor_and_analyze',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                INSERT INTO ticker_config (id, mode, interval_min, cron_time, task, updated_at)
                VALUES (1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    mode         = excluded.mode,
                    interval_min = excluded.interval_min,
                    cron_time    = excluded.cron_time,
                    task         = excluded.task,
                    updated_at   = CURRENT_TIMESTAMP
                """,
                (mode, interval_min, cron_time, task),
            )
            conn.commit()


def _is_json_serialisable(value: Any) -> bool:
    """Return True if value can be serialised to JSON without a custom encoder."""
    try:
        json.dumps(value, default=str)
        return True
    except Exception:
        return False
