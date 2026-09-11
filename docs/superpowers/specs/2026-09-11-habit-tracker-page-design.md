# Habit Tracker page — design

Date: 2026-09-11. Status: approved by Auckie in chat, same day.

## What this is

A phone-first web page that logs Auckie's manual daily habits into the
existing record, `habits.csv` in this repo, one question per screen with
a green Yes tile and a red No tile. It is a front end for the habit engine
that already exists here (`habits.py`, `habits/definitions.json`); it is
not a second habit system.

Live URL once merged: `https://auckiefenstermacher19-cmd.github.io/Health-Tracker/habits.html`
(this repo already serves GitHub Pages from `main`, root).

## Why it is shaped this way

- The spreadsheet tab (`Auckie - 2B.xlsx`, all versions carry the same 14
  habits) died after 8 days because it asked for 14 cells a night. The
  one-sentence agent flow replaced it, but still needs a laptop and an
  agent. The tile flow is the lowest-friction path: eleven taps on the phone.
- Everything a machine can answer is never asked. Today 7 habits are
  derived. This build adds 3 more (water, workout from the Workout
  Tracker, calories on target) so the phone flow is 11 binary questions.
- Storage stays git-backed CSV, same as the food, water and workout
  trackers. A Cloudflare Worker holds the GitHub token, same as the
  Workout Tracker, so the phone never holds a credential.

## The habit set after this build

Source of truth is `habits/definitions.json`. The page reads it and asks
exactly the habits marked for the phone; no habit list is hard-coded in
the page.

Phone flow, in this order (all `type: binary`, `source: self`,
`phone_order` 1..11):

1. made_bed "Made your bed?"
2. morning_vitamins "Morning vitamins?"
3. shower "Showered?"
4. teeth "Brushed your teeth?"
5. night_vitamins "Night vitamins?"
6. no_junk "Stayed off junk food?"
7. no_fap "Stayed clean? (no fap)"
8. read_fiction "Read fiction?"
9. read_nonfiction "Read non-fiction?"
10. devices_off_9pm "Devices off by 9pm?"
11. screentime "Screentime under 2 hours?"

Each habit gets a `question` field in definitions.json holding the text
above. `screentime` changes from `type: hours` to `type: binary` (zero
entries exist, nothing is lost); its `target`/`direction` fields are
removed and its label becomes "Screentime under 2h".

Derived, never asked:

- Existing: bed_on_time, slept_7h, active_day, consistent_wake,
  workout_whoop (WHOOP); logged_food (meal log); learning_consumed
  (ai-learning item status).
- New `water`: `source` stays `self`, and a new `auto_source` field carries
  `water_dashboard`. Rule: the row for the date in
  `MyFitnessClone/Water_Data_Dashboard.csv` has
  `water_fl_oz >= water_goal_fl_oz` -> yes; a row under goal -> no; no
  row -> blank.
