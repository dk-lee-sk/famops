"""MCP server: exposes famops to any MCP-capable assistant (Claude, etc.).

The assistant handles language (reading the daycare's message, talking to both
parents); famops handles state and arithmetic (who owns what, when the child can
return, who covers which day).

Env:
  FAMOPS_DB      SQLite path (default ~/.famops/famops.db)
  FAMOPS_POLICY  daycare policy YAML (default: bundled synthetic example)
"""

from __future__ import annotations

import os
from datetime import date, datetime

from mcp.server.mcpserver import MCPServer

from famops import anticipate as ant
from famops.ledger import Ledger
from famops.sickday import Busy, Parent, Policy, Symptom, evaluate, plan_cover

INSTRUCTIONS = (
    "famops keeps a shared task ledger for a household. Every task must have exactly one owner; "
    "ownership moves only when the receiving parent accepts a handoff. Use report_illness for daycare "
    "sick calls: it applies the daycare's written exclusion policy and never assesses symptoms. If it "
    "returns status 'escalate', tell the parent to contact a clinician or emergency services and do "
    "nothing else. Times are ISO 8601."
)

server = MCPServer("famops", instructions=INSTRUCTIONS)
ledger = Ledger(os.environ.get("FAMOPS_DB", "~/.famops/famops.db"))
policy = Policy.load(os.environ.get("FAMOPS_POLICY"))


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


# ------------------------------------------------------------------ household & ledger

@server.tool()
def set_household(members: list[str]) -> list[str]:
    """Register the household's adults (e.g. ["Alex", "Sam"]). Idempotent."""
    return ledger.set_members(members)


@server.tool()
def create_task(title: str, owner: str, due: str | None = None, ref: str | None = None) -> dict:
    """Create a task with a single owner. `ref` can be a taxonomy ID (e.g. T05)."""
    return ledger.create(title, owner, due=due, ref=ref)


@server.tool()
def list_tasks(owner: str | None = None, status: str | None = None) -> list[dict]:
    """List tasks, optionally filtered by owner and status (open|handoff_pending|done)."""
    return ledger.list(owner, status)


@server.tool()
def handoff_task(task_id: int, from_owner: str, to_owner: str, note: str = "") -> dict:
    """Propose handing a task to the other parent. Ownership moves only when they accept."""
    return ledger.handoff(task_id, from_owner, to_owner, note)


@server.tool()
def respond_to_handoff(task_id: int, by: str, accept: bool, note: str = "") -> dict:
    """Accept or decline a pending handoff. Only the proposed new owner can respond."""
    return ledger.respond(task_id, by, accept, note)


@server.tool()
def complete_task(task_id: int, by: str) -> dict:
    """Mark a task done. Only its owner can complete it."""
    return ledger.complete(task_id, by)


@server.tool()
def load_balance(days: int = 30) -> dict:
    """Open tasks and recent completions per parent."""
    return ledger.balance(days)


# ------------------------------------------------------------------ sick day

@server.tool()
def report_illness(symptoms: list[dict], child_age_months: float | None = None,
                   red_flags: list[str] | None = None) -> dict:
    """Apply the daycare exclusion policy.

    symptoms: [{"name": "fever", "last_seen": "2026-10-15T11:00:00+02:00", "temp_c": 38.5}, ...]
    Names must match policy rules (fever, vomiting, diarrhoea, conjunctivitis, rash_with_fever).
    red_flags: any red-flag signs the parent reported; if present the result is 'escalate'.
    """
    parsed = [Symptom(s["name"], _dt(s["last_seen"]), s.get("temp_c"),
                      _dt(s["treatment_start"]) if s.get("treatment_start") else None) for s in symptoms]
    res = evaluate(policy, parsed, child_age_months=child_age_months, red_flags_reported=red_flags)
    out = res.to_dict()
    out["policy"] = policy.name
    out["policy_red_flags"] = policy.red_flags
    return out


@server.tool()
def plan_sick_cover(now: str, return_at: str, parents: list[dict], create_tasks: bool = False) -> dict:
    """Assign one parent per day-block until the child can return.

    parents: [{"name": "Alex", "cover_minutes_to_date": 600,
               "busy": [{"start": "...", "end": "...", "title": "Board meeting", "hard": true}]}]
    If create_tasks is true, each block is written to the ledger as an owned task.
    """
    ps = [Parent(p["name"], [Busy(_dt(b["start"]), _dt(b["end"]), b.get("title", ""), b.get("hard", False))
                             for b in p.get("busy", [])], p.get("cover_minutes_to_date", 0)) for p in parents]
    plan = plan_cover(policy, ps, _dt(now), _dt(return_at))
    created = []
    if create_tasks:
        ledger.set_members([p.name for p in ps])
        for b in plan:
            created.append(ledger.create(
                f"Sick-day cover {b.start:%a %d %b %H:%M}–{b.end:%H:%M}", b.owner,
                due=b.start.isoformat(), ref="sick-day"))
    return {"blocks": [b.to_dict() for b in plan], "tasks_created": created,
            "backup_needed": any(b.hard_conflict for b in plan)}


# ------------------------------------------------------------------ anticipate

@server.tool()
def upcoming_for_child(dob: str, today: str | None = None, horizon_days: int = 60,
                       jurisdiction: str | None = None) -> dict:
    """Age-anchored tasks due now or soon, plus the computed school-entry year."""
    d = date.fromisoformat(dob)
    t = date.fromisoformat(today) if today else date.today()
    return {"items": [u.to_dict() for u in ant.upcoming(d, t, horizon_days, jurisdiction=jurisdiction)],
            "school_entry": ant.school_entry(d)}


@server.tool()
def taxonomy_tasks(stage: str | None = None, priority_only: bool = False) -> list[dict]:
    """Parent-chore taxonomy (newborn|infant|toddler|preschooler)."""
    return ant.taxonomy(stage, priority_only)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
