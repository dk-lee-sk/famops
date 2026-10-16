"""Anticipate engine: turn a child's date of birth into upcoming tasks.

Anticipating and monitoring are the household-labour phases that are split least
evenly between partners (Daminger 2019). This module does the anticipating so the
ledger can assign an owner before the task becomes urgent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from famops import load_bundled


@dataclass
class Upcoming:
    id: str
    title: str
    window_start: date
    window_end: date
    status: str                 # "due_now" | "upcoming" | "recently_closed"
    note: str | None = None
    source: list[str] | None = None
    jurisdiction: str | None = None
    taxonomy_ref: str | None = None

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["window_start"] = self.window_start.isoformat()
        d["window_end"] = self.window_end.isoformat()
        return {k: v for k, v in d.items() if v is not None}


def school_entry(dob: date, cfg: dict | None = None) -> dict:
    """Which school year a child enters, under a 'must be N by cutoff' rule."""
    cfg = cfg or load_bundled("milestones.yaml")["school_entry_default"]
    age = cfg["entry_age_years"]
    year = dob.year + age
    cutoff = date(year, cfg["cutoff_month"], cfg["cutoff_day"])
    turns = date(year, dob.month, dob.day) if not (dob.month == 2 and dob.day == 29) else date(year, 3, 1)
    if turns > cutoff:
        year += 1
    start = date(year, cfg["term_start_month"], cfg["term_start_day"])
    return {
        "entry_year": year,
        "term_start": start.isoformat(),
        "registration_opens_approx": (start - timedelta(days=cfg["registration_lead_days"])).isoformat(),
        "rule": f"must be {age} by {cfg['cutoff_month']:02d}-{cfg['cutoff_day']:02d}",
        "assumptions": "term start and registration lead time are placeholders; set your district's dates",
        "source": cfg.get("source"),
    }


def upcoming(dob: date, today: date, horizon_days: int = 60, lookback_days: int = 14,
             jurisdiction: str | None = None) -> list[Upcoming]:
    data = load_bundled("milestones.yaml")["milestones"]
    out: list[Upcoming] = []
    horizon = today + timedelta(days=horizon_days)
    lookback = today - timedelta(days=lookback_days)
    for m in data:
        mj = m.get("jurisdiction")
        if mj and jurisdiction and mj != jurisdiction:
            continue
        s = dob + timedelta(days=m["window_days"][0])
        e = dob + timedelta(days=m["window_days"][1])
        if s <= today <= e:
            status = "due_now"
        elif today < s <= horizon:
            status = "upcoming"
        elif lookback <= e < today:
            status = "recently_closed"
        else:
            continue
        out.append(Upcoming(m["id"], m["title"], s, e, status, m.get("note"), m.get("source"), mj,
                            m.get("taxonomy_ref")))
    order = {"due_now": 0, "upcoming": 1, "recently_closed": 2}
    out.sort(key=lambda u: (order[u.status], u.window_start))
    return out


def taxonomy(stage: str | None = None, priority_only: bool = False) -> list[dict]:
    """Return tasks from the bundled parent-chore taxonomy."""
    tx = load_bundled("taxonomy.yaml")
    rows = []
    for st in tx["stages"]:
        if stage and st["stage"] != stage:
            continue
        for t in st["tasks"]:
            if priority_only and not t.get("priority"):
                continue
            rows.append({"stage": st["stage"], **t})
    return rows
