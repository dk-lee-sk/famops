"""Command-line entry point. `famops demo` runs the Thursday sick-call scenario."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from famops import anticipate as ant
from famops.ledger import Ledger
from famops.sickday import Busy, Helper, Parent, Policy, Symptom, evaluate, plan_cover

TZ = ZoneInfo("Europe/Zurich")


def demo() -> None:
    policy = Policy.load()
    now = datetime(2026, 10, 15, 11, 0)  # Thursday; no timezone given -> read as daycare local time
    print(f"Policy: {policy.name}")
    print("Daycare calls Thu 11:00: fever 38.5°C, child is 20 months old, no red flags.")
    print("Paracetamol was given at 12:00.\n")

    res = evaluate(policy, [Symptom("fever", now, 38.5, last_antipyretic=datetime(2026, 10, 15, 12, 0))],
                   child_age_months=20, red_flags_reported=[])
    print("Exclusion:", json.dumps(res.to_dict(), indent=2, ensure_ascii=False), "\n")

    alex = Parent("Alex", [
        Busy(datetime(2026, 10, 15, 11, 30, tzinfo=TZ), datetime(2026, 10, 15, 13, 0, tzinfo=TZ), "Client call"),
        Busy(datetime(2026, 10, 16, 9, 0, tzinfo=TZ), datetime(2026, 10, 16, 17, 0, tzinfo=TZ), "Team offsite", hard=True),
    ], cover_minutes_to_date=900)
    sam = Parent("Sam", [
        Busy(datetime(2026, 10, 15, 14, 0, tzinfo=TZ), datetime(2026, 10, 15, 15, 0, tzinfo=TZ), "1:1"),
        Busy(datetime(2026, 10, 16, 8, 0, tzinfo=TZ), datetime(2026, 10, 16, 12, 0, tzinfo=TZ), "Exam", hard=True),
    ], cover_minutes_to_date=300)
    grandma = Helper("Grandma", [(datetime(2026, 10, 16, 7, 0, tzinfo=TZ), datetime(2026, 10, 16, 13, 0, tzinfo=TZ))])

    plan = plan_cover(policy, [alex, sam], now, res.earliest_return, [grandma])
    print("Proposed cover (half-days):")
    for b in plan:
        tag = {"parent": "", "helper": "  (helper)", "backup": "  ⚠ backup care needed"}[b.kind]
        print(f"  {b.start:%a %d %b %H:%M}–{b.end:%H:%M}  →  {b.owner}{tag}   · {b.reason}")

    led = Ledger()
    led.set_members(["Alex", "Sam"])
    me = "Alex"  # the parent talking to their assistant
    for b in plan:
        mins = int((b.end - b.start).total_seconds() // 60)
        if b.kind == "parent":
            led.propose(f"Sick-day cover {b.start:%a %H:%M}–{b.end:%H:%M}", me, b.owner, effort_min=mins, note=b.reason)
        elif b.kind == "helper":
            led.create(f"Ask {b.owner} to cover {b.start:%a %H:%M}–{b.end:%H:%M}", me)
        else:
            led.create(f"Arrange backup care {b.start:%a %H:%M}", me, effort_min=60)
    print("\nLedger after Alex proposes the plan (Sam has not answered yet):")
    for row in led.list():
        wait = f" (waiting for {row['pending_owner']})" if row["pending_owner"] else ""
        print(f"  #{row['id']} [{row['status']}] {row['title']} → {row['owner']}{wait}")
    pending = [r for r in led.list() if r["status"] == "handoff_pending"]
    if pending:
        led.respond(pending[0]["id"], "Sam", accept=True)
        print(f"\nSam accepts #{pending[0]['id']}.")
    print("Balance (tasks and minutes):", led.balance())


def main() -> None:
    p = argparse.ArgumentParser(prog="famops")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="run the Thursday sick-call scenario")
    up = sub.add_parser("upcoming", help="age-anchored tasks for a child")
    up.add_argument("--dob", required=True)
    up.add_argument("--today")
    up.add_argument("--horizon", type=int, default=60)
    up.add_argument("--weeks-premature", type=int, default=0)
    tx = sub.add_parser("taxonomy", help="list taxonomy tasks")
    tx.add_argument("--stage", choices=["newborn", "infant", "toddler", "preschooler"])
    tx.add_argument("--priority", action="store_true")
    a = p.parse_args()

    if a.cmd == "demo":
        demo()
    elif a.cmd == "upcoming":
        dob = date.fromisoformat(a.dob)
        today = date.fromisoformat(a.today) if a.today else date.today()
        for u in ant.upcoming(dob, today, a.horizon, weeks_premature=a.weeks_premature):
            print(f"[{u.status:15}] {u.window_start} → {u.window_end}  {u.title}")
        print("School entry:", json.dumps(ant.school_entry(dob), indent=2))
    elif a.cmd == "taxonomy":
        for t in ant.taxonomy(a.stage, a.priority):
            print(f"{t['id']}  {t['scenario']}: {t['task']}")


if __name__ == "__main__":
    main()
