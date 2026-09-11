# Health Tracker

Joins WHOOP daily rows with meal-dashboard rows into one master table, and
holds the nightly habit log. This folder does not collect WHOOP or log meals.

---

## Daily path (read this first)

The daily merge runs on GitHub Actions and has been landing every day.
`.github/workflows/consolidate.yml` is live: cron `30 13 * * *`, plus
`repository_dispatch` events (`whoop_updated`, `meal_updated`) from the
upstream repos. GitHub queues scheduled runs late, so in practice the commit
lands somewhere between about 16:00 and 19:30 UTC, not at 13:30.

The run does, in order: `fetch_sources.py` (GitHub API fetch of both source
CSVs) → `validate_sources.py` → `consolidate.py` → `generate_audit_report.py`
→ commit `Health_Tracker_Master.csv`, `schema/` and `logs/` as
`github-actions[bot]` with the message
`chore: consolidate health data <date> [scheduled]` → a freshness gate.

The freshness gate runs **after** the commit on purpose. Fresh data lands
first; the gate only turns the run red so a dead upstream stops looking
healthy. A source in `WARN_ONLY_SOURCES` (default: `meal`) warns instead of
failing, so a stale meal source leaves the run green.

Two other machines write to this repo:

- Code-Geeko Nightly, cron `0 6 * * *`, commits `.code-geeko/state.json`.
  See `codegeeko/README.md`.
- The weekly schema integrity check, `.github/workflows/validate_only.yml`,
  cron `0 9 * * 1` (Mondays), commits `schema/` and `logs/` as
  `chore: update schema snapshots [validate-only]`.

Habits are written locally, not by Actions: the Windows task "WHOOP Daily
Sync" runs at 07:00 and writes yesterday's derived habits into `habits.csv`.
See `habits/README.md`.

There is still no local scheduled merge in this folder — no `install-task.ps1`
or equivalent. If you need the master table rebuilt off-cycle, run the merge
scripts here against local source CSVs; check the newest commit first so you
do not redo a merge the bot already ran.

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

- WHOOP: `..\whoop-data\data\daily_consolidated.csv` — current, one day behind
  at most.
- Meals: `..\MyFitnessClone\` (`Meal_Data_Dashboard.csv`) — **frozen since
  2026-07-25.** Nothing has written a meal row since. Every run since the
  freshness gate was added on 2026-08-26 records `"stale_sources": ["meal"]`
  and `"status": "STALE"` in `logs/consolidation_audit.jsonl`, and shows as
  failed in `logs/audit_report.md`. `meal` is warn-only, so the workflow
  itself stays green. Treat a green run as saying nothing about meal
  freshness.

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
├── fetch_sources.py              ← GitHub-API fetch of both source CSVs
├── validate_sources.py
├── generate_audit_report.py
├── habits.py
├── habits.csv                    ← habit log (date-keyed)
├── cross_repo_trigger_setup.md   ← how the upstream repos fire repository_dispatch
├── index.html + dashboard.js     ← local dashboard over the master CSV
│                                   (with vendored chart.umd.min.js, papaparse.min.js)
├── habits\
│   ├── README.md                 ← nightly sentence rules
│   └── definitions.json
├── codegeeko\                    ← nightly repo scan; see codegeeko\README.md
├── .code-geeko\state.json        ← Code-Geeko's seen-findings state
├── schema\
│   ├── daily_consolidated_schema.json
│   └── Meal_Data_Dashboard_schema.json
├── logs\
├── tests\                        ← test_habits.py plus tests\codegeeko\
├── requirements.txt
└── .github\workflows\
    ├── consolidate.yml           ← live daily merge
    ├── code-geeko-nightly.yml    ← live nightly scan
    └── validate_only.yml         ← live weekly schema check
```

---

## logs\

Everything in `logs\` is committed, and nothing prunes it.

| File | Written by | What |
|---|---|---|
| `validation_YYYYMMDD_HHMMSS.log` | `validate_sources.py`, one per run | Per-run validation detail. Both `consolidate.yml` and `validate_only.yml` add to the pile, so the count grows by roughly one a day plus one a week. |
| `consolidation_audit.jsonl` | `consolidate.py`, one line per run | Row/column counts, date ranges, source ages, freshness verdict. This is the file the freshness gate reads. |
| `audit_report.md` | `generate_audit_report.py` | Human-readable version of the newest audit records. |
| `habits_audit.jsonl` | `habits.py`, one line per write | Every habit write, before and after. |

Retention: the two `.jsonl` files and `audit_report.md` are the record and are
kept. The `validation_*.log` files are diagnostic only — nothing reads them
back — so old ones can be deleted whenever the folder gets unwieldy. Their
names are timestamp-first rather than the building's ISO `2026-09-09-` form
because `validate_sources.py` generates them; renaming is a code change, not a
docs change.

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
- The workflows run on Python 3.11 (`requirements.txt`); Code-Geeko runs on
  3.12 with its own `codegeeko/requirements.txt`.
