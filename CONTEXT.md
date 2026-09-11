# Health Tracker — CONTEXT

If the task is not health (WHOOP, meals, merge, or habits), go back to `..\ROUTER.md`.

Building-wide rules: `..\AGENTS.md`.

This is a **room** (merge + habit log) with three scheduled machines writing into it. WHOOP collection and meal logging are sibling offices, not this folder's job.

## Floor map

| You want to… | Go to | Read first |
|---|---|---|
| Sync WHOOP | `..\whoop-data\` | `..\whoop-data\CONTEXT.md` |
| Log meals / food library | `..\MyFitnessClone\` | `..\MyFitnessClone\CONTEXT.md` |
| Merge sources into the master table | this folder | `README.md` |
| Nightly habit sentence | `habits\` | `habits\README.md` |
| Code-Geeko nightly repo scan | `codegeeko\` | `codegeeko\README.md` |

## What this is

Joins WHOOP days, meal days, water days, and the habit log into one master table, and holds the nightly habit write.

Upstream:

- WHOOP CSVs: `..\whoop-data\` (read its `CONTEXT.md`)
- Meals: `..\MyFitnessClone\` (read its `CONTEXT.md`) — frozen since 2026-07-25; the merge reports the meal source STALE on every run and stays green anyway
- Water: `..\MyFitnessClone\` (`Water_Data_Dashboard.csv`, same repo as meals) — daily fl oz against a 128 fl oz goal; optional, so a missing water file warns and the WHOOP+meal merge still runs

## What runs without you

Three machines commit to this repo. Do not hand-run their work before checking whether they already did it.

| Machine | When | What it writes | Details |
|---|---|---|---|
| Health Tracker Consolidation (`.github\workflows\consolidate.yml`) | GitHub Actions cron `30 13 * * *`, plus `repository_dispatch` | `Health_Tracker_Master.csv`, `schema\`, `logs\` | `README.md` |
| Code-Geeko Nightly (`.github\workflows\code-geeko-nightly.yml`) | GitHub Actions cron `0 6 * * *` | `.code-geeko\state.json` | `codegeeko\README.md` |
| WHOOP Daily Sync (`..\whoop-data\run-once.ps1`) | Windows task, 07:00 local | `habits.csv`, `logs\habits_audit.jsonl` | `habits\README.md` |

## Read next

- How the merge works: `README.md`
- Habit log (one sentence a night, blank is not "no"): `habits\README.md`
- Code-Geeko scan: `codegeeko\README.md`

Do not invent a second health system. Do not write meal rows or WHOOP rows here.
