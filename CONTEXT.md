# Health Tracker — CONTEXT

If the task is not health (WHOOP, meals, merge, or habits), go back to `..\ROUTER.md`.

Building-wide rules: `..\AGENTS.md`.

This is a **room** (merge + habit log). WHOOP collection and meal logging are sibling offices, not this folder's job.

## Floor map

| You want to… | Go to | Read first |
|---|---|---|
| Sync WHOOP | `..\whoop-data\` | `..\whoop-data\CONTEXT.md` |
| Log meals / food library | `..\MyFitnessClone\` | `..\MyFitnessClone\CONTEXT.md` |
| Merge sources into the master table | this folder | `README.md` |
| Nightly habit sentence | `habits\` | `habits\README.md` |

## What this is

Joins WHOOP days, meal days, and the habit log into one master table, and holds the nightly habit write.

Upstream:

- WHOOP CSVs: `..\whoop-data\` (read its `CONTEXT.md`)
- Meals: `..\MyFitnessClone\` (read its `CONTEXT.md`)

## Honest status

GitHub Actions for this merge is **not** the daily path. WHOOP already moved local. This repo's Actions were blocked by the same billing hold. Do not re-enable Actions as the daily merge. Work from the local files in this folder and the sibling folders.

There is no local scheduled merge here (no `install-task.ps1` or equivalent). Run the merge from the files in this folder when it is needed.

## Read next

- How the merge works: `README.md`
- Habit log (one sentence a night, blank is not "no"): `habits\README.md`

Do not invent a second health system. Do not write meal rows or WHOOP rows here.
