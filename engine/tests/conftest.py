"""Test configuration — make the `confession` package importable without installation.

Tests here cover pure logic only: no network, no keys, no external processes.
"""

import os
import sys
import tempfile
from pathlib import Path

TEST_STATE = Path(tempfile.mkdtemp(prefix="confession-tests-"))
os.environ["CONFESSION_STATE_DIR"] = str(TEST_STATE)
os.environ["CONFESSION_DATABASE_PATH"] = str(TEST_STATE / "state.sqlite3")
os.environ["CONFESSION_AUTH_REQUIRED"] = "false"

# engine/ (parent of this tests/ dir) holds the `confession` package.
ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))
