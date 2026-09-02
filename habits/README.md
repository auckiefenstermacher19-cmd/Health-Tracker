# Habit log

One row per day, date-keyed so it joins to `Health_Tracker_Master.csv`. Grew
out of the `Habit Tracker` tab of `Auckie - 2B.xlsx`, whose March data is
backfilled into it.

## Why it is shaped this way

The spreadsheet died after eight days because it asked for fourteen manual
cells every night. This replaces that with **one sentence a night**, and
answers everything it can without asking at all.

An agent reads `definitions.json`, turns what you said into explicit flags, and
`habits.py` does the validated write. Parsing lives with the agent because
judgement lives there. The script stays dumb on purpose: it validates, it never
guesses.

## The one rule that matters

**Blank is not "no".** A habit nothing could answer stays empty. Only an
explicit "no" records a miss. This is why a quiet night cannot fabricate a
broken streak, why blanks never overwrite a recorded value, and why every
derived source below leaves its habit blank when its data is missing rather
than defaulting to a failure.

## The habit set

**Derived — 7, never asked:**

| Habit | Source | Rule |
|---|---|---|
| Workout (WHOOP) | WHOOP | `workout_count > 0`. A day with cycle data but no workout is a real "no"; no WHOOP row at all stays blank. Lands in `workout_whoop`; `workout` itself is self-reported. |
| Bed on time | WHOOP | `sleep_start` (UTC → local) before `bed_on_time_before`. |
| Slept 7+ hours | WHOOP | light + SWS + REM ≥ `sleep_hours_target`. All three stages required, since a missing one understates the total. |
| Active day | WHOOP | `day_strain` ≥ `active_day_strain_min`. |
| Consistent wake | WHOOP | `sleep_consistency_pct` ≥ `consistent_wake_min_pct`. |
| Logged Food | MyFitnessClone | Any `meal_log.csv` row for the date. That file is the record, not a synced copy, so no rows is a real "did not log". |
| Learning consumed | ai-learning | Any item with `viewed_at` on the date. A `viewed` flag with no stamp does not count. |

**Self-report — 11, the nightly sentence:** made bed, morning vitamins, night
vitamins, shower, teeth, water target, no junk, no fap, read fiction, read
non-fiction, screentime.

**Weekly — asked separately, not nightly:** clean sink, reset house.

**Retired — column and history kept, never asked:** Shower + Teeth.

**Year-plan habits (2026-09-01).** Ticked the next morning on the GTD
dashboard's Year tab, or logged by an agent: devices off by 9pm, reach-out
(text: names), outbound / buyer conversations / public posts (counts),
warning signs (text from a fixed list, `none` to clear). Weekly, typed in the
Sunday review: Sunday review, DJ hour (optional), MRR, body weight, books
finished (running total). `workout` is now self-reported; `workout_whoop`
records what WHOOP saw so the two can disagree visibly. The dashboard never
passes `--whoop`; the 7:00 WHOOP sync step does, and it only fills blanks.

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
self-reported `workout=yes` survives the 7:00 sync even when WHOOP saw no
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
- **Screentime cannot be automated.** Neither iOS Screen Time nor Android
  Wellbeing exports without manual work.

## Agent notes for the nightly check-in

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
| `tests/test_habits.py` | 51 tests, concentrated on midnight, blank-vs-no, the write lock, and each derived source's failure mode. |

Writes go to a per-pid staging file, get validated, then atomically replace
`habits.csv`, matching how `consolidate.py` handles the master CSV. The whole
read-modify-write is held under `habits.lock`.
