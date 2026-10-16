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
    assert t["status"] == "handoff_pending"
    assert t["owner"] == "Alex"            # ownership has not moved yet
    t = led.respond(t["id"], "Sam", accept=True)
    assert t["owner"] == "Sam" and t["status"] == "open"


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


def test_history_and_balance(led):
    t = led.create("x", "Alex")
    led.handoff(t["id"], "Alex", "Sam")
    led.respond(t["id"], "Sam", accept=True)
    led.complete(t["id"], "Sam")
    kinds = [e["kind"] for e in led.history(t["id"])]
    assert kinds == ["created", "handoff_requested", "handoff_accepted", "completed"]
    bal = led.balance()
    assert bal["Sam"]["done_last_30d"] == 1 and bal["Alex"]["open"] == 0
