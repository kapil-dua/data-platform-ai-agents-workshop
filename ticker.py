"""
Background Ticker — runs the monitoring workflow on a configurable schedule.

The ticker runs independently of the Streamlit UI. It writes results to the
shared SQLite store so the UI can read and display them without triggering
any agent runs itself.

Schedule modes (set via .env or CLI args):
  - interval:  run every N minutes  (default: every 30 minutes)
  - cron:      run at a fixed time   (e.g. "06:00" runs daily at 06:00)

Usage:
    # Run every 30 minutes (default)
    python ticker.py

    # Run every 10 minutes
    python ticker.py --interval 10

    # Run daily at 06:30
    python ticker.py --cron 06:30

    # Run once immediately and exit (useful for testing)
    python ticker.py --once

Environment variables (all optional — override defaults):
    TICKER_MODE          interval | cron         (default: interval)
    TICKER_INTERVAL_MIN  integer minutes          (default: 30)
    TICKER_CRON_TIME     HH:MM string             (default: 06:00)
    TICKER_TASK          monitor | monitor_and_analyze | monitor_analyze_incident
                                                  (default: monitor_and_analyze)
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.supervisor_agent import SupervisorAgent
from utils.durable_memory import WorkflowStore

# ── Config from env (overridable by CLI) ─────────────────────────────────────

TICKER_MODE         = os.getenv("TICKER_MODE", "interval")
TICKER_INTERVAL_MIN = int(os.getenv("TICKER_INTERVAL_MIN", "30"))
TICKER_CRON_TIME    = os.getenv("TICKER_CRON_TIME", "06:00")
TICKER_TASK         = os.getenv("TICKER_TASK", "monitor_and_analyze")

# ── Graceful shutdown ─────────────────────────────────────────────────────────

_shutdown = False

def _handle_signal(sig, frame):
    global _shutdown
    print(f"\n[Ticker] Received signal {sig} — shutting down after current run completes...")
    _shutdown = True

signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# ── Core run logic ────────────────────────────────────────────────────────────

def run_once(task: str) -> None:
    """Execute one monitoring workflow run and persist results to SQLite."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[Ticker] ▶  Starting workflow '{task}' at {now}")

    store = WorkflowStore()

    try:
        supervisor = SupervisorAgent()
        result = supervisor.run_monitoring_workflow(task=task)

        failed  = len(result.get("failed_jobs", []))
        rca     = len(result.get("rca_results", []))
        status  = result.get("workflow_status", "completed")

        # Persist the full result payload so the UI can read it
        run_id = result.get("workflow_run_id", "unknown")
        store.save_latest_result(run_id=run_id, result=result)

        print(
            f"[Ticker] ✅ Done — status={status}, "
            f"failed_jobs={failed}, rca_results={rca}, run_id={run_id}"
        )

    except Exception as exc:
        print(f"[Ticker] ❌ Workflow error: {exc}")
        import traceback
        traceback.print_exc()


# ── Schedule helpers ──────────────────────────────────────────────────────────

def _next_cron_seconds(cron_time: str) -> float:
    """Return seconds until the next occurrence of HH:MM (UTC)."""
    now = datetime.utcnow()
    hh, mm = map(int, cron_time.split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def run_interval(task: str, interval_min: int) -> None:
    """Run the workflow every `interval_min` minutes."""
    print(f"[Ticker] Mode: interval — every {interval_min} minute(s), task='{task}'")
    print(f"[Ticker] Press Ctrl+C to stop.\n")

    while not _shutdown:
        run_once(task)
        if _shutdown:
            break
        next_run = datetime.utcnow() + timedelta(minutes=interval_min)
        print(f"[Ticker] 💤 Next run at {next_run.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        # Sleep in 1-second ticks so Ctrl+C is responsive
        for _ in range(interval_min * 60):
            if _shutdown:
                break
            time.sleep(1)

    print("[Ticker] Stopped.")


def run_cron(task: str, cron_time: str) -> None:
    """Run the workflow once a day at `cron_time` (HH:MM UTC)."""
    print(f"[Ticker] Mode: cron — daily at {cron_time} UTC, task='{task}'")
    print(f"[Ticker] Press Ctrl+C to stop.\n")

    while not _shutdown:
        wait_secs = _next_cron_seconds(cron_time)
        next_run = datetime.utcnow() + timedelta(seconds=wait_secs)
        print(f"[Ticker] 💤 Next run at {next_run.strftime('%Y-%m-%d %H:%M:%S UTC')} ({wait_secs/60:.1f} min)")
        for _ in range(int(wait_secs)):
            if _shutdown:
                break
            time.sleep(1)
        if not _shutdown:
            run_once(task)

    print("[Ticker] Stopped.")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Data Platform AI Agents — Background Ticker")
    parser.add_argument(
        "--mode",
        choices=["interval", "cron"],
        default=TICKER_MODE,
        help=f"Schedule mode (default: {TICKER_MODE})",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=TICKER_INTERVAL_MIN,
        metavar="MINUTES",
        help=f"Interval in minutes for 'interval' mode (default: {TICKER_INTERVAL_MIN})",
    )
    parser.add_argument(
        "--cron",
        default=TICKER_CRON_TIME,
        metavar="HH:MM",
        help=f"Daily run time in UTC for 'cron' mode (default: {TICKER_CRON_TIME})",
    )
    parser.add_argument(
        "--task",
        default=TICKER_TASK,
        choices=["monitor", "monitor_and_analyze", "monitor_analyze_incident"],
        help=f"Workflow task to run (default: {TICKER_TASK})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run the workflow once immediately and exit (useful for testing)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    print("=" * 60)
    print("  Data Platform AI Agents — Background Ticker")
    print("=" * 60)

    if args.once:
        print(f"[Ticker] Mode: once — running '{args.task}' immediately\n")
        run_once(args.task)
        return

    if args.mode == "cron":
        run_cron(task=args.task, cron_time=args.cron)
    else:
        run_interval(task=args.task, interval_min=args.interval)


if __name__ == "__main__":
    main()
