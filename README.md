# Health Tracker

A centralized health-data consolidation platform that automatically merges
WHOOP biometric data with nutrition tracking data into a single master CSV.

---

## What This Repository Does

Every day, this repository:

1. **Fetches** the latest `daily_consolidated.csv` from the `whoop-data` repository
2. **Fetches** the latest `Meal_Data_Dashboard.csv` from the `MyFitnessClone` repository
3. **Validates** both files for integrity and schema changes
4. **Merges** them into `data/Health_Tracker_Master.csv`
5. **Commits** the result back to this repository automatically

### Output Layout

```
[ All WHOOP columns (70 cols, newest first) ]
[ 1 blank spacer column                     ]
[ All Meal columns (131 cols)               ]
```

Total: **202 columns**, one row per calendar date, newest date first.

The merge is **date-joined** on the `date` column (YYYY-MM-DD).  Dates that
exist in only one source still appear in the output — the other side is blank.

---

## Repository Structure

```
health-tracker/
├── .github/
│   └── workflows/
│       ├── consolidate.yml       ← Main workflow: fetch → validate → merge → commit
│       └── validate_only.yml     ← Standalone validation + weekly schema check
│
├── scripts/
│   ├── fetch_sources.py          ← Downloads both source CSVs via GitHub API
│   ├── validate_sources.py       ← Schema detection, integrity checks, audit logs
│   ├── consolidate.py            ← Core merge engine (schema-resilient)
│   └── generate_audit_report.py ← Produces Markdown audit summary
│
├── data/
│   ├── Health_Tracker_Master.csv ← ⭐ The consolidated output (auto-updated)
│   ├── raw/                      ← Temporary downloaded source files (git-ignored)
│   └── schema/
│       ├── daily_consolidated_schema.json    ← Schema snapshot for change detection
│       └── Meal_Data_Dashboard_schema.json   ← Schema snapshot for change detection
│
├── logs/
│   ├── consolidation_audit.jsonl ← Append-only machine-readable audit log
│   └── audit_report.md           ← Human-readable audit report (auto-generated)
│
├── docs/
│   └── cross_repo_trigger_setup.md  ← How to wire up upstream dispatch triggers
│
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Setup Instructions

### Prerequisites

- A GitHub account
- Access to both source repositories (`whoop-data` and `MyFitnessClone`)
- A GitHub Personal Access Token (PAT) with Contents read permission on both repos

---

### Step 1 — Create This Repository

1. Go to https://github.com/new
2. Repository name: `health-tracker`
3. Set to **Private**
4. Do NOT initialize with a README (you'll push the code)
5. Click **Create repository**

---

### Step 2 — Push the Code

Clone this project locally and push to your new repo:

```bash
git clone https://github.com/YOUR_USERNAME/health-tracker.git
cd health-tracker
# copy all files into this folder
git add .
git commit -m "Initial Health Tracker setup"
git push
```

---

### Step 3 — Create a GitHub Personal Access Token

This PAT allows the consolidation workflow to read files from your private
`whoop-data` and `MyFitnessClone` repositories.

1. Go to: https://github.com/settings/tokens?type=beta
2. Click **Generate new token**
3. Name: `health-tracker-reader`
4. Repository access: Select **both** `whoop-data` and `MyFitnessClone`
5. Permissions:
   - **Contents** → Read-only
6. Generate and copy the token

---

### Step 4 — Add Secrets and Variables to This Repository

Go to your `health-tracker` repository:
**Settings → Secrets and variables → Actions**

#### Repository Secrets (encrypted):

| Secret Name | Value |
|---|---|
| `GH_PAT` | The PAT you created in Step 3 |
| `GH_USERNAME` | Your GitHub username (e.g. `johndoe`) |

#### Repository Variables (not encrypted — these are configuration, not credentials):

**Settings → Secrets and variables → Actions → Variables tab**

| Variable Name | Value |
|---|---|
| `WHOOP_REPO` | `whoop-data` |
| `MEAL_REPO` | `MyFitnessClone` |

> If your repos use different names, update these variables accordingly.

---

### Step 5 — Run the Workflow Manually to Test

1. Go to your repository on GitHub
2. Click the **Actions** tab
3. Click **"Health Tracker Consolidation"** in the left sidebar
4. Click **"Run workflow"** → **"Run workflow"**
5. Wait ~30 seconds for it to complete

If successful, you will see `data/Health_Tracker_Master.csv` appear in your
repository with all rows merged.

---

### Step 6 (Optional) — Set Up Cross-Repo Triggers

For real-time consolidation whenever either source repo updates, follow the
instructions in `docs/cross_repo_trigger_setup.md`.

Without this step, consolidation still runs daily at 13:30 UTC automatically.

---

## Automation Schedule

| Trigger | When | Description |
|---|---|---|
| `repository_dispatch: whoop_updated` | After WHOOP sync completes | Fires within minutes of new WHOOP data |
| `repository_dispatch: meal_updated` | After meal dashboard regenerates | Fires when meal log is updated |
| `schedule` | 13:30 UTC daily | Guaranteed daily fallback |
| `workflow_dispatch` | Manual | Run on demand from Actions tab |
| `validate_only` schedule | 09:00 UTC every Monday | Weekly schema integrity check |

---

## Schema Resilience

The consolidation engine is fully schema-resilient.  **No code changes are
required** when either source file changes its column structure.

| Scenario | Behavior |
|---|---|
| WHOOP gains 10 new columns | Detected automatically; new columns appear in output before spacer |
| Meal data gains new columns | Detected automatically; new columns appear after spacer |
| Either file reorders columns | Handled — output preserves each source file's own ordering |
| New dates added to either file | Merged automatically into output |
| Column removed from either file | Detected and logged; output still valid |

Schema changes are:
1. Detected by comparing the live header against the saved snapshot in `data/schema/`
2. Logged prominently in the workflow output
3. Automatically saved as the new baseline snapshot
4. **Never halt the consolidation** (advisory warnings only)

---

## Output File Reference

**`data/Health_Tracker_Master.csv`**

- One row per calendar date
- Sorted newest date first (matching WHOOP's ordering convention)
- Column layout:

```
Columns 1–70    : WHOOP daily_consolidated columns (in original order)
Column 71       : [blank spacer]
Columns 72–202  : Meal_Data_Dashboard columns (in original order)
```

### WHOOP Section (columns 1–70)

Includes 10 insight sections separated by internal blank spacers:
Recovery → Sleep → Cycle → Workouts → Calories → Readiness →
Sleep Debt → Strain-Recovery → CV Fitness → Energy Balance

### Meal Section (columns 72–202)

Includes 10 nutritional sections separated by internal blank spacers:
Date → Calories Total → Calories by Meal → Calories % by Meal →
Macros Total → Macros % of Goal → Macros by Meal →
Micros Total → Micros % of Goal → Micros by Meal

---

## Troubleshooting

### "404 Not Found" during fetch

- Verify `GH_USERNAME`, `WHOOP_REPO`, and `MEAL_REPO` are set correctly
- Verify `GH_PAT` has Contents read access to both repos
- Verify the source file paths have not changed in the upstream repos

### "Schema change detected" warning

- This is informational, not an error
- The consolidation still runs successfully
- Review the added/removed columns in the workflow log
- No action required unless you want to understand what changed

### "Post-write validation FAILED"

- This is a hard error — the staging file did not pass sanity checks
- The existing `Health_Tracker_Master.csv` is NOT overwritten
- Check the workflow log for the specific mismatch (row count, column count)
- Re-run the workflow once the root cause is identified

### Workflow runs but no changes committed

- Both source files are unchanged since the last run
- This is expected behavior — the commit step skips if output is identical

### Cross-repo dispatch not firing

- Verify `HEALTH_TRACKER_DISPATCH_TOKEN` secret is set in both upstream repos
- The 13:30 UTC scheduled run will still consolidate daily

---

## Maintenance

### Adding a new source repository

1. Add a new fetch target in `scripts/fetch_sources.py`
2. Add its schema tracking in `scripts/validate_sources.py`
3. Add the new columns to the merge logic in `scripts/consolidate.py`
4. Add the new repo name as a GitHub Variable

### Changing source repository names

Update the GitHub Variables (`WHOOP_REPO` or `MEAL_REPO`) in Settings.
No code changes needed.

### Viewing the audit trail

- **Machine-readable:** `logs/consolidation_audit.jsonl`
- **Human-readable:** `logs/audit_report.md`
- **Per-run detail:** GitHub Actions → individual run logs

---

## Architecture Notes

- Python standard library only (csv, json, pathlib, logging) — no pandas dependency.
  This makes the scripts fast, portable, and dependency-free beyond `requests`.
- Staging file pattern: output is written to `.staging.csv`, validated, then
  atomically renamed. The production file is never partially overwritten.
- All column detection is dynamic — no column names or positions are hardcoded.
- The `date` join uses a left-outer merge from the union of all dates, so
  no rows from either source are ever silently dropped.
