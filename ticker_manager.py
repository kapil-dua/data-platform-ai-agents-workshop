"""
TickerManager — launch and stop the ticker.py process from within Streamlit.

The ticker is spawned as a fully detached subprocess so it survives UI
restarts and browser closes. The PID is written to a file so the UI can
check status and stop it at any time.

Cross-platform:
  Windows  — uses DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP flags
  Linux/macOS/WSL — uses nohup + redirected stdout/stderr
"""

from __future__ import annotations

import os
import platform
import signal
import subprocess
import sys
from pathlib import Path


# PID file lives next to the SQLite store
_PID_FILE = Path(os.getcwd()) / ".sqlite" / "ticker.pid"
_LOG_FILE = Path(os.getcwd()) / ".sqlite" / "ticker.log"


def _python_executable() -> str:
    """Return the Python executable for the current virtual environment."""
    return sys.executable


def _ticker_script() -> str:
    """Absolute path to ticker.py."""
    return str(Path(__file__).resolve().parent / "ticker.py")


def start(mode: str, interval_min: int, cron_time: str, task: str) -> str:
    """
    Launch ticker.py as a detached background process.

    Returns a human-readable status message.
    """
    if is_running():
        return "⚠️ Ticker is already running. Stop it first to apply new settings."

    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        _python_executable(),
        _ticker_script(),
        "--mode", mode,
        "--interval", str(interval_min),
        "--cron", cron_time,
        "--task", task,
    ]

    log_fh = open(_LOG_FILE, "a", encoding="utf-8")

    if platform.system() == "Windows":
        # DETACHED_PROCESS (0x00000008) + CREATE_NEW_PROCESS_GROUP (0x00000200)
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=log_fh,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    else:
        # nohup equivalent via preexec_fn=os.setsid
        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=log_fh,
            preexec_fn=os.setsid,
            close_fds=True,
        )

    _PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    return f"✅ Ticker started (PID {proc.pid}) — logs: {_LOG_FILE}"


def stop() -> str:
    """Terminate the ticker process. Returns a status message."""
    if not _PID_FILE.exists():
        return "ℹ️ Ticker is not running (no PID file found)."

    pid = int(_PID_FILE.read_text().strip())

    try:
        if platform.system() == "Windows":
            subprocess.call(["taskkill", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass  # process already gone

    _PID_FILE.unlink(missing_ok=True)
    return f"🛑 Ticker stopped (PID {pid})."


def is_running() -> bool:
    """Return True if the ticker process is alive."""
    if not _PID_FILE.exists():
        return False

    pid = int(_PID_FILE.read_text().strip())

    try:
        if platform.system() == "Windows":
            result = subprocess.call(
                ["tasklist", "/FI", f"PID eq {pid}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return result == 0
        else:
            os.kill(pid, 0)  # signal 0 = existence check
            return True
    except (ProcessLookupError, PermissionError, OSError):
        _PID_FILE.unlink(missing_ok=True)
        return False


def get_pid() -> int | None:
    """Return the ticker PID, or None if not running."""
    if not _PID_FILE.exists():
        return None
    return int(_PID_FILE.read_text().strip())


def get_log(last_n_lines: int = 30) -> str:
    """Return the last N lines of the ticker log."""
    if not _LOG_FILE.exists():
        return "No log file yet."
    lines = _LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-last_n_lines:]) if lines else "Log is empty."
