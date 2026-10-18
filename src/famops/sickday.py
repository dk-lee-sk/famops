"""Sick-day engine: exclusion-rule evaluation and cover planning.

Everything here is deterministic. LLMs are bad at date arithmetic and policy
application; this module does that part, and the assistant explains the result.
It never assesses symptoms clinically: red flags short-circuit to escalation.

v0.2: all times are converted to the policy's timezone; age and a red-flag answer
are required before any return date; fever-medicine masking; half-day cover blocks;
helpers (grandparents, nanny) before "backup needed".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from famops import load_bundled

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# --------------------------------------------------------------------------- policy

@dataclass
class Policy:
    name: str
    tz: ZoneInfo
    opening_hours: dict[str, tuple[time, time]]
    closures: set[date]
    rules: dict[str, dict]
    red_flags: list[str]
    fever_red_flag_under_months: int | None = None
    antipyretic_masking_hours: float | None = None
    handover_at: time | None = time(13, 0)

    @classmethod
    def from_dict(cls, d: dict) -> "Policy":
        hours = {}
        for day, span in (d.get("opening_hours") or {}).items():
            start, end = span.split("-")
            hours[day.lower()[:3]] = (time.fromisoformat(start), time.fromisoformat(end))
        handover = d.get("handover_at", "13:00")
        return cls(
            name=d.get("policy_name", "unnamed policy"),
            tz=ZoneInfo(d.get("timezone", "UTC")),
            opening_hours=hours,
            closures={date.fromisoformat(str(x)) for x in d.get("closures") or []},
            rules=d.get("rules") or {},
            red_flags=d.get("red_flags") or [],
            fever_red_flag_under_months=d.get("fever_red_flag_under_months"),
            antipyretic_masking_hours=d.get("antipyretic_masking_hours"),
            handover_at=time.fromisoformat(handover) if handover else None,
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Policy":
        if path is None:
            return cls.from_dict(load_bundled("policy_example.yaml"))
        return cls.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def local(self, t: datetime) -> datetime:
        """Times without a timezone are read as the daycare's local time; others are converted."""
        return t.replace(tzinfo=self.tz) if t.tzinfo is None else t.astimezone(self.tz)

    def hours_on(self, d: date) -> tuple[time, time] | None:
        if d in self.closures:
            return None
        return self.opening_hours.get(DAYS[d.weekday()])

    def next_opening_at_or_after(self, t: datetime, max_days: int = 60) -> datetime:
        t = self.local(t)
        for offset in range(max_days + 1):
            d = (t + timedelta(days=offset)).date()
            hrs = self.hours_on(d)
            if not hrs:
                continue
            start = datetime.combine(d, hrs[0], tzinfo=self.tz)
            if start >= t:
                return start
        raise ValueError("No opening found within range; check opening_hours/closures.")

    def open_blocks(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        """Daycare opening intervals within [start, end), split at the handover time."""
        start, end = self.local(start), self.local(end)
        blocks = []
        d = start.date()
        while d <= end.date():
            hrs = self.hours_on(d)
            if hrs:
                o = datetime.combine(d, hrs[0], tzinfo=self.tz)
                c = datetime.combine(d, hrs[1], tzinfo=self.tz)
                cuts = [o, c]
                if self.handover_at:
                    h = datetime.combine(d, self.handover_at, tzinfo=self.tz)
                    if o < h < c:
                        cuts = [o, h, c]
                for a, b in zip(cuts, cuts[1:]):
                    s, e = max(a, start), min(b, end)
                    if s < e:
                        blocks.append((s, e))
            d += timedelta(days=1)
        return blocks


# --------------------------------------------------------------------------- exclusion

@dataclass
class Symptom:
    name: str                               # key in policy.rules, e.g. "fever"
    last_seen: datetime                     # last time the symptom was observed
    temp_c: float | None = None             # for fever
    treatment_start: datetime | None = None
    last_antipyretic: datetime | None = None  # last fever-reducing medicine dose


@dataclass
class ExclusionResult:
    status: str   # "needs_info" | "escalate" | "excluded" | "not_excluded" | "doctor_note_required"
    earliest_return: datetime | None = None
    cleared_at: datetime | None = None
    reasons: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    unknown_symptoms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "earliest_return": self.earliest_return.isoformat() if self.earliest_return else None,
            "cleared_at": self.cleared_at.isoformat() if self.cleared_at else None,
            "reasons": self.reasons,
            "next_steps": self.next_steps,
            "unknown_symptoms": self.unknown_symptoms,
        }


