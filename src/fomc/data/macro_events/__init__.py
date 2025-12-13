"""
Macro events package bootstrap.

Centralizes database paths and ensures `.env` is loaded so CLI / web callers
can reuse the same configuration.
"""

from pathlib import Path

from fomc.config import DATA_DIR, MACRO_EVENTS_DB_PATH, load_env

load_env()
DATA_DIR.mkdir(parents=True, exist_ok=True)
MACRO_EVENTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
DATA_DIR = MACRO_EVENTS_DB_PATH.parent
DEFAULT_DB_PATH = MACRO_EVENTS_DB_PATH

__all__ = ["DATA_DIR", "DEFAULT_DB_PATH"]
