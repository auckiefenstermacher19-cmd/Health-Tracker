# Habit log

One row per day in `habits.csv`, date-keyed. Grew out of the `Habit Tracker`
tab of `Auckie - 2B.xlsx`, whose March data is backfilled into it.

This file is the only record. Exactly one thing reads it: the GTD dashboard's
Year tab scoreboard, from the copy on this PC. It does not feed
`Health_Tracker_Master.csv` or the health dashboard.

## Why it is shaped this way

The spreadsheet died after eight days because it asked for fourteen manual
cells every night. Now a machine answers everything it can (10 habits, filled
at 07:00 the next morning), and the rest is **eleven yes/no taps on the
phone** (`habits.html`, see "Phone page" below).

Fallback when the phone was not used: an agent reads `definitions.json`,
turns one spoken sentence into explicit flags, and `habits.py` does the
validated write. Parsing lives with the agent because judgement lives there.
The script stays dumb on purpose: it validates, it never guesses.

Log at night. Two questions (devices off by 9pm, screentime) cannot be
answered before bedtime; logging earlier means editing later.

## The one rule that matters

**Blank is not "no".** A habit nothing could answer stays empty. Only an
explicit "no" records a miss. This is why a quiet night cannot fabricate a
broken streak, why blanks never overwrite a recorded value, and why every
derived source below leaves its habit blank when its data is missing rather
than defaulting to a failure.

## What writes here without you

The Windows scheduled task **"WHOOP Daily Sync"** (07:00 local) writes
yesterday's derived habits into this repo. Nothing in this folder starts it.

- Entry point: `..\whoop-data\run-once.ps1`, launched hidden by
  `..\whoop-data\run-hidden.vbs`. The habits step is the last section of that
  script, after the WHOOP sync itself.
- Interpreter: `..\whoop-data\.venv\Scripts\python.exe` — the *sibling's*
  venv, not anything in this repo.
- Sequence, in this order. Three writers share this file (the phone commits
  to the remote at night, the GTD Year tab writes the local copy without
  committing, this step writes the local copy at 07:00), so the order is
  what keeps them from colliding:
  1. Commit any uncommitted `habits.csv` / `logs/habits_audit.jsonl` left by
     the Year tab, as `habits: dashboard ticks before <date>`.
  2. `git pull --rebase --autostash`, so the phone's row from last night is
     on disk before anything is written. If the rebase fails it is aborted,
     the tree is left clean, and the step stops.
  3. `habits.py log --date <yesterday> --whoop --tz America/New_York`, with
     yesterday computed in Eastern. `--whoop` fills blanks only: it never
     overwrites a stored value, never stamps `logged_at`, and does not rewrite
     the file at all when there is nothing to change.
  4. Commit scoped to those two files as `habits: log through <date>`, pull
     with rebase once more, push.

Failure signal: `..\whoop-data\state\local-run.log`. Habits lines are
prefixed `habits:`; the last line of the run names the stage that failed.

- `run end (exit 2) - WHOOP synced; habits step FAILED (pre-pull failed)` or
  `(dashboard-ticks commit failed)` — nothing was written; yesterday's derived
  habits are missing and the tree is clean. Run the step by hand after a
  `git pull`.
- `habits: derived-habit step FAILED` — the WHOOP sync itself succeeded;
  nothing was written and nothing is stranded.
- `... habits step FAILED (commit failed)`, `(pull failed)` or `(push failed)`
  — yesterday's habits exist **only on this disk** until someone pushes.
- No `run end` line for the day at all — the task did not run, and yesterday
  has no derived habits.

## The habit set

**Derived — 10, never asked on the phone:**

| Habit | Source | Rule |
|---|---|---|
| Workout (WHOOP) | WHOOP | `workout_count > 0`. A day with cycle data but no workout is a real "no"; no WHOOP row at all stays blank. Lands in `workout_whoop`; `workout` itself is derived from the Workout Tracker (see below). |
| Bed on time | WHOOP | `sleep_start` (UTC → local) before `bed_on_time_before`. |
| Slept 7+ hours | WHOOP | light + SWS + REM ≥ `sleep_hours_target`. All three stages required, since a missing one understates the total. |
| Active day | WHOOP | `day_strain` ≥ `active_day_strain_min`. |
| Consistent wake | WHOOP | `sleep_consistency_pct` ≥ `consistent_wake_min_pct`. |
| Logged Food | MyFitnessClone | Any `meal_log.csv` row for the date. That file is the record, not a synced copy, so no rows is a real "did not log". |
| Learning consumed | ai-learning | Any item with `viewed_at` on the date. A `viewed` flag with no stamp does not count. |
| Water target | Water dashboard (`auto_source`) | Day total in `Water_Data_Dashboard.csv` ≥ `water_goal_fl_oz` → yes; a row under goal → no; no row → blank. Auto-filled when blank; still tickable on the Year tab. |
| Workout | Workout Tracker (`auto_source`) | Any row in `workout_tracker.csv` for the date → yes, otherwise blank, never no — an unlogged day is not a missed workout. WHOOP's view lands separately in `workout_whoop`, so the two can disagree visibly. Auto-filled when blank; still tickable on the Year tab. |
| Calories on target | MyFitnessClone | `calories_actual` within `calorie_tolerance_pct` (10%) of `calories_goal` in `Meal_Data_Dashboard.csv` → yes; outside → no; no row or blank goal → blank. A day with no food logged stays blank. |

