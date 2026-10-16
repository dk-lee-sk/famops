from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from famops.sickday import Busy, Parent, Policy, Symptom, evaluate, plan_cover

TZ = ZoneInfo("Europe/Zurich")


def dt(*a):
    return datetime(*a, tzinfo=TZ)


@pytest.fixture
def policy():
    return Policy.load()


def test_thursday_fever_returns_monday(policy):
    # Thu 11:00 fever -> clear Fri 11:00 -> next opening is Mon 07:30
    r = evaluate(policy, [Symptom("fever", dt(2026, 10, 15, 11), 38.5)], child_age_months=20)
    assert r.status == "excluded"
    assert r.cleared_at == dt(2026, 10, 16, 11)
    assert r.earliest_return == dt(2026, 10, 19, 7, 30)


def test_clear_before_opening_returns_same_day(policy):
    # Vomiting last at Mon 06:00 -> clear Wed 06:00 -> Wed 07:30
    r = evaluate(policy, [Symptom("vomiting", dt(2026, 10, 12, 6))])
    assert r.earliest_return == dt(2026, 10, 14, 7, 30)


def test_multiple_symptoms_take_latest(policy):
    r = evaluate(policy, [Symptom("fever", dt(2026, 10, 12, 9), 39.0),
                          Symptom("diarrhoea", dt(2026, 10, 12, 20))])
    assert r.cleared_at == dt(2026, 10, 14, 20)
    assert r.earliest_return == dt(2026, 10, 15, 7, 30)


def test_temperature_below_threshold_not_excluded(policy):
    r = evaluate(policy, [Symptom("fever", dt(2026, 10, 12, 9), 37.6)])
    assert r.status == "not_excluded"
    assert r.earliest_return is None


def test_fever_in_young_baby_escalates(policy):
    r = evaluate(policy, [Symptom("fever", dt(2026, 10, 12, 9), 38.2)], child_age_months=2)
    assert r.status == "escalate"
    assert r.earliest_return is None


def test_red_flag_escalates_and_never_returns_date(policy):
    r = evaluate(policy, [Symptom("fever", dt(2026, 10, 12, 9), 38.5)],
                 red_flags_reported=["difficulty breathing"])
    assert r.status == "escalate"
    assert r.earliest_return is None


def test_doctor_note_rule(policy):
    r = evaluate(policy, [Symptom("rash_with_fever", dt(2026, 10, 12, 9))])
    assert r.status == "doctor_note_required"


def test_unknown_symptom_is_reported(policy):
    r = evaluate(policy, [Symptom("hiccups", dt(2026, 10, 12, 9))])
    assert r.unknown_symptoms == ["hiccups"]


def test_closure_day_skipped():
    p = Policy.from_dict({"opening_hours": {"mon": "08:00-18:00", "tue": "08:00-18:00"},
                          "closures": ["2026-10-13"],
                          "rules": {"vomiting": {"exclude_hours_after_last": 1}}})
    r = evaluate(p, [Symptom("vomiting", dt(2026, 10, 12, 20))])
    assert r.earliest_return == dt(2026, 10, 19, 8)  # Tue closed, next Mon


def test_cover_prefers_fewer_conflicts(policy):
    a = Parent("A", [Busy(dt(2026, 10, 14, 9), dt(2026, 10, 14, 12), "mtg")])
    b = Parent("B", [Busy(dt(2026, 10, 14, 13), dt(2026, 10, 14, 14), "1:1")])
    plan = plan_cover(policy, [a, b], dt(2026, 10, 14, 7, 30), dt(2026, 10, 15, 7, 30))
    assert [x.owner for x in plan] == ["B"]
    assert plan[0].conflict_minutes == 60


def test_hard_conflict_loses_even_with_fewer_minutes(policy):
    a = Parent("A", [Busy(dt(2026, 10, 14, 9), dt(2026, 10, 14, 10), "flight", hard=True)])
    b = Parent("B", [Busy(dt(2026, 10, 14, 9), dt(2026, 10, 14, 13), "workshop")])
    plan = plan_cover(policy, [a, b], dt(2026, 10, 14, 7, 30), dt(2026, 10, 15, 7, 30))
    assert plan[0].owner == "B"
    assert not plan[0].hard_conflict


def test_fairness_breaks_ties_and_alternates(policy):
    a, b = Parent("A", cover_minutes_to_date=0), Parent("B", cover_minutes_to_date=0)
    plan = plan_cover(policy, [a, b], dt(2026, 10, 12, 7, 30), dt(2026, 10, 15, 7, 30))
    assert [x.owner for x in plan] == ["A", "B", "A"]


def test_all_hard_conflicts_flag_backup(policy):
    a = Parent("A", [Busy(dt(2026, 10, 14, 9), dt(2026, 10, 14, 17), "surgery", hard=True)])
    b = Parent("B", [Busy(dt(2026, 10, 14, 8), dt(2026, 10, 14, 18), "exam", hard=True)])
    plan = plan_cover(policy, [a, b], dt(2026, 10, 14, 7, 30), dt(2026, 10, 15, 7, 30))
    assert plan[0].hard_conflict
    assert plan[0].to_dict()["needs_backup_care"] is True


def test_cover_skips_weekend(policy):
    plan = plan_cover(policy, [Parent("A")], dt(2026, 10, 16, 11), dt(2026, 10, 19, 7, 30))
    assert len(plan) == 1 and plan[0].start == dt(2026, 10, 16, 11)
