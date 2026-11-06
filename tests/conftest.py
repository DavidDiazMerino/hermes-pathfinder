import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pathfinder.ledger import Ledger  # noqa: E402
from pathfinder.tools import Runtime  # noqa: E402

FIXTURES = ROOT / "domains" / "sap" / "fixtures"


@pytest.fixture
def runtime(tmp_path):
    ledger = Ledger(sqlite3.connect(":memory:"), tmp_path)
    return Runtime(ledger=lambda: ledger, cwd=lambda: str(tmp_path))
