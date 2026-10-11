import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.delenv("HRC_SESSION_ID", raising=False)
    monkeypatch.delenv("HRC_DB", raising=False)
    return tmp_path / "hrc.db"


@pytest.fixture
def read(db_path):
    """Run a query on a fresh read connection; returns all rows as tuples."""
    def run(sql, params=()):
        con = sqlite3.connect(db_path)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()
    return run
