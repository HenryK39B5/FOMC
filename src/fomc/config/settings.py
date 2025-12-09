"""Environment loading and simple settings."""

from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv

from .paths import REPO_ROOT


def load_env() -> Path:
    """Load .env from repo root; return path."""
    env_path = REPO_ROOT / ".env"
    load_dotenv(env_path)
    return env_path

