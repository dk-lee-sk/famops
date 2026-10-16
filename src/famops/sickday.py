"""Sick-day engine: exclusion-rule evaluation and cover planning.

Everything here is deterministic. LLMs are bad at date arithmetic and policy
application; this module does that part, and the assistant explains the result.
It never assesses symptoms clinically: red flags short-circuit to escalation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import yaml

from famops import load_bundled

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# --------------------------------------------------------------------------- policy

@dataclass
class Policy:
    name: str
    opening_hours: dict[str, tuple[time, time]]
    closures: set[date]
    rules: dict[str, dict]
    red_flags: list[str]
    fever_red_flag_under_months: int | None = None
    return_rule: str = "next_opening"

    @classmethod
    def from_dict(cls, d: dict) -> "Policy":
        hours = {}
        for day, span in (d.get("opening_hours") or {}).items():
            start, end = span.split("-")
            hours[day.lower()[:3]] = (time.fromisoformat(start), time.fromisoformat(end))
        return cls(
            name=d.get("policy_name", "unnamed policy"),
            opening_hours=hours,
            closures={date.fromisoformat(str(x)) for x in d.get("closures") or []},
            rules=d.get("rules") or {},
            red_flags=d.get("red_flags") or [],
            fever_red_flag_under_months=d.get("fever_red_flag_under_months"),
            return_rule=d.get("return_rule", "next_opening"),
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Policy":
        if path is None:
            return cls.from_dict(load_bundled("policy_example.yaml"))
        return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    # -- calendar helpers
    def hours_on(self, d: date) -> tuple[time, time] | None:
        if d in self.closures:
            return None
        return self.opening_hours.get(DAYS[d.weekday()])

    def next_opening_at_or_after(self, t: datetime, max_days: int = 60) -> datetime:
        for offset in range(max_days + 1):
            d = (t + timedelta(days=offset)).date()
            hrs = self.hours_on(d)
            if not hrs:
                continue
            start = datetime.combine(d, hrs[0], tzinfo=t.tzinfo)
            if start >= t:
                return start
        raise ValueError("No opening found within range; check opening_hours/closures.")

    def open_blocks(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        """Daycare opening intervals intersected with [start, end)."""
        blocks = []
        d = start.date()
        while d <= end.date():
            hrs = self.hours_on(d)
            if hrs:
                o = datetime.combine(d, hrs[0], tzinfo=start.tzinfo)
                c = datetime.combine(d, hrs[1], tzinfo=start.tzinfo)
                s, e = max(o, start), min(c, end)
                if s < e:
                    blocks.append((s, e))
            d += timedelta(days=1)
        return blocks


# --------------------------------------------------------------------------- exclusion

@dataclass
class Symptom:
    name: str                       # key in policy.rules, e.g. "fever"
    last_seen: datetime             # last time the symptom was observed
    temp_c: float | None = None     # for fever
    treatment_start: datetime | None = None


@dataclass
class ExclusionResult:
    status: str                     # "escalate" | "excluded" | "not_excluded" | "doctor_note_required"
    earliest_return: datetime | None = None
    cleared_at: datetime | None = None
    reasons: list[str] = field(default_factory=list)
    unknown_symptoms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "earliest_return": self.earliest_return.isoformat() if self.earliest_return else None,
            "cleared_at": self.cleared_at.isoformat() if self.cleared_at else None,
            "reasons": self.reasons,
            "unknown_symptoms": self.unknown_symptoms,
        }


ESCALATE_MSG = ("Red flag reported. Contact your doctor or emergency services now. "
                "This tool does not assess symptoms and will not compute a return date.")


def evaluate(policy: Policy, symptoms: list[Symptom], *, child_age_months: float | None = None,
             red_flags_reported: list[str] | None = None) -> ExclusionResult:
    """Apply the policy and return the earliest return time, or escalate."""
    if red_flags_reported:
        return ExclusionResult("escalate", reasons=[ESCALATE_MSG, *red_flags_reported])

    clear_times: list[datetime] = []
    reasons: list[str] = []
    unknown: list[str] = []
    note_required = False

    for s in symptoms:
        rule = policy.rules.get(s.name)
        if rule is None:
            unknown.append(s.name)
            continue

        if s.name == "fever":
            threshold = rule.get("threshold_c", 38.0)
            if s.temp_c is not None and s.temp_c < threshold:
                reasons.append(f"fever: {s.temp_c}°C is below the {threshold}°C threshold")
                continue
            if (child_age_months is not None and policy.fever_red_flag_under_months is not None
                    and child_age_months < policy.fever_red_flag_under_months):
                return ExclusionResult("escalate", reasons=[
                    ESCALATE_MSG,
                    f"fever in a baby under {policy.fever_red_flag_under_months} months"])

        if rule.get("requires_doctor_note"):
            note_required = True
            reasons.append(f"{s.name}: return requires a doctor's note")
            continue

        if "exclude_hours_after_last" in rule:
            h = rule["exclude_hours_after_last"]
            clear_times.append(s.last_seen + timedelta(hours=h))
            reasons.append(f"{s.name}: excluded until {h}h after last occurrence")
        elif "exclude_hours_after_treatment_start" in rule:
            if s.treatment_start is None:
                reasons.append(f"{s.name}: treatment not started; excluded until {rule['exclude_hours_after_treatment_start']}h after it starts")
                note_required = True  # cannot compute; parent action needed
                continue
            h = rule["exclude_hours_after_treatment_start"]
            clear_times.append(s.treatment_start + timedelta(hours=h))
            reasons.append(f"{s.name}: excluded until {h}h after treatment start")
        if rule.get("note"):
            reasons.append(f"{s.name}: {rule['note']}")

    if note_required and not clear_times:
        return ExclusionResult("doctor_note_required", reasons=reasons, unknown_symptoms=unknown)
    if not clear_times:
        return ExclusionResult("not_excluded", reasons=reasons, unknown_symptoms=unknown)

    cleared = max(clear_times)
    earliest = policy.next_opening_at_or_after(cleared)
    status = "doctor_note_required" if note_required else "excluded"
    return ExclusionResult(status, earliest_return=earliest, cleared_at=cleared,
                           reasons=reasons, unknown_symptoms=unknown)


# --------------------------------------------------------------------------- cover planning

@dataclass
class Busy:
    start: datetime
    end: datetime
    title: str = ""
    hard: bool = False              # cannot be moved (flight, surgery, exam)


@dataclass
class Parent:
    name: str
    busy: list[Busy] = field(default_factory=list)
    cover_minutes_to_date: int = 0  # fairness memory across the season


@dataclass
class CoverBlock:
    start: datetime
    end: datetime
    owner: str
    conflict_minutes: int
    conflicts: list[str]
    hard_conflict: bool

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(), "end": self.end.isoformat(), "owner": self.owner,
            "conflict_minutes": self.conflict_minutes, "conflicts": self.conflicts,
            "needs_backup_care": self.hard_conflict,
        }


def _overlap_minutes(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> int:
    s, e = max(a0, b0), min(a1, b1)
    return max(0, int((e - s).total_seconds() // 60))


def plan_cover(policy: Policy, parents: list[Parent], now: datetime, return_at: datetime) -> list[CoverBlock]:
    """Assign one owner per day-block of care needed between `now` and `return_at`.

    Rule: a parent without an immovable (hard) conflict beats one with; then fewest
    conflicting minutes; then whoever has covered less this season (updated as blocks
    are assigned); then alphabetical. If every parent has a hard conflict, the block
    is flagged as needing backup care.
    """
    if not parents:
        raise ValueError("At least one parent is required.")
    tally = {p.name: p.cover_minutes_to_date for p in parents}
    plan: list[CoverBlock] = []
    for b0, b1 in policy.open_blocks(now, return_at):
        scored = []
        for p in parents:
            mins, titles, hard = 0, [], False
            for bz in p.busy:
                m = _overlap_minutes(b0, b1, bz.start, bz.end)
                if m:
                    mins += m
                    titles.append(bz.title or "busy")
                    hard = hard or bz.hard
            scored.append((hard, mins, tally[p.name], p.name, titles))
        scored.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
        hard, mins, _, name, titles = scored[0]
        tally[name] += int((b1 - b0).total_seconds() // 60)
        plan.append(CoverBlock(b0, b1, name, mins, titles, hard))
    return plan
