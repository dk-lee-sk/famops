from datetime import datetime, timedelta, timezone

import pytest

from famops.ledger import Ledger, LedgerError


@pytest.fixture
def led():
    l = Ledger()
    l.set_members(["Alex", "Sam"])
    return l


def test_owner_required(led):
    with pytest.raises(LedgerError):
        led.create("Pack spare clothes", "")
    with pytest.raises(LedgerError):
        led.create("Pack spare clothes", "Grandma")


def test_handoff_requires_acceptance(led):
    t = led.create("Book 18-month check-up", "Alex")
    t = led.handoff(t["id"], "Alex", "Sam", "travelling next week")
    assert t["status"] == "handoff_pending" and t["owner"] == "Alex"
    t = led.respond(t["id"], "Sam", accept=True)
    assert t["owner"] == "Sam" and t["status"] == "open"


def test_propose_to_other_parent_waits_for_yes(led):
    t = led.propose("Sick-day cover Fri am", "Alex", "Sam", effort_min=330)
    assert t["owner"] == "Alex" and t["pending_owner"] == "Sam"
    t = led.propose("Call the crèche", "Alex", "Alex")
    assert t["status"] == "open" and t["owner"] == "Alex"


def test_declined_handoff_stays_with_owner(led):
    t = led.create("Reply to daycare re closure", "Alex")
    led.handoff(t["id"], "Alex", "Sam")
    t = led.respond(t["id"], "Sam", accept=False, note="all-day workshop")
    assert t["owner"] == "Alex" and t["status"] == "open"


def test_only_pending_owner_can_respond(led):
    t = led.create("x", "Alex")
    led.handoff(t["id"], "Alex", "Sam")
    with pytest.raises(LedgerError):
        led.respond(t["id"], "Alex", accept=True)


def test_only_owner_can_hand_off_or_complete(led):
    t = led.create("x", "Alex")
    with pytest.raises(LedgerError):
        led.handoff(t["id"], "Sam", "Alex")
    with pytest.raises(LedgerError):
        led.complete(t["id"], "Sam")
    assert led.complete(t["id"], "Alex")["status"] == "done"


def test_unanswered_handoff_expires_back_to_sender(led):
    t = led.create("x", "Alex")
    led.handoff(t["id"], "Alex", "Sam")
    assert led.expire_stale(24) == []
    later = datetime.now(timezone.utc) + timedelta(hours=25)
    back = led.expire_stale(24, now=later)
    assert back[0]["owner"] == "Alex" and back[0]["status"] == "open"
    assert led.history(t["id"])[-1]["kind"] == "handoff_expired"


def test_balance_counts_effort_not_just_tasks(led):
    led.create("Two days of sick cover", "Sam", effort_min=1200)
    led.create("Buy wipes", "Alex", effort_min=10)
    led.create("Book dentist", "Alex", effort_min=10)
    bal = led.balance()
    assert bal["Alex"]["open"] == 2 and bal["Sam"]["open"] == 1
    assert bal["Sam"]["open_effort_min"] == 1200 and bal["Alex"]["open_effort_min"] == 20


def test_history(led):
    t = led.create("x", "Alex")
    led.handoff(t["id"], "Alex", "Sam")
    led.respond(t["id"], "Sam", accept=True)
    led.complete(t["id"], "Sam")
    assert [e["kind"] for e in led.history(t["id"])] == ["created", "handoff_requested", "handoff_accepted", "completed"]


def test_v01_database_is_migrated(tmp_path):
    import sqlite3
    p = tmp_path / "old.db"
    db = sqlite3.connect(p)
    db.executescript("""CREATE TABLE members (name TEXT PRIMARY KEY);
      CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, owner TEXT NOT NULL,
        status TEXT NOT NULL, pending_owner TEXT, due TEXT, ref TEXT, created_at TEXT NOT NULL, done_at TEXT);
      CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL, ts TEXT NOT NULL,
        actor TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT);""")
    db.close()
    led = Ledger(p)
    led.set_members(["Alex"])
    assert led.create("x", "Alex", effort_min=30)["effort_min"] == 30
