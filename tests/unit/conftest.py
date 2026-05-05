"""Configuration for root-level unit tests.

Adds ``scripts/`` to ``sys.path`` so that ``common`` and ``setup`` modules
can be imported directly in tests without relative path gymnastics.

This runs before any test module import via the pytest conftest mechanism.
"""

import sys
from pathlib import Path

# Make scripts/ importable as top-level modules (common, setup, …)
_SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