`water` and `workout` keep `source: self` and name their feed in
`auto_source`, because the GTD Year tab renders anything whose `source` is not
`self` as a read-only row and these two still need a tick box. They are
deliberately asymmetric: water records a real "no" when the water page has a
row under goal, while workout stays blank when nothing is logged, because an
unlogged run is not a missed workout.

**Self-report — 11, the phone page, in this order:** made bed, morning
vitamins, shower, teeth, night vitamins, no junk, no fap, read fiction, read
non-fiction, devices off by 9pm, screentime.

**Screentime is a yes/no, defined by an iOS App Limit, not a number.** Auckie
sets a single 2-hour App Limit in iOS Screen Time on the apps that count as
phone time. Clock, Spotify and the Workout Tracker are left out of the limit,
so gym use never counts. The question "Stayed under the 2-hour app limit?"
is answered by whether the "Limit reached" wall was hit that day. Apple's
own Screen Time total cannot be exported (encrypted, no API, no Shortcuts
action), so this is the accurate manual form. Decided 2026-09-11.

**Weekly — asked separately, not nightly:** clean sink, reset house.

**Retired — column and history kept, never asked:** Shower + Teeth.

**Year-plan habits (2026-09-01).** Ticked the next morning on the GTD
dashboard's Year tab, or logged by an agent: reach-out (text: names),
outbound / buyer conversations / public posts (counts), warning signs (text
from a fixed list, `none` to clear). Devices off by 9pm is now phone question
10 as well, and remains tickable on the Year tab. Weekly, typed in the Sunday
review: Sunday review, DJ hour (optional), MRR, body weight, books finished
(running total). `workout` is auto-filled from the Workout Tracker (any set
logged that day) and still tickable there; `workout_whoop` records what WHOOP
saw so the two can disagree visibly, and a hand-set `workout` value is never
overwritten. The dashboard never passes `--whoop`; the 7:00 WHOOP sync step
does, and it only fills blanks.

## What `logged_at` means

`logged_at` means a human or an explicit caller wrote something; derived-only
runs never stamp it. A `log` call carrying `--set`, `--json`, or `--note`
stamps the column, even if every value already matched what was stored — you
still said it. A `--whoop`-only run does not, no matter how many derived
habits it fills, and when such a run has nothing to change it does not rewrite
`habits.csv` at all. The dashboard reads this column to tell "yesterday is
untouched" from "yesterday was ticked", so a 7:00 sync stamping it would
report every quiet day as done.

Writes take `habits.lock` and retry the final rename; another writer holding
the lock for over 60 s is treated as dead. Days resolve in `America/New_York`
(`--tz` to override).

## Current thresholds

Set in `definitions.json`. All are judgement calls, not physics:

| Setting | Value | Why |
|---|---|---|
| `bed_on_time_before` | 22:00 | From a 05:30 wake. WHOOP's `sleep_start` is when sleep began, so this is "asleep by 10", not "in bed by 10". |
| `sleep_hours_target` | 7.0 | **Stricter than current reality** — the median since June is 6.66h, so expect early "no"s. |
| `active_day_strain_min` | 6.0 | Median day is 4.28, max 13.5. |
| `consistent_wake_min_pct` | 70 | WHOOP's own consistency measure. |

## Phone page

Live at `https://auckiefenstermacher19-cmd.github.io/Health-Tracker/habits.html`
(GitHub Pages serves `main`; added to the iPhone home screen as "Habits").
`habits.html` asks the 11 self-report habits one per screen and writes the
row through the Cloudflare Worker `habit-tracker-proxy` (source in
`cloudflare-worker/habits-worker.js`, deployed 2026-09-11; the GitHub token
lives only in Cloudflare as the secret `GITHUB_PAT`). It stamps `logged_at`,
never touches `note` or the audit log: the commit message
`habits: phone log <date>` is its audit trail. Skip leaves a blank, never a
no. Already-logged days open an edit list; each flip is its own commit,
`habits: phone edit <date> <habit>=<value>`.

