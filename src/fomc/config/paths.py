"""Centralized path definitions."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"
MAIN_DB_PATH = DATA_DIR / "fomc_data.db"
MACRO_EVENTS_DB_PATH = DATA_DIR / "macro_events.db"
