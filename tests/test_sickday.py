from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from famops.sickday import Busy, Helper, Parent, Policy, Symptom, evaluate, plan_cover

TZ = ZoneInfo("Europe/Zurich")


def dt(*a):
    return datetime(*a, tzinfo=TZ)


def ev(policy, symptoms, age=20, flags=()):
    return evaluate(policy, symptoms, child_age_months=age, red_flags_reported=list(flags))


@pytest.fixture
def policy():
    return Policy.load()


@pytest.fixture
def whole_day():
    p = Policy.load()
    p.handover_at = None
    return p


# ---------------------------------------------------------------- exclusion

def test_thursday_fever_returns_monday(policy):
    r = ev(policy, [Symptom("fever", dt(2026, 10, 15, 11), 38.5)])
    assert r.status == "excluded"
    assert r.cleared_at == dt(2026, 10, 16, 11)
    assert r.earliest_return == dt(2026, 10, 19, 7, 30)


def test_clear_before_opening_returns_same_day(policy):
    r = ev(policy, [Symptom("vomiting", dt(2026, 10, 12, 6))])
    assert r.earliest_return == dt(2026, 10, 14, 7, 30)


def test_multiple_symptoms_take_latest(policy):
    r = ev(policy, [Symptom("fever", dt(2026, 10, 12, 9), 39.0), Symptom("diarrhoea", dt(2026, 10, 12, 20))])
    assert r.cleared_at == dt(2026, 10, 14, 20)
    assert r.earliest_return == dt(2026, 10, 15, 7, 30)


def test_temperature_below_threshold_not_excluded(policy):
    assert ev(policy, [Symptom("fever", dt(2026, 10, 12, 9), 37.6)]).status == "not_excluded"


def test_fever_medicine_delays_the_clock(policy):
    # fever at Mon 09:00, paracetamol at Mon 10:00 -> masked until 18:00 -> clear Tue 18:00 -> Wed 07:30
    r = ev(policy, [Symptom("fever", dt(2026, 10, 12, 9), 38.4, last_antipyretic=dt(2026, 10, 12, 10))])
    assert r.cleared_at == dt(2026, 10, 13, 18)
    assert r.earliest_return == dt(2026, 10, 14, 7, 30)


def test_normal_reading_after_medicine_still_excludes(policy):
    r = ev(policy, [Symptom("fever", dt(2026, 10, 12, 9), 37.2, last_antipyretic=dt(2026, 10, 12, 8))])
    assert r.status == "excluded"


def test_missing_age_asks_instead_of_dating(policy):
    r = evaluate(policy, [Symptom("fever", dt(2026, 10, 12, 9), 38.5)], child_age_months=None, red_flags_reported=[])
    assert r.status == "needs_info" and r.earliest_return is None


def test_red_flags_not_asked_asks_instead_of_dating(policy):
    r = evaluate(policy, [Symptom("fever", dt(2026, 10, 12, 9), 38.5)], child_age_months=20, red_flags_reported=None)
    assert r.status == "needs_info"
    assert "difficulty breathing" in r.reasons[0]


def test_fever_in_young_baby_escalates(policy):
    assert ev(policy, [Symptom("fever", dt(2026, 10, 12, 9), 38.2)], age=2).status == "escalate"


def test_red_flag_escalates_and_never_returns_date(policy):
    r = ev(policy, [Symptom("fever", dt(2026, 10, 12, 9), 38.5)], flags=["difficulty breathing"])
    assert r.status == "escalate" and r.earliest_return is None


def test_doctor_note_gives_a_next_step(policy):
    r = ev(policy, [Symptom("rash_with_fever", dt(2026, 10, 12, 9))])
    assert r.status == "doctor_note_required"
    assert r.next_steps


def test_naive_and_aware_times_mix(policy):
    # v0.1 crashed here: a time without a timezone next to one with a timezone
    r = ev(policy, [Symptom("fever", datetime(2026, 10, 15, 11), 38.5)])
    assert r.earliest_return == dt(2026, 10, 19, 7, 30)
    a = Parent("A", [Busy(datetime(2026, 10, 15, 9, 0, tzinfo=ZoneInfo("UTC")), dt(2026, 10, 15, 13), "call")])
    plan = plan_cover(policy, [a, Parent("B")], datetime(2026, 10, 15, 11), r.earliest_return)
    assert plan[0].owner == "B"