- New `workout`: `source` stays `self`, `auto_source` is `workout_log`.
  Rule: any row in `Workout-Tracker-v2/workout_tracker.csv` whose `Date`
  equals the date -> yes. Otherwise blank (never no: an unlogged run is
  not a missed workout; `workout_whoop` still records WHOOP's view). A
  stored value is never overwritten, so a hand-set `workout=yes` survives.

  Why `auto_source` rather than moving `source`: the GTD dashboard's Year
  tab renders every habit whose `source` is not `self` as a read-only
  "· WHOOP" row, so flipping these two would have taken away the tick box
  Auckie uses to correct them.
- New `calories_on_target` (new column, appended after `books_finished`
  and before `logged_at`): source `meal_dashboard`. Rule: row for the
  date in `MyFitnessClone/Meal_Data_Dashboard.csv` with
  `calories_actual` within `calorie_tolerance_pct` (10) of
  `calories_goal` -> yes; a row outside -> no; no row or blank goal ->
  blank. Known: the meal log has been stale since 2026-07-25, so this
  stays blank until food is logged again.

Not on the phone, unchanged: reach_out, outbound, conversations, posts,
warning_signs (GTD Year tab) and every `cadence: weekly` habit (Sunday
review). Retired `shower_teeth` stays retired.

Source fetching for the three new derivations: each has a list of
sources in `config`; entries that start with `http` are fetched with
`urllib` (10 s timeout), others are paths relative to this repo. First
source that answers wins. Any failure leaves the habit blank and adds a
note. Defaults:

- `water_dashboard_sources`: raw GitHub URL of
  `MyFitnessClone/main/Water_Data_Dashboard.csv`, then
  `../MyFitnessClone/Water_Data_Dashboard.csv`.
- `workout_log_sources`: raw GitHub URL of
  `Workout-Tracker-v2/main/workout_tracker.csv` (no local checkout).
- `meal_dashboard_sources`: raw GitHub URL of
  `MyFitnessClone/main/Meal_Data_Dashboard.csv`, then
  `../MyFitnessClone/Meal_Data_Dashboard.csv`.

Raw URLs are used because the local sibling checkouts are only as fresh
as the last time someone pulled them; the raw URL is always current for
a public repo.

## Files

All in this repo unless stated.

| Path | What |
|---|---|
| `habits.html` | The page. Home, wizard, done and edit views in one file; inline CSS and JS, no framework, no build step. |
| `habits-core.js` | Pure functions shared by page and tests: CSV parse/serialize, row upsert, question selection, draft state. No DOM, no fetch. Loaded by a `<script>` tag and by `node --test`. |
| `habits-config.js` | `HABITS_WORKER_URL` only. No secrets. |
| `habits.webmanifest`, `habits-icon-192.png`, `habits-icon-512.png` | Add-to-home-screen. Same shape as `MyFitnessClone/water.webmanifest`. Icon made by `tools/make_habits_icon.py` (Pillow), a checkmark on the accent colour. |
| `cloudflare-worker/habits-worker.js` | Worker source, deployed by Auckie to Cloudflare, never to Pages. |
| `tools/dev_worker.py` | Local stand-in for the Worker for browser testing: serves the repo folder as static files and the `/habits` endpoints against a scratch copy of `habits.csv`. Never touches the real file. |
| `tests/habits-core.test.js` | `node --test` suite for `habits-core.js`. |
| `tests/test_habits.py` | Existing suite, extended for the three new derivations and the new column. |
| `habits/definitions.json` | Changes listed above. |
| `habits.py` | Three new prefill functions and a source fetcher. |
| `habits/README.md` | Updated habit table and the phone write path. |
| `../whoop-data/run-once.ps1` | Pull before the habits step (see Concurrency). |

## The Worker

Copy of the Workout Tracker worker with these endpoints:

- `GET /habits` -> `{ content, sha }` of `habits.csv` (authenticated read,
  always current; Pages caching is not acceptable for read-before-write).
- `PUT /habits` body `{ content, sha, message }` -> writes `habits.csv`
  on `main`. Relays GitHub's status, so a stale sha comes back as 409.
- `GET /raw/definitions` -> text of `habits/definitions.json`.
- `OPTIONS` for CORS. `Access-Control-Allow-Origin` = `ALLOWED_ORIGIN`.

Cloudflare settings: `GITHUB_PAT` (secret), `GITHUB_OWNER` =
`auckiefenstermacher19-cmd`, `GITHUB_REPO` = `Health-Tracker`,
`ALLOWED_ORIGIN` = `https://auckiefenstermacher19-cmd.github.io`.
Worker name `habit-tracker-proxy`; its URL goes in `habits-config.js`.

## The page

Design tokens copied from `MyFitnessClone/Water_Log.html` (dark
background `#0f1117`, surface `#1a1d27`, border `#2a2d3a`, text
`#e8eaf0`, muted `#7a7f94`, error `#f87171`, radius 10px, system font).
Accent for this app: `--accent: #a78bfa` (violet), `--accent-dim:
#2e2452`. Yes tile `#22c55e` on `#14331f`; No tile `#ef4444` on
`#3a1717`. Card max-width 420px. PWA meta tags identical to the water
page. Title "Habits".

Views (one visible at a time, no scrolling needed on a phone):

**Home.** Date input, default today in device-local time. Under it a
status line: "Not logged yet" or "Logged at 10:12 pm" (from `logged_at`)
or "Loading…". One large button: "Log habits" when the date has no
`logged_at`, "Edit habits" otherwise. Small footer link to the Health
dashboard (`index.html`). On load the page fetches definitions and the
CSV once; `visibilitychange` refetches.

**Wizard.** Progress text "3 of 11". Question in large type. Two tiles
filling the width, stacked, each at least 120px tall: Yes (green), No
(red). Under them a small muted "skip" link. Tap: the chosen tile fills
solid, a check (or cross) mark scales in over ~250ms, then the next
question slides in from the right (~200ms). Skip records blank, never
no. Back arrow returns to the previous question and keeps its answer.
Answers accumulate in memory and in `localStorage` under
`habits_draft_<date>` so closing the app mid-way resumes where it left
off. Nothing is written to GitHub until the last question.

**Saving.** After the last question: read `{content, sha}`, upsert the
row for the date (create it with `day_of_week` if absent, keep every
other column as is, set only answered habits, stamp `logged_at` with the
device time as ISO 8601 with offset, leave `note` alone), serialize, PUT
with commit message `habits: phone log <date>`. On 409, refetch and
retry once. Then show **Done**: big check, "Habits tracked for
September 11", button "Back". Draft cleared. On failure: toast with the
error, draft kept, button "Retry".

**Edit.** For a logged date: a list of the 11 phone habits, each a row
with the label and a three-way pill (Yes / No / blank). Below, read-only
rows for the derived habits with their current value or "—" (so the
morning's automatic answers are visible). Changing a pill saves
immediately with the same upsert (one commit per change, message
`habits: phone edit <date> <habit>=<value>`), serialized through a
promise queue so two quick taps never race. `logged_at` is re-stamped
on each edit.

Writes never reorder columns and never touch columns the page does not
know. Rows are sorted oldest first. Output is LF line endings, UTF-8, no
BOM, trailing newline, minimal quoting (quote only fields containing a
comma, quote, or newline; double inner quotes) — byte-identical to what
Python's `csv` writer produces after git's LF normalization.

Blank is never "no": skip and the blank pill both store an empty field.

No offline mode. If the Worker is unreachable the home screen says so
and the wizard still runs; the save fails with a Retry button and the
draft survives.

## Concurrency: three writers, one file

- Phone: read sha then PUT; 409 -> refetch, re-upsert, retry once, then
  surface the error.
- 07:00 WHOOP sync (`whoop-data/run-once.ps1`): today it writes
  `habits.py log --whoop` on whatever the local checkout has, commits,
  then pulls with rebase. If the phone changed the same day's row the
  night before, that rebase conflicts on the line and the morning data
  is stranded locally (exit 2). Change: before running `habits.py`, run
  `git pull --rebase --autostash` in Health-Tracker; if that fails, log
  `habits: PULL FAILED` and skip the habits step with exit 2. After
  writing, keep the existing commit + pull + push. With the pull first,
  the two writers only clash in the seconds between pull and push.
- GTD dashboard (Year tab) writes through `habits.py` on this machine
  without committing; the 07:00 step commits it. Its ticks land after
  07:00, after the pull, so they rebase cleanly. Residual risk accepted:
  the Year tab reads the local file, which is behind the phone's writes
  until the next 07:00 pull.
- The `note` column and `logs/habits_audit.jsonl` are not written by the
  phone. The commit message is the phone's audit trail; the README says
  so.

## Testing

- `node --test tests/habits-core.test.js`: CSV round-trip is
  byte-identical on the real `habits.csv` fixture (LF form); upsert
  creates and updates rows, keeps unknown columns, sorts by date, sets
  `day_of_week`; quoting of commas/quotes; question selection honours
  `phone_order`, `active: false`, `cadence: weekly`; draft resume.
- `pytest tests/test_habits.py`: each new derivation's yes/no/blank
  cases, source fallback from URL to local path, fetch failure leaves
  blank with a note, new column appears in the header in the right
  place, existing rows still round-trip.
- Browser: run `tools/dev_worker.py`, open `habits.html`, drive the full
  wizard with Playwright at 375x812: 11 questions, one skip, done screen,
  reopen the date -> edit view shows the answers, flip one, scratch CSV
  reflects exactly the expected bytes. Also: quit mid-wizard, reload,
  resumes at the same question. Screenshot each view for Auckie.
- Live: after Auckie deploys the Worker and the config commit lands,
  log a real day from the phone and confirm the commit on GitHub.

## Out of scope

Streaks, scoring, charts (the Health dashboard and GTD Year tab own
that). Weekly habits and year-plan counters on the phone. Offline
queueing. Automating screentime (iOS offers no export).
