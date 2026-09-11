# Health Tracker — CONTEXT

If the task is not health (WHOOP, meals, merge, or habits), go back to `..\ROUTER.md`.

Building-wide rules: `..\AGENTS.md`.

This is a **room** (merge + habit log) with three scheduled machines and one always-on service writing into it. WHOOP collection and meal logging are sibling offices, not this folder's job.

## Floor map

| You want to… | Go to | Read first |
|---|---|---|
| Sync WHOOP | `..\whoop-data\` | `..\whoop-data\CONTEXT.md` |
| Log meals / food library | `..\MyFitnessClone\` | `..\MyFitnessClone\CONTEXT.md` |
| Merge sources into the master table | this folder | `README.md` |
| Habits: what is tracked, the rules, the phone page, the 07:00 fill, the agent fallback | `habits\` | `habits\README.md` |
| Change or redeploy the phone page's Worker | `cloudflare-worker\` | `habits\README.md` (section "Phone page") |
| Code-Geeko nightly repo scan | `codegeeko\` | `codegeeko\README.md` |

## What this is

Joins WHOOP days, meal days and water days into one master table, and holds the habit log (`habits.csv`, its own record, read only by the GTD Year tab).

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
| WHOOP Daily Sync (`..\whoop-data\run-once.ps1`) | Windows task, 07:00 local | `habits.csv`, `logs\habits_audit.jsonl` (the 10 automatic habits for yesterday) | `habits\README.md` |
| Cloudflare Worker `habit-tracker-proxy` (`cloudflare-worker\habits-worker.js`) | Always on; called by the phone page `habits.html` | `habits.csv` (the 11 self-report habits, commit `habits: phone log <date>`) | `habits\README.md` |

## Read next

- How the merge works: `README.md`
- Habit log (phone page, 10 automatic habits, blank is not "no"): `habits\README.md`
- Code-Geeko scan: `codegeeko\README.md`

Do not invent a second health system. Do not write meal rows or WHOOP rows here.