def test_closure_day_skipped():
    p = Policy.from_dict({"timezone": "Europe/Zurich", "opening_hours": {"mon": "08:00-18:00", "tue": "08:00-18:00"},
                          "closures": ["2026-10-13"], "rules": {"vomiting": {"exclude_hours_after_last": 1}}})
    r = ev(p, [Symptom("vomiting", dt(2026, 10, 12, 20))])
    assert r.earliest_return == dt(2026, 10, 19, 8)


# ---------------------------------------------------------------- cover

def test_days_split_at_handover(policy):
    plan = plan_cover(policy, [Parent("A")], dt(2026, 10, 14, 7, 30), dt(2026, 10, 15, 7, 30))
    assert [(b.start.hour, b.end.hour) for b in plan] == [(7, 13), (13, 18)]


def test_split_lets_each_parent_take_a_half(policy):
    a = Parent("A", [Busy(dt(2026, 10, 14, 14), dt(2026, 10, 14, 16), "pm meeting")])
    b = Parent("B", [Busy(dt(2026, 10, 14, 9), dt(2026, 10, 14, 11), "am meeting")])
    plan = plan_cover(policy, [a, b], dt(2026, 10, 14, 7, 30), dt(2026, 10, 15, 7, 30))
    assert [x.owner for x in plan] == ["A", "B"]


def test_cover_prefers_fewer_conflicts(whole_day):
    a = Parent("A", [Busy(dt(2026, 10, 14, 9), dt(2026, 10, 14, 12), "mtg")])
    b = Parent("B", [Busy(dt(2026, 10, 14, 13), dt(2026, 10, 14, 14), "1:1")])
    plan = plan_cover(whole_day, [a, b], dt(2026, 10, 14, 7, 30), dt(2026, 10, 15, 7, 30))
    assert [x.owner for x in plan] == ["B"] and plan[0].conflict_minutes == 60


def test_hard_conflict_loses_even_with_fewer_minutes(whole_day):
    a = Parent("A", [Busy(dt(2026, 10, 14, 9), dt(2026, 10, 14, 10), "flight", hard=True)])
    b = Parent("B", [Busy(dt(2026, 10, 14, 9), dt(2026, 10, 14, 13), "workshop")])
    plan = plan_cover(whole_day, [a, b], dt(2026, 10, 14, 7, 30), dt(2026, 10, 15, 7, 30))
    assert plan[0].owner == "B" and plan[0].kind == "parent"


def test_fairness_breaks_ties_and_alternates(whole_day):
    plan = plan_cover(whole_day, [Parent("A"), Parent("B")], dt(2026, 10, 12, 7, 30), dt(2026, 10, 15, 7, 30))
    assert [x.owner for x in plan] == ["A", "B", "A"]


def test_helper_covers_when_both_parents_are_stuck(policy):
    a = Parent("A", [Busy(dt(2026, 10, 14, 7), dt(2026, 10, 14, 19), "surgery", hard=True)])
    b = Parent("B", [Busy(dt(2026, 10, 14, 7), dt(2026, 10, 14, 19), "exam", hard=True)])
    gran = Helper("Grandma", [(dt(2026, 10, 14, 7), dt(2026, 10, 14, 13))])
    plan = plan_cover(policy, [a, b], dt(2026, 10, 14, 7, 30), dt(2026, 10, 15, 7, 30), [gran])
    assert [(x.owner, x.kind) for x in plan] == [("Grandma", "helper"), ("A", "backup")]
    assert plan[1].to_dict()["needs_backup_care"] is True


def test_cover_skips_weekend(policy):
    plan = plan_cover(policy, [Parent("A")], dt(2026, 10, 16, 11), dt(2026, 10, 19, 7, 30))
    assert len(plan) == 2 and plan[0].start == dt(2026, 10, 16, 11)
