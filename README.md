# famops

**A shared operations layer for two-parent households.** famops keeps track of who owns each family task, works out sick-day exclusions and cover, and flags age-based deadlines before they become urgent. It plugs into any AI assistant that supports MCP (Model Context Protocol), Claude included.

> The thesis: parental mental load is an **ownership** problem, not an information problem. Shared calendars already exist. What's missing is a system where every task has exactly one owner, and ownership only moves when the other parent accepts it.

## Why this exists

Research behind the design (full taxonomy in [`src/famops/data/taxonomy.yaml`](src/famops/data/taxonomy.yaml)):

- **The most urgent parenting tasks are about cover and deadlines, not advice.** The taxonomy scores 92 tasks from newborn to preschool. The 15 that need both parents, are time-critical and suit AI help are sick-day cover, pickup and drop-off rotas, and enrolment deadlines.
- **Sick days are the anchor.** About half of parents of under-6s in childcare missed work for a sick child in a year, and about two-thirds had a child sent home or kept out of childcare for illness (C.S. Mott poll, 2012).
- **The unequal work is the invisible part.** Anticipating and monitoring are the household-labour steps split least evenly between partners (Daminger, *American Sociological Review*, 2019).
- **General-purpose assistants are unreliable with dates and policy rules.** famops does that part deterministically, and the assistant explains the result in plain language.

## What it does (v0.1)

| Module | What it does | Taxonomy tasks covered |
|---|---|---|
| `ledger` | SQLite task ledger. Every task has exactly one owner, ownership moves only on an accepted handoff, there's an audit log, and it shows each parent's load | All tasks that need an owner |
| `sickday` | Applies a daycare exclusion policy to compute the earliest return time, then assigns one parent per day of cover based on calendar conflicts, immovable meetings and fairness so far this season | I12–I14, T05–T07, P16 |
| `anticipate` | Turns a child's date of birth into tasks that are due now or coming up (waitlists, check-ups, solids and allergens, potty training) and works out which school year they start | N01, N03, N10, N13, N15, I07, I08, T09, P01 |
| `server` | MCP server exposing all of the above as tools | — |

**Safety boundary.** `sickday` never assesses symptoms. If the parent reports any red flag, or a baby under 3 months has a fever, it returns `escalate` with an instruction to contact a clinician. It never returns a date in that case. The bundled daycare policy is **synthetic**: replace it with your own daycare's written policy.

## Quickstart

```bash
git clone https://github.com/<you>/famops && cd famops
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

famops demo                                   # daycare calls Thursday 11:00: fever 38.5°C
famops upcoming --dob 2025-02-10              # what's coming for a 20-month-old
famops taxonomy --stage toddler --priority    # priority tasks for toddlers
pytest
```

### Use it from Claude (or any MCP client)

Add this to your MCP client config (for Claude Desktop, that's `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "famops": {
      "command": "famops-mcp",
      "env": {
        "FAMOPS_DB": "~/.famops/famops.db",
        "FAMOPS_POLICY": "/path/to/your_daycare_policy.yaml"
      }
    }
  }
}
```

Then you can ask, for example: *"Daycare just called, fever 38.5 at 11. When can she go back, and who covers? Here are both our calendars."* The assistant calls `report_illness`, then `plan_sick_cover`, and writes the result to the ledger as owned tasks.

## Tools

| Tool | Purpose |
|---|---|
| `set_household(members)` | Register the adults in the household |
| `create_task(title, owner, due?, ref?)` | Create a task; an owner is mandatory |
| `list_tasks(owner?, status?)` | List tasks, optionally filtered |
| `handoff_task(id, from, to, note?)` | Propose a handoff (status becomes `handoff_pending`) |
| `respond_to_handoff(id, by, accept)` | Only the proposed new owner can accept or decline |
| `complete_task(id, by)` | Only the owner can mark a task done |
| `load_balance(days?)` | Open and recently completed tasks per parent |
| `report_illness(symptoms, child_age_months?, red_flags?)` | Apply the exclusion policy: earliest return time, or `escalate` |
| `plan_sick_cover(now, return_at, parents, create_tasks?)` | One owner per day-block, with backup-care flags |
| `upcoming_for_child(dob, today?, horizon_days?)` | Age-anchored tasks plus school entry year |
| `taxonomy_tasks(stage?, priority_only?)` | Query the 92-task taxonomy |

## Writing your daycare's policy

Copy `src/famops/data/policy_example.yaml` and set:

- opening hours and closure dates
- an exclusion rule per symptom: `exclude_hours_after_last`, `exclude_hours_after_treatment_start` or `requires_doctor_note`
- the red flags that should trigger escalation

## Roadmap

| Version | Scope | Why |
|---|---|---|
| 0.2 | Read calendars from Google Calendar or ICS, so busy times don't have to be typed in | Removes the main manual step |
| 0.3 | Turn daycare emails and app posts into owned tasks, with the AI reading the message and the ledger storing the tasks | Covers the largest benchmark category (daycare messages) |
| 0.4 | `bench/`: toddler-ops-bench, comparing general AI assistants with and without famops | Shows whether famops adds value, with data |
| 0.5 | Daily digest per parent, nudges when a handoff goes unanswered, a monthly load review | Targets the anticipating and monitoring work |
| Later | Multi-device sync and a thin mobile client | Only after the core loop is validated |

## Status and caveats

- This is a v0.1 prototype and is not medical software. Exclusion logic only applies the policy you give it.
- The evidence behind the taxonomy is mostly from the US. Deadlines such as insurance enrolment and school entry vary by country, and US-specific items are tagged.
- Taxonomy rows with source `U` are unsourced and need validating with parents.

## License

MIT
