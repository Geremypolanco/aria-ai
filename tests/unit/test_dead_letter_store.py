"""
Persistent dead-letter sink (cuspide wave 3).

- The Supabase sink never raises and never blocks: without credentials or
  on write failure the in-memory queue stays the source of truth.
- get_health_summary() exposes the persistent count.
"""

from __future__ import annotations

import pytest

from apps.core.llm.contracts.dead_letter import DeadLetterEntry, get_dead_letter_queue
from apps.core.llm.contracts.dead_letter_store import DeadLetterStore

# ── fakes ──────────────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


class _FakeQuery:
    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._limit = None
        self._select_count = None

    def insert(self, row):
        self._db.rows.append(row)
        return self

    def select(self, *cols, **kwargs):
        self._select_count = kwargs.get("count")
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        if self._select_count == "exact":
            return _FakeResult(data=[{"id": r["id"]} for r in self._db.rows[:1]],
                               count=len(self._db.rows))
        rows = sorted(self._db.rows, key=lambda r: r.get("at", ""), reverse=True)
        if self._limit is not None:
            rows = rows[: self._limit]
        return _FakeResult(data=rows)


class _FakeDB:
    def __init__(self, fail_on=None):
        self.rows: list[dict] = []
        self.fail_on = fail_on or set()
        self.tables_used: list[str] = []

    def table(self, name):
        if name in self.fail_on:
            raise ConnectionError("supabase down")
        self.tables_used.append(name)
        return _FakeQuery(self, name)


class _FailingDB:
    def table(self, name):
        raise ConnectionError("supabase down")


@pytest.fixture(autouse=True)
def _clean_dlq():
    get_dead_letter_queue().clear()
    yield
    get_dead_letter_queue().clear()


# ── store behavior ─────────────────────────────────────────────────────────


def test_persist_writes_expected_row():
    db = _FakeDB()
    store = DeadLetterStore(db=db)
    entry = DeadLetterEntry(schema="OfferData", errors=["price_cents: bad"], attempts=3, agent="loop")
    assert store.persist(entry) is True
    assert db.tables_used == ["dead_letters"]
    row = db.rows[0]
    assert row["id"] == entry.id
    assert row["schema"] == "OfferData"
    assert row["errors"] == ["price_cents: bad"]
    assert row["attempts"] == 3
    assert row["agent"] == "loop"


def test_persist_never_raises_when_db_down():
    store = DeadLetterStore(db=_FailingDB())
    assert store.persist(DeadLetterEntry(schema="X")) is False  # no raise


def test_unavailable_without_credentials(monkeypatch):
    # No SUPABASE_URL/KEY anywhere -> store degrades, never raises.
    import apps.core.llm.contracts.dead_letter_store as mod

    monkeypatch.setattr(mod, "AriaDatabase", None, raising=False)
    store = DeadLetterStore(db=None)
    monkeypatch.setattr(
        "apps.core.config.settings.SUPABASE_URL", "", raising=False
    )
    monkeypatch.setattr(
        "apps.core.config.settings.SUPABASE_KEY", "", raising=False
    )
    assert store.available() is False
    assert store.persist(DeadLetterEntry(schema="X")) is False
    assert store.count() is None
    assert store.recent() == []


def test_count_and_recent():
    db = _FakeDB()
    store = DeadLetterStore(db=db)
    for i in range(3):
        store.persist(DeadLetterEntry(schema=f"S{i}", at=f"2026-10-08T0{i}:00:00+00:00"))
    assert store.count() == 3
    recent = store.recent(limit=2)
    assert len(recent) == 2
    assert recent[0]["schema"] == "S2"  # newest first


def test_count_none_when_db_down():
    store = DeadLetterStore(db=_FailingDB())
    assert store.count() is None
    assert store.recent() == []


# ── queue -> store wiring ──────────────────────────────────────────────────


def test_queue_push_persists_best_effort(monkeypatch):
    import apps.core.llm.contracts.dead_letter_store as store_mod

    db = _FakeDB()
    monkeypatch.setattr(store_mod, "get_dead_letter_store", lambda: DeadLetterStore(db=db))
    q = get_dead_letter_queue()
    q.push(DeadLetterEntry(schema="MindDecision", agent="aria_mind"))
    assert len(q) == 1          # in-memory still the source of truth
    assert len(db.rows) == 1    # ...and the durable sink got it too
    assert db.rows[0]["schema"] == "MindDecision"


def test_queue_push_survives_store_failure(monkeypatch):
    import apps.core.llm.contracts.dead_letter_store as store_mod

    monkeypatch.setattr(
        store_mod, "get_dead_letter_store", lambda: DeadLetterStore(db=_FailingDB())
    )
    q = get_dead_letter_queue()
    q.push(DeadLetterEntry(schema="X"))  # must not raise
    assert len(q) == 1


# ── health summary ─────────────────────────────────────────────────────────


def test_health_summary_exposes_persistent_dead_letters(monkeypatch):
    # get_health_summary() resolves the store lazily via the module singleton.
    import apps.core.llm.contracts.dead_letter_store as store_mod
    from apps.core.tools.ai_client import AIProvider, AriaAIClient

    db = _FakeDB()
    store = DeadLetterStore(db=db)
    store.persist(DeadLetterEntry(schema="S1"))
    monkeypatch.setattr(store_mod, "_STORE", store)

    client = AriaAIClient.__new__(AriaAIClient)
    client._health = {p: _FakeHealth() for p in AIProvider}
    client._total_tokens = 0
    client._total_fallbacks = 0
    summary = client.get_health_summary()
    assert summary["dead_letters"]["count"] == 0  # in-memory (clean fixture)
    persisted = summary["dead_letters_persistent"]
    assert persisted["available"] is True
    assert persisted["count"] == 1


class _FakeHealth:
    class _State:
        value = "healthy"

    state = _State()
    success_rate = 100.0
    total_calls = 0
    consecutive_failures = 0
