import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db as db_module  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_db(tmp_path):
    """Every test gets its own throwaway SQLite file — no shared state, no
    dependency on ARIA's Supabase/Postgres stack."""
    db_module.reset_for_tests(str(tmp_path / "test.db"))
    yield
