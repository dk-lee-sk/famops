"""MCP server: exposes famops to any MCP-capable assistant (Claude, etc.).

The assistant handles language (reading the daycare's message, talking to both
parents); famops handles state and arithmetic (who owns what, when the child can
return, who covers which half-day).

Env:
  FAMOPS_USER    REQUIRED: the parent this assistant acts for, e.g. "Alex". Each parent
                 runs their own connection with their own name. famops never lets a
                 request claim to be the other parent.
  FAMOPS_DB      SQLite path (default ~/.famops/famops.db). For now both parents'
                 connections must point at the same file (see README: Sharing).
  FAMOPS_POLICY  daycare policy YAML (default: bundled synthetic example)
"""

from __future__ import annotations

import os
from datetime import date, datetime

from mcp.server.mcpserver import MCPServer

from famops import anticipate as ant
from famops.ledger import Ledger, LedgerError
from famops.sickday import Busy, Helper, Parent, Policy, Symptom, evaluate, plan_cover

INSTRUCTIONS = (
    "famops keeps a shared task ledger for a household and acts for ONE parent (FAMOPS_USER). "
    "Every task has exactly one owner; giving a task to the other parent is a proposal they must accept. "
    "For a daycare sick call: first ask the parent about the red flags listed by report_illness and the "
    "child's age, then call report_illness. If it returns 'escalate', tell the parent to contact a "
    "clinician or emergency services and do nothing else. If 'needs_info', ask for what it lists. "
    "Times are ISO 8601; times without a timezone are read as the daycare's local time."
)

server = MCPServer("famops", instructions=INSTRUCTIONS)
ledger = Ledger(os.environ.get("FAMOPS_DB", "~/.famops/famops.db"))
policy = Policy.load(os.environ.get("FAMOPS_POLICY"))


def _me() -> str:
    me = os.environ.get("FAMOPS_USER", "").strip()
    if not me:
        raise LedgerError("FAMOPS_USER is not set. Add it to this parent's MCP config, e.g. \"FAMOPS_USER\": \"Alex\".")
    ledger.require_member(me)
    return me


def _dt(s: str) -> datetime:
    return policy.local(datetime.fromisoformat(s))


# ------------------------------------------------------------------ household & ledger

@server.tool()
def set_household(members: list[str]) -> list[str]:
    """Register the household's adults (e.g. ["Alex", "Sam"]). Idempotent."""
    return ledger.set_members(members)


@server.tool()
def whoami() -> str:
    """The parent this connection acts for."""
    return _me()


@server.tool()
def create_task(title: str, owner: str | None = None, due: str | None = None, ref: str | None = None,
                effort_min: int = 15) -> dict:
    """Create a task. Owner defaults to you. Naming the other parent sends it to them as a
    proposal they must accept. effort_min is a rough time estimate used for the balance view."""
    me = _me()
    return ledger.propose(title, me, owner or me, due=due, ref=ref, effort_min=effort_min)


@server.tool()
def list_tasks(owner: str | None = None, status: str | None = None) -> list[dict]:
    """List tasks (open|handoff_pending|done). owner also matches tasks waiting for that person."""
    ledger.expire_stale(float(os.environ.get("FAMOPS_HANDOFF_HOURS", 24)))
    return ledger.list(owner, status)


@server.tool()
def handoff_task(task_id: int, to_owner: str, note: str = "") -> dict:
    """Offer one of your tasks to the other parent. It moves only when they accept."""
    return ledger.handoff(task_id, _me(), to_owner, note)


@server.tool()
def respond_to_handoff(task_id: int, accept: bool, note: str = "") -> dict:
    """Accept or decline a task offered to you."""
    return ledger.respond(task_id, _me(), accept, note)


@server.tool()
def complete_task(task_id: int) -> dict:
    """Mark one of your tasks done."""
    return ledger.complete(task_id, _me())


@server.tool()
def load_balance(days: int = 30) -> dict:
    """Open and recently completed work per parent, in tasks and minutes of effort."""
    return ledger.balance(days)


@server.tool()
def expire_stale_handoffs(hours: float = 24) -> list[dict]:
    """Return unanswered handoffs older than `hours` to their sender."""
    return ledger.expire_stale(hours)


# ------------------------------------------------------------------ sick day