ESCALATE_MSG = ("Red flag reported. Contact your doctor or emergency services now. "
                "This tool does not assess symptoms and will not compute a return date.")


def evaluate(policy: Policy, symptoms: list[Symptom], *, child_age_months: float | None,
             red_flags_reported: list[str] | None) -> ExclusionResult:
    """Apply the policy and return the earliest return time, escalate, or ask for what's missing.

    red_flags_reported must be an explicit answer: [] means "asked, none reported";
    None means "not asked yet", which returns needs_info instead of a date.
    """
    if red_flags_reported:
        return ExclusionResult("escalate", reasons=[ESCALATE_MSG, *red_flags_reported])
    missing = []
    if red_flags_reported is None:
        missing.append("Ask the parent about red flags first: " + "; ".join(policy.red_flags)
                       + ". Pass an empty list if there are none.")
    if child_age_months is None:
        missing.append("Child's age in months is required (young babies follow stricter rules).")
    if missing:
        return ExclusionResult("needs_info", reasons=missing)

    clear_times: list[datetime] = []
    reasons: list[str] = []
    unknown: list[str] = []
    note_required = False
    next_steps: list[str] = []

    for s in symptoms:
        last_seen = policy.local(s.last_seen)
        rule = policy.rules.get(s.name)
        if rule is None:
            unknown.append(s.name)
            continue

        if s.name == "fever":
            threshold = rule.get("threshold_c", 38.0)
            if s.temp_c is not None and s.temp_c < threshold and s.last_antipyretic is None:
                reasons.append(f"fever: {s.temp_c}°C is below the {threshold}°C threshold")
                continue
            if (policy.fever_red_flag_under_months is not None
                    and child_age_months < policy.fever_red_flag_under_months):
                return ExclusionResult("escalate", reasons=[
                    ESCALATE_MSG, f"fever in a baby under {policy.fever_red_flag_under_months} months"])

        if rule.get("requires_doctor_note"):
            note_required = True
            reasons.append(f"{s.name}: return requires a doctor's note")
            next_steps.append("Book a doctor's appointment and assign it to one parent")
            continue

        if "exclude_hours_after_last" in rule:
            h = rule["exclude_hours_after_last"]
            start = last_seen
            if s.name == "fever" and s.last_antipyretic and policy.antipyretic_masking_hours:
                masked_until = policy.local(s.last_antipyretic) + timedelta(hours=policy.antipyretic_masking_hours)
                if masked_until > start:
                    start = masked_until
                    reasons.append(f"fever: medicine given at {policy.local(s.last_antipyretic):%a %H:%M} can hide a fever "
                                   f"for {policy.antipyretic_masking_hours:g}h (per policy), so the clock starts {start:%a %H:%M}")
            clear_times.append(start + timedelta(hours=h))
            reasons.append(f"{s.name}: excluded until {h}h after last occurrence")
        elif "exclude_hours_after_treatment_start" in rule:
            h = rule["exclude_hours_after_treatment_start"]
            if s.treatment_start is None:
                note_required = True
                reasons.append(f"{s.name}: excluded until {h}h after treatment starts; treatment not started")
                next_steps.append("Get treatment started (pharmacy or doctor), then report the start time")
                continue
            clear_times.append(policy.local(s.treatment_start) + timedelta(hours=h))
            reasons.append(f"{s.name}: excluded until {h}h after treatment start")
        if rule.get("note"):
            reasons.append(f"{s.name}: {rule['note']}")

    if note_required and not clear_times:
        return ExclusionResult("doctor_note_required", reasons=reasons, next_steps=next_steps,
                               unknown_symptoms=unknown)
    if not clear_times:
        return ExclusionResult("not_excluded", reasons=reasons, unknown_symptoms=unknown)

    cleared = max(clear_times)
    earliest = policy.next_opening_at_or_after(cleared)
    status = "doctor_note_required" if note_required else "excluded"
    return ExclusionResult(status, earliest_return=earliest, cleared_at=cleared, reasons=reasons,
                           next_steps=next_steps, unknown_symptoms=unknown)


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
class Helper:
    """Someone outside the couple (grandparent, nanny) who can cover when they are free."""
    name: str
    available: list[tuple[datetime, datetime]] = field(default_factory=list)


