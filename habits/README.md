# Habit log

One row per day, 14 habits, carried over from the `Habit Tracker` tab of
`Auckie - 2B.xlsx`. Data lives in `habits.csv` at the repo root, joinable on
`date` with `Health_Tracker_Master.csv`.

## Why it is shaped this way

The spreadsheet died after eight days because it asked for fourteen manual
cells every night. This replaces that with **one sentence a night**. An agent
reads `definitions.json`, turns what you said into explicit flags, and
`habits.py` does the validated write.

Parsing lives with the agent because judgement lives there. The script stays
dumb on purpose: it validates, it never guesses.

## The one rule that matters

**Blank is not "no".** A habit you did not mention stays empty. Only an
explicit "no" records a miss. This is why a quiet night cannot fabricate a
broken streak, and why blanks are never allowed to overwrite a recorded value.

## Commands

Ask WHOOP what it already knows, before asking Auckie anything:

```bash
python habits.py prefill --date today
```

Returns JSON: `known` (what WHOOP answered), `already_logged` (what is already
in the row), `still_unknown` (what to actually ask about), and `notes`
(including a warning when the WHOOP sync has gone stale).

Write a day:

```bash
python habits.py log --date today --whoop --set made_bed=yes --set water=6 --set no_junk=no
```

`--whoop` fills `workout` and `bed_on_time` from WHOOP where you did not give
them. Anything you pass explicitly always wins. Re-running merges into the
existing row rather than replacing it, so corrections and second passes are
safe.

Review:

```bash
python habits.py show --last 7
```

## What WHOOP can and cannot answer

| Habit | Source | How |
|---|---|---|
| Workout | WHOOP | `workout_count > 0`. A day with cycle data but no workout counts as a real "no"; a day with no WHOOP row at all stays blank. |
| Bed on time | WHOOP | `sleep_start`, converted from UTC to local, against `config.bed_on_time_before`. |
| The other 12 | You | No sensor knows whether you made the bed. |

**`bed_on_time_before` currently defaults to 23:30 and is a guess.** Change it
in `definitions.json` to your real target.

Bedtimes straddle midnight, so the comparison folds both times onto an axis
starting at noon. Without that, 00:40 reads as *earlier* than 23:30 and every
late night scores as a win.

## Agent notes for the nightly check-in

- Run `prefill` first. Only ask about `still_unknown`; never re-ask something
  WHOOP or a previous entry already answered.
- `aliases` in `definitions.json` map everyday phrasing to habit ids.
- Two habits are `inverted`: `no_junk` and `no_fap`. "Ate junk" means
  `no_junk=no`. Getting this backwards silently records the opposite of the
  truth, so confirm rather than assume when the phrasing is ambiguous.
- Leave anything genuinely unmentioned out of the command. Do not pass "no"
  to be tidy.

## Files

| Path | What |
|---|---|
| `habits.csv` | The log. Oldest first, one row per date. |
| `habits/definitions.json` | Habit set, order, types, targets, aliases, config. |
| `habits.py` | prefill / log / show. |
| `logs/habits_audit.jsonl` | Every write, with before and after values. |
| `tests/test_habits.py` | 25 tests, mostly on midnight and blank-vs-no. |

Writes go to a staging file, get validated, then atomically replace
`habits.csv`, matching how `consolidate.py` handles the master CSV.
