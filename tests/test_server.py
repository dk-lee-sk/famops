import asyncio
import importlib


def test_server_registers_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("FAMOPS_DB", str(tmp_path / "t.db"))
    srv = importlib.reload(importlib.import_module("famops.server"))
    tools = asyncio.run(srv.server.list_tools())
    names = {t.name for t in tools}
    assert {"report_illness", "plan_sick_cover", "create_task", "handoff_task",
            "respond_to_handoff", "upcoming_for_child"} <= names


def test_report_illness_tool(tmp_path, monkeypatch):
    monkeypatch.setenv("FAMOPS_DB", str(tmp_path / "t.db"))
    srv = importlib.reload(importlib.import_module("famops.server"))
    out = srv.report_illness([{"name": "fever", "last_seen": "2026-10-15T11:00:00+02:00", "temp_c": 38.5}],
                             child_age_months=20)
    assert out["status"] == "excluded"
    assert out["earliest_return"] == "2026-10-19T07:30:00+02:00"


def test_plan_sick_cover_writes_owned_tasks(tmp_path, monkeypatch):
    monkeypatch.setenv("FAMOPS_DB", str(tmp_path / "t.db"))
    srv = importlib.reload(importlib.import_module("famops.server"))
    out = srv.plan_sick_cover("2026-10-15T11:00:00+02:00", "2026-10-19T07:30:00+02:00",
                              [{"name": "Alex"}, {"name": "Sam", "cover_minutes_to_date": 120}],
                              create_tasks=True)
    assert len(out["blocks"]) == 2
    assert all(t["owner"] in {"Alex", "Sam"} for t in out["tasks_created"])
