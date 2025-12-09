"""
Compatibility bootstrap so legacy `apps.*` imports keep working.

It also ensures the repository `src/` directory is on sys.path, so
`fomc.*` imports resolve even when running commands like
`uvicorn apps.web.main:app`.
"""

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

