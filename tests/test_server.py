import asyncio
import importlib

import pytest

from famops.ledger import LedgerError


@pytest.fixture
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("FAMOPS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("FAMOPS_USER", "Alex")
    s = importlib.reload(importlib.import_module("famops.server"))
    s.set_household(["Alex", "Sam"])
    return s


def test_server_registers_tools(srv):
    names = {t.name for t in asyncio.run(srv.server.list_tools())}
    assert {"report_illness", "plan_sick_cover", "create_task", "handoff_task", "respond_to_handoff",
            "upcoming_for_child", "add_upcoming_to_ledger", "whoami"} <= names


def test_acts_only_as_configured_parent(srv, monkeypatch):
    t = srv.create_task("Book check-up", owner="Sam")
    assert t["status"] == "handoff_pending"
    with pytest.raises(LedgerError):          # Alex's connection cannot accept for Sam
        srv.respond_to_handoff(t["id"], accept=True)
    monkeypatch.setenv("FAMOPS_USER", "Sam")
    assert srv.respond_to_handoff(t["id"], accept=True)["owner"] == "Sam"


def test_missing_user_is_refused(srv, monkeypatch):
    monkeypatch.delenv("FAMOPS_USER")
    with pytest.raises(LedgerError):
        srv.create_task("x")


def test_report_illness_requires_age_and_red_flag_answer(srv):
    s = [{"name": "fever", "last_seen": "2026-10-15T11:00", "temp_c": 38.5}]
    assert srv.report_illness(s)["status"] == "needs_info"
    out = srv.report_illness(s, child_age_months=20, red_flags=[])
    assert out["status"] == "excluded" and out["earliest_return"] == "2026-10-19T07:30:00+02:00"


def test_plan_sick_cover_sends_proposals(srv):
    out = srv.plan_sick_cover("2026-10-15T11:00", "2026-10-19T07:30:00+02:00",
                              [{"name": "Alex", "cover_minutes_to_date": 600}, {"name": "Sam"}],
                              propose_tasks=True)
    assert len(out["blocks"]) == 4
    for t in out["tasks"]:
        assert t["owner"] == "Alex"                     # nothing lands on Sam without a yes
        assert t["status"] in {"open", "handoff_pending"}
    assert any(t["pending_owner"] == "Sam" for t in out["tasks"])


def test_upcoming_to_ledger_is_idempotent(srv):
    first = srv.add_upcoming_to_ledger("2026-05-15", today="2026-10-16")
    again = srv.add_upcoming_to_ledger("2026-05-15", today="2026-10-16")
    assert len(first["created"]) >= 2 and again["created"] == []
