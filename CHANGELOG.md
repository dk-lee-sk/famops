# Changelog

## 0.2.0: real-life fixes (2026-10-18)

Based on a review of how v0.1 would behave in a real household.

**Safety and correctness**
- Return dates now need the child's age and an explicit red-flag answer; otherwise famops asks for them (`needs_info`). v0.1 gave a date for a fever when no age was passed.
- All times are converted to the daycare's timezone. v0.1 crashed when one time had a timezone and another didn't.
- Fever medicine: a normal temperature soon after a dose doesn't start the 24-hour clock. The length is set in the policy (`antipyretic_masking_hours`).
- "Doctor's note needed" now comes with a next step instead of a dead end.

**Ownership**
- Each connection acts for one parent (`FAMOPS_USER`). A request can no longer claim to be the other parent.
- Cover plans are proposals. Blocks for the other parent arrive as handoffs to accept or decline.
- Unanswered handoffs go back to the sender after 24 hours.
- Tasks carry an effort estimate; the balance view shows minutes as well as counts.

**Planning**
- Cover is planned in half-days (handover at 13:00 by default), so parents can split a day.
- Helpers (grandparents, nanny) are proposed before "backup care needed".
- Corrected age for premature babies on developmental milestones.
- Milestones can be added to the ledger as owned tasks without duplicates.

**Upgrade note:** existing v0.1 databases are migrated automatically. Tool signatures changed: `by` and `from_owner` parameters are gone because the acting parent comes from `FAMOPS_USER`.

## 0.1.0 (2026-10-16)

First version: ownership ledger, sick-day engine, anticipate engine, MCP server, 92-task taxonomy.
