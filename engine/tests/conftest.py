"""Test configuration — make the `confession` package importable without installation.

Tests here cover pure logic only: no network, no keys, no external processes.
"""

import sys
from pathlib import Path

# engine/ (parent of this tests/ dir) holds the `confession` package.
ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