@server.tool()
def report_illness(symptoms: list[dict], child_age_months: float | None = None,
                   red_flags: list[str] | None = None) -> dict:
    """Apply the daycare exclusion policy.

    symptoms: [{"name": "fever", "last_seen": "2026-10-15T11:00", "temp_c": 38.5,
                "last_antipyretic": "2026-10-15T12:00"}]
    Names: fever, vomiting, diarrhoea, conjunctivitis (+ treatment_start), rash_with_fever.
    child_age_months and red_flags are required before a date is given. red_flags = the warning
    signs the parent reported; [] means you asked and there were none.
    """
    parsed = [Symptom(s["name"], _dt(s["last_seen"]), s.get("temp_c"),
                      _dt(s["treatment_start"]) if s.get("treatment_start") else None,
                      _dt(s["last_antipyretic"]) if s.get("last_antipyretic") else None) for s in symptoms]
    res = evaluate(policy, parsed, child_age_months=child_age_months, red_flags_reported=red_flags)
    out = res.to_dict()
    out["policy"] = policy.name
    out["red_flags_to_ask_about"] = policy.red_flags
    return out


@server.tool()
def plan_sick_cover(now: str, return_at: str, parents: list[dict], helpers: list[dict] | None = None,
                    propose_tasks: bool = False) -> dict:
    """Propose one carer per half-day until the child can return.

    parents: [{"name": "Alex", "cover_minutes_to_date": 600,
               "busy": [{"start": "...", "end": "...", "title": "Board meeting", "hard": true}]}]
    helpers: [{"name": "Grandma", "available": [{"start": "...", "end": "..."}]}]
    propose_tasks: write the plan to the ledger. Blocks for the other parent arrive as handoffs
    they accept or decline; helper and backup blocks become "ask/arrange" tasks for you.
    """
    ps = [Parent(p["name"], [Busy(_dt(b["start"]), _dt(b["end"]), b.get("title", ""), b.get("hard", False))
                             for b in p.get("busy", [])], p.get("cover_minutes_to_date", 0)) for p in parents]
    hs = [Helper(h["name"], [(_dt(a["start"]), _dt(a["end"])) for a in h.get("available", [])])
          for h in (helpers or [])]
    plan = plan_cover(policy, ps, _dt(now), _dt(return_at), hs)
    written = []
    if propose_tasks:
        me = _me()
        for b in plan:
            when = f"{b.start:%a %d %b %H:%M}–{b.end:%H:%M}"
            effort = int((b.end - b.start).total_seconds() // 60)
            if b.kind == "parent":
                written.append(ledger.propose(f"Sick-day cover {when}", me, b.owner, due=b.start.isoformat(),
                                              ref="sick-day", effort_min=effort, note=b.reason))
            elif b.kind == "helper":
                written.append(ledger.create(f"Ask {b.owner} to cover {when}", me, due=b.start.isoformat(),
                                             ref="sick-day", effort_min=15))
            else:
                written.append(ledger.create(f"Arrange backup care {when}", me, due=b.start.isoformat(),
                                             ref="sick-day", effort_min=60))
    return {"blocks": [b.to_dict() for b in plan], "tasks": written,
            "backup_needed": any(b.kind == "backup" for b in plan)}


# ------------------------------------------------------------------ anticipate

@server.tool()
def upcoming_for_child(dob: str, today: str | None = None, horizon_days: int = 60,
                       jurisdiction: str | None = None, weeks_premature: int = 0) -> dict:
    """Age-anchored tasks due now or soon, plus the computed school-entry year."""
    d = date.fromisoformat(dob)
    t = date.fromisoformat(today) if today else date.today()
    items = ant.upcoming(d, t, horizon_days, jurisdiction=jurisdiction, weeks_premature=weeks_premature)
    return {"items": [u.to_dict() for u in items], "school_entry": ant.school_entry(d)}


@server.tool()
def add_upcoming_to_ledger(dob: str, today: str | None = None, horizon_days: int = 60,
                           weeks_premature: int = 0) -> dict:
    """Turn due-now and upcoming milestones into tasks you own (hand them off afterwards).
    Milestones already in the ledger, open or done, are skipped, so this is safe to repeat."""
    me = _me()
    d = date.fromisoformat(dob)
    t = date.fromisoformat(today) if today else date.today()
    created, skipped = [], []
    for u in ant.upcoming(d, t, horizon_days, weeks_premature=weeks_premature):
        if u.status == "recently_closed":
            continue
        ref = f"milestone:{u.id}"
        if ledger.find_by_ref(ref):
            skipped.append(u.id)
            continue
        created.append(ledger.create(u.title, me, due=u.window_end.isoformat(), ref=ref, actor=me))
    return {"created": created, "skipped_already_in_ledger": skipped}


@server.tool()
def taxonomy_tasks(stage: str | None = None, priority_only: bool = False) -> list[dict]:
    """Parent-chore taxonomy (newborn|infant|toddler|preschooler)."""
    return ant.taxonomy(stage, priority_only)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
