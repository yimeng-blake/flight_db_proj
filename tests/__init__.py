"""Tests package"""

# Ensure direct ``python tests/test_*.py`` invocations can import the project
# modules even when the repository root is not automatically added to
# ``sys.path`` (which normally happens when running ``pytest`` from the root).
#
# This mirrors the approach used by standalone scripts such as
# ``data/populate_flights.py`` and prevents ``ModuleNotFoundError`` exceptions
# when contributors execute tests individually via ``python`` instead of
# ``pytest``.
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
