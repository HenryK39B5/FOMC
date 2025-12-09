"""
Macro events package bootstrap.

Exposes common defaults for database location so other modules can share it.
"""

from pathlib import Path

# Default database path under a local data directory.
DATA_DIR = Path("data")
DEFAULT_DB_PATH = DATA_DIR / "macro_events.db"

__all__ = ["DATA_DIR", "DEFAULT_DB_PATH"]
