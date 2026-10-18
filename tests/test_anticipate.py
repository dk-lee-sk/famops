from datetime import date

from famops.anticipate import school_entry, taxonomy, upcoming


def ids(items):
    return {u.id for u in items}


def test_pregnancy_waitlist_prompt():
    dob = date(2027, 3, 1)
    got = upcoming(dob, today=date(2026, 7, 1))
    assert "waitlists" in ids(got)


def test_five_month_old_solids_and_allergens():
    dob = date(2026, 5, 15)
    got = {u.id: u.status for u in upcoming(dob, today=date(2026, 10, 16))}
    assert got["solids_readiness"] == "due_now"
    assert got["allergen_introduction"] == "due_now"


def test_jurisdiction_filter():
    dob = date(2026, 10, 1)
    assert "insurance_enrolment_us" in ids(upcoming(dob, date(2026, 10, 10)))
    assert "insurance_enrolment_us" not in ids(upcoming(dob, date(2026, 10, 10), jurisdiction="CH"))


def test_school_entry_cutoff():
    assert school_entry(date(2025, 8, 31))["entry_year"] == 2030   # turns 5 before cutoff
    assert school_entry(date(2025, 9, 2))["entry_year"] == 2031    # misses cutoff


def test_taxonomy_counts():
    assert len(taxonomy()) == 92
    assert len(taxonomy(priority_only=True)) == 15
    assert all(t["stage"] == "toddler" for t in taxonomy("toddler"))


def test_premature_baby_uses_corrected_age_for_development_only():
    dob = date(2026, 5, 15)
    term = {u.id for u in upcoming(dob, today=date(2026, 9, 20))}
    early = {u.id: u for u in upcoming(dob, today=date(2026, 9, 20), weeks_premature=8)}
    assert "solids_readiness" in term          # 4 months old at term
    assert "solids_readiness" not in early or early["solids_readiness"].status == "upcoming"