@dataclass
class CoverBlock:
    start: datetime
    end: datetime
    owner: str
    kind: str                        # "parent" | "helper" | "backup"
    conflict_minutes: int
    conflicts: list[str]
    reason: str

    @property
    def hard_conflict(self) -> bool:
        return self.kind == "backup"

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(), "end": self.end.isoformat(), "owner": self.owner,
            "kind": self.kind, "conflict_minutes": self.conflict_minutes, "conflicts": self.conflicts,
            "needs_backup_care": self.kind == "backup", "reason": self.reason,
        }


def _overlap_minutes(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> int:
    s, e = max(a0, b0), min(a1, b1)
    return max(0, int((e - s).total_seconds() // 60))


def plan_cover(policy: Policy, parents: list[Parent], now: datetime, return_at: datetime,
               helpers: list[Helper] | None = None) -> list[CoverBlock]:
    """Propose one carer per half-day block between `now` and `return_at`.

    Rule: a parent without an immovable (hard) conflict beats one with; then fewest
    conflicting minutes; then whoever has covered less this season; then alphabetical.
    If every parent has a hard conflict, a helper who is free for the whole block is
    proposed; failing that, the block is flagged as needing backup care.
    The result is a PROPOSAL: the server sends each block as a handoff to accept.
    """
    if not parents:
        raise ValueError("At least one parent is required.")
    helpers = helpers or []
    loc = policy.local
    tally = {p.name: p.cover_minutes_to_date for p in parents}
    plan: list[CoverBlock] = []
    for b0, b1 in policy.open_blocks(now, return_at):
        scored = []
        for p in parents:
            mins, titles, hard = 0, [], False
            for bz in p.busy:
                m = _overlap_minutes(b0, b1, loc(bz.start), loc(bz.end))
                if m:
                    mins += m
                    titles.append(bz.title or "busy")
                    hard = hard or bz.hard
            scored.append((hard, mins, tally[p.name], p.name, titles))
        scored.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
        hard, mins, _, name, titles = scored[0]
        block_min = int((b1 - b0).total_seconds() // 60)

        if hard:
            free = next((h for h in helpers
                         if any(loc(a) <= b0 and loc(z) >= b1 for a, z in h.available)), None)
            if free:
                plan.append(CoverBlock(b0, b1, free.name, "helper", 0, [],
                                       "Both parents have commitments that can't move; helper is free."))
                continue
            plan.append(CoverBlock(b0, b1, name, "backup", mins, titles,
                                   "Both parents have commitments that can't move and no helper is free."))
            tally[name] += block_min
            continue

        runner = scored[1] if len(scored) > 1 else None
        if runner is None:
            why = "Only parent listed."
        elif runner[0]:
            why = f"{runner[3]} has a commitment that can't move."
        elif runner[1] > mins:
            why = f"{runner[3]} has more clashes ({runner[1]} min)."
        else:
            why = f"Tie on clashes; {name} has covered less this season."
        tally[name] += block_min
        plan.append(CoverBlock(b0, b1, name, "parent", mins, titles, why))
    return plan