Redeploying the Worker: edit `habits-worker.js`, then from
`cloudflare-worker\` run `wrangler.cmd deploy` (Wrangler is installed and
logged in on this PC; `wrangler.toml` holds the three plain settings).
Rotating the token is Auckie's job: `wrangler.cmd secret put GITHUB_PAT`
in the same folder, then paste. Scripts that call the Worker must send a
browser-style `User-Agent`; Cloudflare's bot filter returns 403 to Python's
default one.

Accepted risk: the Worker URL is public and unauthenticated. `ALLOWED_ORIGIN`
is a CORS restriction, which only browsers honour, so anyone who learns the URL
could `curl` a write into `habits.csv`. That is the deal being taken knowingly:
git history holds every version, a bad commit is a one-line revert, and the
token itself never leaves Cloudflare. Same trade-off as the Workout Tracker.

Local testing: `python tools/dev_worker.py` serves the page and a scratch
copy of `habits.csv` at http://127.0.0.1:8765/habits.html.

Concurrency: the phone commits to the remote; the 07:00 WHOOP step pulls
Health-Tracker before writing derived habits, then commits and pushes.
The GTD Year tab reads the local file, so it lags the phone until 07:00.

## Commands

Ask every source what it already knows, before asking Auckie anything:

```bash
python habits.py prefill --date today
```

Returns `known` (what was derived), `already_logged`, `still_unknown` (what to
actually ask about — retired and weekly habits are excluded), and `notes`,
including a warning when the WHOOP sync has gone stale.

Write a day:

```bash
python habits.py log --date today --whoop --set made_bed=yes --set water=yes --set no_junk=no
```

`--whoop` fills blanks only: a derived habit that already has a stored value
keeps it, and anything you pass on the command line wins outright. So a
hand-set `workout=yes` survives the 7:00 sync even when WHOOP saw no
workout - WHOOP's answer lands in `workout_whoop` and the two disagree in
public. Re-running merges into the existing row, so corrections and second
passes are safe.

Review:

```bash
python habits.py show --last 7
```

## Design decisions worth remembering

- **Shower + Teeth was split** because it asked two questions in one cell and
  scored *no* on 6 of 8 days. The old column is retired rather than deleted:
  its history is real and cannot be un-merged into two answers.
- **Water became a yes/no.** It and Screentime were the only numeric habits and
  both have zero entries in their entire life. A number you have to recall is
  the highest-friction question there is.
- **Clean Sink and Reset House went weekly** for the same reason: never filled
  once. Asking nightly and getting blanks trains you to ignore the prompt.
- **Screentime cannot be automated, so an App Limit defines it (2026-09-11).**
  Apple's Screen Time total is encrypted with no export, no API and no
  Shortcuts action. Per-app open/close Shortcuts automations posting to the
  Worker were evaluated and declined: they need every app listed by name,
  miss the phone being locked mid-app, and sometimes do not fire. A 2-hour
  iOS App Limit on the counted apps (gym apps excluded) turns the question
  into one Auckie can answer without guessing.
- **Screentime became yes/no for the phone page.** Same reasoning as
  water: a number you have to recall is the highest-friction question
  there is, and the phone flow needed a binary tile either way.
- **Water and workout became derived.** Both already have their own
  trackers (the water page, the Workout Tracker) with a daily CSV; asking
  again at night was asking Auckie to remember what a machine already
  recorded. Workout stays blank rather than no when nothing is logged,
  since an unlogged day is not proof a workout was missed.

## Agent notes for the nightly check-in (fallback when the phone was not used)

- Check `habits.csv` on the remote first: a row with `logged_at` for the date
  means the phone already did the job. Do not ask again.
- Run `prefill` first. Only ask about `still_unknown`; never re-ask something a
  source or a previous entry already answered.
- `aliases` in `definitions.json` map everyday phrasing to habit ids.
- Two habits are `inverted`: `no_junk` and `no_fap`. "Ate junk" means
  `no_junk=no`. Getting this backwards silently records the opposite of the
  truth, so confirm rather than assume when phrasing is ambiguous.
- Leave anything genuinely unmentioned out of the command. Do not pass "no" to
  be tidy.

## Files

| Path | What |
|---|---|
| `habits.csv` | The log. Oldest first, one row per date. |
| `habits/definitions.json` | Habit set, order, types, sources, thresholds, aliases. |
| `habits.py` | prefill / log / show. |
| `logs/habits_audit.jsonl` | Every write, with before and after values. |
| `habits.html` | The phone page: home, wizard, done and edit views. GitHub Pages. |
| `habits-core.js` | Pure functions shared by the page and its tests: CSV parse/serialize, row upsert, question selection, draft state. |
| `habits-config.js` | The Worker URL. No secrets. |
| `tools/dev_worker.py` | Local stand-in for the Worker: serves the page and a scratch copy of `habits.csv` for browser testing. Never touches the real file. |
| `tests/habits-core.test.js` | `node --test` suite for `habits-core.js`, 10 tests. |
| `tests/test_habits.py` | 80 tests, concentrated on midnight, blank-vs-no, the write lock, and each derived source's failure mode. |

Writes go to a per-pid staging file, get validated, then atomically replace
`habits.csv`, matching how `consolidate.py` handles the master CSV. The whole
read-modify-write is held under `habits.lock`.
