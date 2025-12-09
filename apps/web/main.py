"""
Compatibility shim so `uvicorn apps.web.main:app` continues to work.

Preferred entrypoint: `uvicorn fomc.apps.web.main:app --reload --port 9000`
(the src/ directory is injected below for convenience).
"""

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fomc.apps.web.main import app  # noqa: E402,F401
