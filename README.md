# Health Tracker

Joins WHOOP daily rows with meal-dashboard rows into one master table, and
holds the nightly habit log. This folder does not collect WHOOP or log meals.

---

## Daily path (read this first)

GitHub Actions is **not** the daily merge. The same billing hold that stopped
WHOOP's Actions cron also stops this repo's workflows. Do not re-enable
Actions as the daily merge, and do not treat `.github/workflows/consolidate.yml`
as if it were live.

WHOOP already syncs locally in `..\whoop-data\`. Meals live in
`..\MyFitnessClone\`. Work from those sibling folders and the files in this
folder.

**There is no local scheduled merge yet.** This folder has no `install-task.ps1`
(or equivalent). When the master table needs updating, run the merge scripts
here against the local source CSVs.

Nightly habit sentence: `habits\README.md`.

---

## What the merge is

Date-join on `date` (YYYY-MM-DD). One row per calendar date, newest first.
Dates that exist in only one source still appear — the other side is blank.

```
[ All WHOOP columns from daily_consolidated.csv, original order ]
[ 1 blank spacer column                                         ]
[ All meal columns from Meal_Data_Dashboard.csv, original order ]
```

Sources (siblings, not this folder):

- WHOOP: `..\whoop-data\data\daily_consolidated.csv`
- Meals: `..\MyFitnessClone\` (`Meal_Data_Dashboard.csv`)

Output on disk: **`Health_Tracker_Master.csv` at this repo root** (not
`data\Health_Tracker_Master.csv` — there is no `data\` folder).

Scripts write through a staging file, validate, then atomically rename. Column
detection is dynamic; neither source's column names nor positions are
hardcoded.

---

## On disk (what actually exists)

```
Health-Tracker\
├── CONTEXT.md                    ← floor map for agents
├── README.md
├── Health_Tracker_Master.csv     ← merge output (repo root)
├── consolidate.py                ← date-join merge
├── fetch_sources.py              ← GitHub-API fetch (Actions-era; not daily)
├── validate_sources.py
├── generate_audit_report.py
├── habits.py
├── habits.csv                    ← habit log (date-keyed)
├── habits\
│   ├── README.md                 ← nightly sentence rules
│   └── definitions.json
├── schema\
│   ├── daily_consolidated_schema.json
│   └── Meal_Data_Dashboard_schema.json
├── logs\
├── tests\
├── requirements.txt
└── .github\workflows\            ← on disk, blocked; not the daily path
    ├── consolidate.yml
    └── validate_only.yml
```

`fetch_sources.py` still talks to GitHub. For a local merge, copy or point at
the sibling CSVs rather than re-enabling that fetch as a cron.

---

## Habits

One sentence a night. Blank is not "no". Full rules, commands, and derived
sources: **`habits\README.md`**.

Do not write meal rows or WHOOP rows here. Do not invent a second health
system.

---

## Schema resilience

The merge engine does not need a code change when either source adds, removes,
or reorders columns.

| Scenario | Behavior |
|---|---|
| WHOOP gains columns | New columns appear in the output before the spacer |
| Meal data gains columns | New columns appear after the spacer |
| Either file reorders columns | Output keeps each source file's own order |
| New dates in either file | Merged into the output |
| Column removed | Detected and logged; output still valid |

Schema snapshots live in `schema\`. Changes are logged and become the new
baseline. They do not halt the merge.

---

## Architecture notes

- Python standard library for the merge (`csv`, `json`, `pathlib`, `logging`).
  `fetch_sources.py` is the piece that uses `requests` (GitHub fetch).
- Staging file: write `Health_Tracker_Master.staging.csv`, validate, then
  rename. The production file is never partially overwritten.
- The `date` join is the union of all dates, so neither source silently drops
  rows.

---

## Blocked GitHub Actions (do not treat as live)

`.github/workflows\consolidate.yml` still describes a fetch → validate → merge
→ commit cron (13:30 UTC) plus `repository_dispatch` from the sibling repos.
That path is blocked by account billing. WHOOP's local runner does **not**
dispatch here.

Do not set this up again as the daily merge. If billing is ever restored, the
decision is still: WHOOP is local; this merge is not on a local schedule yet.
