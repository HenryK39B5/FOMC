"""Centralized path definitions."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"
MAIN_DB_PATH = DATA_DIR / "fomc_data.db"
MACRO_EVENTS_DB_PATH = DATA_DIR / "macro_events.db"
REPORTS_DB_PATH = DATA_DIR / "reports.db"
MEETINGS_DIR = DATA_DIR / "meetings"
MEETING_RUNS_DIR = DATA_DIR / "meeting_runs"
PROMPT_RUNS_DIR = DATA_DIR / "prompt_runs"
