"""
Auto-bootstrap for local development.

Whenever Python starts inside this repository, this module ensures the
`src/` directory is on `sys.path`, so `import fomc` works without
manually setting PYTHONPATH or installing the package.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

