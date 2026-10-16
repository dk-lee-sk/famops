"""Command-line entry point. `famops demo` runs the Thursday sick-call scenario."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from famops import anticipate as ant
from famops.ledger import Ledger
from famops.sickday import Busy, Parent, Policy, Symptom, evaluate, plan_cover

TZ = ZoneInfo("Europe/Zurich")


def demo() -> None:
    policy = Policy.load()
    now = datetime(2026, 10, 15, 11, 0, tzinfo=TZ)  # Thursday
    print(f"Policy: {policy.name}")
    print("Daycare calls Thu 11:00: fever 38.5°C, child is 20 months old.\n")

    res = evaluate(policy, [Symptom("fever", now, 38.5)], child_age_months=20)
    print("Exclusion:", json.dumps(res.to_dict(), indent=2, ensure_ascii=False), "\n")

    alex = Parent("Alex", [
        Busy(datetime(2026, 10, 15, 11, 30, tzinfo=TZ), datetime(2026, 10, 15, 13, 0, tzinfo=TZ), "Client call"),
        Busy(datetime(2026, 10, 16, 9, 0, tzinfo=TZ), datetime(2026, 10, 16, 17, 0, tzinfo=TZ), "Offsite", hard=True),
    ], cover_minutes_to_date=900)
    sam = Parent("Sam", [
        Busy(datetime(2026, 10, 15, 14, 0, tzinfo=TZ), datetime(2026, 10, 15, 15, 0, tzinfo=TZ), "1:1"),
    ], cover_minutes_to_date=300)

    plan = plan_cover(policy, [alex, sam], now, res.earliest_return)
    print("Cover plan:")
    for b in plan:
        flag = "  ⚠ backup care needed" if b.hard_conflict else ""
        print(f"  {b.start:%a %d %b %H:%M}–{b.end:%H:%M}  →  {b.owner}"
              f"  (conflict {b.conflict_minutes} min: {', '.join(b.conflicts) or 'none'}){flag}")

    led = Ledger()
    led.set_members(["Alex", "Sam"])
    for b in plan:
        led.create(f"Sick-day cover {b.start:%a %H:%M}", b.owner, due=b.start.isoformat(), ref="sick-day")
    t = led.create("Get doctor's note if daycare asks", "Sam", ref="I14")
    led.handoff(t["id"], "Sam", "Alex", "I'm on cover all day")
    led.respond(t["id"], "Alex", accept=True)
    print("\nLedger:")
    for row in led.list():
        print(f"  #{row['id']} [{row['status']}] {row['title']} → {row['owner']}")
    print("\nBalance:", led.balance())


def main() -> None:
    p = argparse.ArgumentParser(prog="famops")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="run the Thursday sick-call scenario")
    up = sub.add_parser("upcoming", help="age-anchored tasks for a child")
    up.add_argument("--dob", required=True)
    up.add_argument("--today")
    up.add_argument("--horizon", type=int, default=60)
    tx = sub.add_parser("taxonomy", help="list taxonomy tasks")
    tx.add_argument("--stage", choices=["newborn", "infant", "toddler", "preschooler"])
    tx.add_argument("--priority", action="store_true")
    a = p.parse_args()

    if a.cmd == "demo":
        demo()
    elif a.cmd == "upcoming":
        dob = date.fromisoformat(a.dob)
        today = date.fromisoformat(a.today) if a.today else date.today()
        for u in ant.upcoming(dob, today, a.horizon):
            print(f"[{u.status:15}] {u.window_start} → {u.window_end}  {u.title}")
        print("School entry:", json.dumps(ant.school_entry(dob), indent=2))
    elif a.cmd == "taxonomy":
        for t in ant.taxonomy(a.stage, a.priority):
            print(f"{t['id']}  {t['scenario']}: {t['task']}")


if __name__ == "__main__":
    main()
