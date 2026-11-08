# famops status

_Last updated: 2026-11-08 (seeded by Claude from repo history and docs; DK to confirm "Next")_

## Goal
An ownership and handoff layer for two-parent households that plugs into any MCP assistant. Wedge: the daycare
sick-day call. Path and kill criteria are in `docs/PRODUCT.md`.

## Stage
Stage 0, open source. v0.2.0 released 2026-10-18; CI on GitHub Actions; 42 tests.

## Done recently
- 2026-10-30: README: demo GIF, CI/Python/licence badges, how famops was built (PR #2)
- 2026-10-18: v0.2.0 real-life fixes (return-date safety, timezones, half-day cover, handoff expiry) (PR #1)
- 2026-10-16: v0.1.0: ownership ledger, sick-day engine, anticipate engine, MCP server, 92-task taxonomy

## Next (seeded from docs, not yet confirmed by DK)
1. Stage 0 success test: 5 households run `famops-mcp` for a month, at least 3 sick days logged through it
2. Stage 1: `bench/` comparing general assistants with and without famops on sick-day tasks

## Blockers and decisions waiting on DK
- Recruiting the 5 pilot households
- Two merged branches still on the remote (`readme-visuals`, `v0.2-real-life-fixes`): delete or keep

## Metrics
Households using it: no data recorded yet.
