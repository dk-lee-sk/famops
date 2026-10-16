# From repo to product

## Positioning

The family-AI market is splitting into two crowded lanes:

- **Advice:** Joy, Riley and Sprouty answer parenting questions.
- **Inbox scraping:** Fambot and Goldee read family email and pull out events and to-dos.

famops takes a third position: **an ownership and handoff layer that sits underneath any assistant.** It doesn't compete with ChatGPT or Claude. It gives them state and rules they don't have: who owns which task, what the daycare's policy allows, and who covers which day.

## Wedge: the sick-day call

It's the strongest first use case for four reasons:

- **Frequent.** Children under 2 get roughly 3.4 illnesses a year, mostly in winter.
- **Painful.** About half of parents of under-6s in childcare miss work for it.
- **Rule-bound.** It depends on exclusion policies and calendars, which deterministic code can check.
- **Inherently two-parent.** It is a split decision, which is where the ownership thesis matters.

## Path

| Stage | What ships | Success test |
|---|---|---|
| 0. Open source (now) | This repo plus the taxonomy | 5 households run `famops-mcp` for a month; at least 3 sick days are logged through it |
| 1. Benchmark | `bench/` compares general assistants with and without famops on sick-day tasks | famops closes a measurable gap in getting return dates and owner assignment right |
| 2. Hosted beta | Hosted MCP endpoint, Google Calendar sync, SMS/WhatsApp nudges for unanswered handoffs | More than 40% of sick days are resolved with no message between parents outside the tool |
| 3. Payer | Employer pilot measuring unplanned absence from child illness and backup-care spend avoided | The pilot produces a metric a CFO can use |

## What stays open source vs paid

- **Open:** the ledger, the sick-day engine, the anticipate engine and the taxonomy. These build trust and distribution, and they sit in health-adjacent territory where auditability matters.
- **Paid:** hosted sync, calendar and email ingestion, nudges, the employer dashboard and policy libraries per daycare network.

## Kill criteria

- **If general assistants with calendar access already handle sick-day handoff reliably** (from the bench results), stop building the engine and keep only the ledger.
- **If households won't log tasks after the first two weeks,** the ownership thesis fails on behaviour, not technology. Go back to interviews before building more.
