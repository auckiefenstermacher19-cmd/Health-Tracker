# Habit Tracker Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A phone web page at `Health-Tracker/habits.html` that asks Auckie's 11 manual habits one per screen (green Yes / red No tiles) and writes the answers into the existing `habits.csv` through a Cloudflare Worker; plus three new automatic habit derivations in `habits.py`.

**Architecture:** Static HTML page on GitHub Pages (already enabled for this repo) reads `habits/definitions.json` for the question list and reads/writes `habits.csv` through a Worker that holds the GitHub token. Pure CSV/upsert logic lives in `habits-core.js` and is unit-tested with `node --test`. Python derivations extend `habits.py` and are tested with pytest. A local `tools/dev_worker.py` stands in for the Worker so the page can be driven in a browser without touching the real file.

**Tech Stack:** Vanilla HTML/CSS/JS (no framework, no build), Node 24 `node --test`, Python 3 stdlib + pytest, Cloudflare Workers, GitHub Contents API, Pillow for the icon.

**Spec:** `docs/superpowers/specs/2026-09-11-habit-tracker-page-design.md` — read it first; every task argues from it.

## Global Constraints

- Repo: `C:\Users\Auckie\workspaces\Health-Tracker` (git remote `auckiefenstermacher19-cmd/Health-Tracker`, branch `main`). Shared tree: commit with explicit pathspecs only, never `git add -A` or `git add .`.
- `habits.csv` written by the page must be: UTF-8, no BOM, LF line endings, trailing newline, minimal quoting (quote only fields containing `,` `"` or newline; inner `"` doubled), columns in the exact header order, rows sorted by date ascending. Blank means "not answered", never "no".
- Never touch the real `habits.csv` in tests or dev runs. Tests use tmp copies; `tools/dev_worker.py` works on a scratch copy.
- Existing 60 pytest tests in `tests/test_habits.py` must keep passing. Run: `cd C:\Users\Auckie\workspaces\Health-Tracker && python -m pytest tests/test_habits.py -q`.
- Run node tests with: `node --test tests/habits-core.test.js` from the repo root.
- Colors: bg `#0f1117`, surface `#1a1d27`, border `#2a2d3a`, text `#e8eaf0`, muted `#7a7f94`, error `#f87171`, accent `#a78bfa`, accent-dim `#2e2452`, yes `#22c55e` on `#14331f`, no `#ef4444` on `#3a1717`, radius 10px, font `-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Windows machine. Bash (Git Bash) works for git/node/python. Paths with backslashes in PowerShell only.

---

### Task 1: definitions.json — phone flags, questions, new sources, new column

**Files:**
- Modify: `habits/definitions.json`
- Test: `tests/test_habits.py` (append)

**Interfaces:**
- Produces: habit objects gain optional `phone_order` (int) and `question` (string). New config keys `water_dashboard_sources`, `workout_log_sources`, `meal_dashboard_sources` (lists of strings), `calorie_tolerance_pct` (number). New habit id `calories_on_target`. Sources `water_dashboard`, `workout_log`, `meal_dashboard` are new `source` values. Task 2 and Task 4 read these.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_habits.py`)

```python
# -- phone flow definition ----------------------------------------------------

PHONE_ORDER = ["made_bed", "morning_vitamins", "shower", "teeth", "night_vitamins",
               "no_junk", "no_fap", "read_fiction", "read_nonfiction",
               "devices_off_9pm", "screentime"]


def test_phone_habits_are_eleven_binary_self_daily_in_order(defs):
    phone = sorted((h for h in defs["habits"] if "phone_order" in h),
                   key=lambda h: h["phone_order"])
    assert [h["id"] for h in phone] == PHONE_ORDER
    for h in phone:
        assert h["type"] == "binary", h["id"]
        assert h["source"] == "self", h["id"]
        assert h.get("active", True) is True, h["id"]
        assert h.get("cadence", "daily") != "weekly", h["id"]
        assert h["question"].endswith("?"), h["id"]


def test_screentime_is_binary_now(defs):
    s = habits.habit_by_id(defs, "screentime")
    assert s["type"] == "binary"
    assert "target" not in s and "direction" not in s


def test_water_and_workout_are_derived_now(defs):
    assert habits.habit_by_id(defs, "water")["source"] == "water_dashboard"
    assert habits.habit_by_id(defs, "workout")["source"] == "workout_log"
    assert habits.habit_by_id(defs, "workout_whoop")["source"] == "whoop"


def test_calories_on_target_column_sits_before_logged_at(defs):
    cols = habits.columns(defs)
    assert cols.index("calories_on_target") == cols.index("books_finished") + 1
    assert cols[-2:] == ["logged_at", "note"]
    c = habits.habit_by_id(defs, "calories_on_target")
    assert c["type"] == "binary" and c["source"] == "meal_dashboard"


def test_new_source_lists_exist(defs):
    cfg = defs["config"]
    for key in ("water_dashboard_sources", "workout_log_sources", "meal_dashboard_sources"):
        assert isinstance(cfg[key], list) and cfg[key], key
        assert cfg[key][0].startswith("https://raw.githubusercontent.com/"), key
    assert cfg["calorie_tolerance_pct"] == 10
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_habits.py -q -k "phone or screentime_is or derived_now or calories_on_target or new_source"`
Expected: 5 failures (KeyError / AssertionError).

- [ ] **Step 3: Edit `habits/definitions.json`**

In `config` add (keep every existing key):

```json
"water_dashboard_sources": [
  "https://raw.githubusercontent.com/auckiefenstermacher19-cmd/MyFitnessClone/main/Water_Data_Dashboard.csv",
  "../MyFitnessClone/Water_Data_Dashboard.csv"
],
"workout_log_sources": [
  "https://raw.githubusercontent.com/auckiefenstermacher19-cmd/Workout-Tracker-v2/main/workout_tracker.csv"
],
"meal_dashboard_sources": [
  "https://raw.githubusercontent.com/auckiefenstermacher19-cmd/MyFitnessClone/main/Meal_Data_Dashboard.csv",
  "../MyFitnessClone/Meal_Data_Dashboard.csv"
],
"calorie_tolerance_pct": 10,
"source_fetch_timeout_s": 10
```

Habit edits (ids unchanged, positions unchanged):

| id | change |
|---|---|
| made_bed | add `"phone_order": 1, "question": "Made your bed?"` |
| morning_vitamins | `"phone_order": 2, "question": "Morning vitamins?"` |
| shower | `"phone_order": 3, "question": "Showered?"` |
| teeth | `"phone_order": 4, "question": "Brushed your teeth?"` |
| night_vitamins | `"phone_order": 5, "question": "Night vitamins?"` |
| no_junk | `"phone_order": 6, "question": "Stayed off junk food?"` |
| no_fap | `"phone_order": 7, "question": "Stayed clean? (no fap)"` |
| read_fiction | `"phone_order": 8, "question": "Read fiction?"` |
| read_nonfiction | `"phone_order": 9, "question": "Read non-fiction?"` |
| devices_off_9pm | `"phone_order": 10, "question": "Devices off by 9pm?"` |
| screentime | `"type": "binary"`, remove `target` and `direction`, `"label": "Screentime under 2h"`, `"phone_order": 11, `"question": "Screentime under 2 hours?"`, add `"note": "Was type hours with zero entries ever; became yes/no on 2026-09-11 for the phone flow."` |
| water | `"source": "water_dashboard"`, add `"note": "Derived from the water page since 2026-09-11: day total >= goal. Never asked."` |
| workout | `"source": "workout_log"`, replace note with `"Derived from Workout-Tracker-v2 since 2026-09-11: any set logged that day -> yes; otherwise blank, never no. WHOOP's view lands in workout_whoop. A hand-set value is never overwritten."` |

Insert a new habit object immediately after `books_finished` (last element of the array):

```json
{
  "id": "calories_on_target",
  "label": "Calories on target",
  "type": "binary",
  "source": "meal_dashboard",
  "aliases": ["calories", "hit calories", "calorie goal"],
  "note": "Derived from the food log dashboard: calories_actual within calorie_tolerance_pct of calories_goal -> yes; a logged day outside -> no; no row -> blank. Added 2026-09-11."
}
```

Update the top-level `"note"` to: `"Column order mirrors the original 'Habit Tracker' tab in Auckie - 2B.xlsx, then habits in the order they were added. phone_order marks what the phone page asks."`

Validate JSON: `python -c "import json;json.load(open('habits/definitions.json'))"`.

- [ ] **Step 4: Run the whole suite**

Run: `python -m pytest tests/test_habits.py -q`
Expected: all pass. If `test_original_spreadsheet_habits_survive_in_order` or a `hours` test fails because screentime is no longer `hours`, update that test to use another example or drop the screentime case; `test_hours_keeps_fractions` may reference screentime — switch it to a synthetic `{"id":"x","type":"hours"}` dict.

- [ ] **Step 5: Add the new column to `habits.csv` header**

`habits.py` writes only the columns it knows, so the header must gain `calories_on_target` before `logged_at`. Do it with the script itself so the file stays byte-exact:

```bash
python - <<'PY'
import csv, io, json
defs = json.load(open("habits/definitions.json", encoding="utf-8"))
cols = ["date", "day_of_week"] + [h["id"] for h in defs["habits"]] + ["logged_at", "note"]
rows = list(csv.DictReader(open("habits.csv", newline="", encoding="utf-8-sig")))
out = io.StringIO()
w = csv.DictWriter(out, fieldnames=cols, lineterminator="\n")
w.writeheader()
for r in rows:
    w.writerow({c: r.get(c, "") for c in cols})
open("habits.csv", "w", newline="", encoding="utf-8").write(out.getvalue())
PY
git diff --stat habits.csv
```
Expected: header line changed only; row count unchanged (every row gains one empty field).

- [ ] **Step 6: Commit**

```bash
git add habits/definitions.json habits.csv tests/test_habits.py
git commit -m "habits: phone flow flags, screentime yes/no, water+workout derived, calories_on_target column

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- habits/definitions.json habits.csv tests/test_habits.py
```

---

### Task 2: habits.py — three new derivations with URL-then-local sources

**Files:**
- Modify: `habits.py` (add after `prefill_learning`, before `prefill`; wire into `prefill`)
- Test: `tests/test_habits.py` (append)

**Interfaces:**
- Consumes: config keys from Task 1.
- Produces: `read_source_rows(defs, config_key, notes) -> list[dict] | None`, `prefill_water(defs, day, known, notes)`, `prefill_workout_log(...)`, `prefill_calories(...)`, all same signature as `prefill_learning`. `prefill()` calls all three. `_fetch_text(url, timeout) -> str` is the single network call so tests can monkeypatch it.

- [ ] **Step 1: Write the failing tests**

```python
# -- new derivations ----------------------------------------------------------

def _use_local_source(monkeypatch, defs, key, text, tmp_path):
    """Point one source list at a temp file holding `text`; kill network."""
    p = tmp_path / (key + ".csv")
    p.write_text(text, encoding="utf-8")
    monkeypatch.setitem(defs["config"], key, [str(p)])
    monkeypatch.setattr(habits, "_fetch_text", lambda url, timeout: (_ for _ in ()).throw(OSError("no net")))
    return p


def test_water_yes_when_total_meets_goal(defs, tmp_path, monkeypatch):
    _use_local_source(monkeypatch, defs, "water_dashboard_sources",
        "date,water_fl_oz,water_goal_fl_oz,water_pct_of_goal\n2026-09-11,130,128,101.6\n", tmp_path)
    known, notes = {}, []
    habits.prefill_water(defs, date(2026, 9, 11), known, notes)
    assert known["water"] == "yes"


def test_water_no_when_under_goal_and_blank_when_no_row(defs, tmp_path, monkeypatch):
    _use_local_source(monkeypatch, defs, "water_dashboard_sources",
        "date,water_fl_oz,water_goal_fl_oz\n2026-09-11,64,128\n", tmp_path)
    known, notes = {}, []
    habits.prefill_water(defs, date(2026, 9, 11), known, notes)
    assert known["water"] == "no"
    known = {}
    habits.prefill_water(defs, date(2026, 9, 12), known, notes)
    assert "water" not in known


def test_workout_yes_from_any_logged_set_else_blank(defs, tmp_path, monkeypatch):
    _use_local_source(monkeypatch, defs, "workout_log_sources",
        "Date,Workout Day,Exercise,Set Number,Weight,Reps\n2026-09-11,Back,BB Row,1,255,5\n", tmp_path)
    known, notes = {}, []
    habits.prefill_workout_log(defs, date(2026, 9, 11), known, notes)
    assert known["workout"] == "yes"
    known = {}
    habits.prefill_workout_log(defs, date(2026, 9, 12), known, notes)
    assert "workout" not in known          # never "no"


@pytest.mark.parametrize("actual,goal,expected", [
    ("2600", "2600", "yes"), ("2350", "2600", "yes"), ("2860", "2600", "yes"),
    ("2300", "2600", "no"), ("2900", "2600", "no"), ("2600", "", None), ("", "2600", None),
])
def test_calories_within_ten_percent(defs, tmp_path, monkeypatch, actual, goal, expected):
    _use_local_source(monkeypatch, defs, "meal_dashboard_sources",
        "date,,calories_actual,calories_goal\n2026-09-11,," + actual + "," + goal + "\n", tmp_path)
    known, notes = {}, []
    habits.prefill_calories(defs, date(2026, 9, 11), known, notes)
    assert known.get("calories_on_target") == expected


def test_url_source_is_tried_first_then_local(defs, tmp_path, monkeypatch):
    p = tmp_path / "w.csv"
    p.write_text("date,water_fl_oz,water_goal_fl_oz\n2026-09-11,10,128\n", encoding="utf-8")
    monkeypatch.setitem(defs["config"], "water_dashboard_sources", ["https://example.invalid/x.csv", str(p)])
    calls = []
    def fake(url, timeout):
        calls.append(url)
        return "date,water_fl_oz,water_goal_fl_oz\n2026-09-11,200,128\n"
    monkeypatch.setattr(habits, "_fetch_text", fake)
    known, notes = {}, []
    habits.prefill_water(defs, date(2026, 9, 11), known, notes)
    assert calls == ["https://example.invalid/x.csv"]
    assert known["water"] == "yes"            # URL answered, local not consulted


def test_all_sources_failing_leaves_blank_with_note(defs, monkeypatch):
    monkeypatch.setitem(defs["config"], "workout_log_sources", ["https://example.invalid/x.csv"])
    monkeypatch.setattr(habits, "_fetch_text", lambda url, timeout: (_ for _ in ()).throw(OSError("down")))
    known, notes = {}, []
    habits.prefill_workout_log(defs, date(2026, 9, 11), known, notes)
    assert known == {}
    assert any("workout" in n and "blank" in n for n in notes)


def test_prefill_calls_new_sources(defs, monkeypatch):
    seen = []
    for name in ("prefill_whoop", "prefill_meal_log", "prefill_learning",
                 "prefill_water", "prefill_workout_log", "prefill_calories"):
        monkeypatch.setattr(habits, name, lambda d, day, k, n, _n=name: seen.append(_n))
    habits.prefill(defs, date(2026, 9, 11))
    assert seen[-3:] == ["prefill_water", "prefill_workout_log", "prefill_calories"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_habits.py -q -k "water or workout_yes or calories or url_source or all_sources or prefill_calls"`
Expected: AttributeError (functions missing).

- [ ] **Step 3: Implement in `habits.py`** (insert after `prefill_learning`)

```python
# -- Sibling-app sources (water page, workout tracker, food dashboard) ------

def _fetch_text(url, timeout):
    """The one network call. Tests replace this."""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "health-tracker-habits"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8-sig", errors="replace")


def read_source_rows(defs, config_key, notes):
    """Rows from the first source in defs.config[config_key] that answers.

    Entries starting with http are fetched; others are paths relative to
    this repo. Every failure is noted and the next entry tried. Returns None
    when nothing answered, so callers leave the habit blank.
    """
    timeout = defs["config"].get("source_fetch_timeout_s", 10)
    for entry in defs["config"].get(config_key, []):
        try:
            if entry.startswith("http"):
                text = _fetch_text(entry, timeout)
            else:
                p = (REPO_DIR / entry).resolve()
                if not p.exists():
                    continue
                text = p.read_text(encoding="utf-8-sig", errors="replace")
        except Exception as exc:          # network, permission, decode - all skip
            notes.append(config_key + ": " + entry + " failed (" + str(exc)[:80] + ")")
            continue
        rows = list(csv.DictReader(io.StringIO(text)))
        notes.append(config_key + ": read " + str(len(rows)) + " rows from " + entry)
        return rows
    return None


def _row_for_day(rows, day, field="date"):
    target = day.isoformat()
    for r in rows:
        if (r.get(field) or "").strip() == target:
            return r
    return None


def prefill_water(defs, day, known, notes):
    """water = day total on the water page >= its goal. No row -> blank."""
    rows = read_source_rows(defs, "water_dashboard_sources", notes)
    if rows is None:
        notes.append("No water dashboard reachable - water left blank.")
        return
    row = _row_for_day(rows, day)
    if row is None:
        notes.append("Water dashboard has no row for " + day.isoformat() + " - water left blank.")
        return
    total, goal = _num(row, "water_fl_oz"), _num(row, "water_goal_fl_oz")
    if total is None or goal is None:
        notes.append("Water dashboard row missing numbers - water left blank.")
        return
    known["water"] = "yes" if total >= goal else "no"
    notes.append("Water: %s of %s fl oz -> water=%s" % (total, goal, known["water"]))


def prefill_workout_log(defs, day, known, notes):
    """workout = any set logged in Workout-Tracker-v2 that day. Never 'no'."""
    rows = read_source_rows(defs, "workout_log_sources", notes)
    if rows is None:
        notes.append("No workout log reachable - workout left blank.")
        return
    if _row_for_day(rows, day, field="Date") is None:
        notes.append("Workout log has no sets for " + day.isoformat() + " - workout left blank.")
        return
    known["workout"] = "yes"
    notes.append("Workout log: sets found for " + day.isoformat() + " -> workout=yes")


def prefill_calories(defs, day, known, notes):
    """calories_on_target = actual within calorie_tolerance_pct of goal."""
    rows = read_source_rows(defs, "meal_dashboard_sources", notes)
    if rows is None:
        notes.append("No meal dashboard reachable - calories_on_target left blank.")
        return
    row = _row_for_day(rows, day)
    if row is None:
        notes.append("Meal dashboard has no row for " + day.isoformat() + " - calories_on_target left blank.")
        return
    actual, goal = _num(row, "calories_actual"), _num(row, "calories_goal")
    if actual is None or goal is None or goal <= 0:
        notes.append("Meal dashboard row missing calories - calories_on_target left blank.")
        return
    tol = float(defs["config"].get("calorie_tolerance_pct", 10)) / 100.0
    ok = abs(actual - goal) <= goal * tol
    known["calories_on_target"] = "yes" if ok else "no"
    notes.append("Calories: %s vs goal %s (tol %d%%) -> calories_on_target=%s"
                 % (actual, goal, tol * 100, known["calories_on_target"]))
```

Add `import io` to the imports. Check `_num(row, field)` at line ~229 returns `None` for blank/non-numeric (it should; if it raises, wrap accordingly). Then in `prefill()` add after `prefill_learning(...)`:

```python
    prefill_water(defs, day, known, notes)
    prefill_workout_log(defs, day, known, notes)
    prefill_calories(defs, day, known, notes)
```

- [ ] **Step 4: Run the whole suite**

Run: `python -m pytest tests/test_habits.py -q`
Expected: all pass (60 + Task 1's 5 + these 13).

- [ ] **Step 5: Smoke the real command against live sources**

Run: `python habits.py prefill --date 2026-09-10`
Expected: exit 0; notes mention the water dashboard, workout log and meal dashboard (rows read or "no row"); no traceback. Do not run `log`.

- [ ] **Step 6: Commit**

```bash
git add habits.py tests/test_habits.py
git commit -m "habits: derive water, workout and calories from the sibling apps

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- habits.py tests/test_habits.py
```

---

### Task 3: whoop-data/run-once.ps1 — pull before the habits write

**Files:**
- Modify: `C:\Users\Auckie\workspaces\whoop-data\run-once.ps1` (the habits block starting near line 116; commit/push at ~150-175)

**Interfaces:** none. Behaviour change only.

- [ ] **Step 1: Read the block** `sed -n 110,185p run-once.ps1` in `whoop-data`. Note `$htRepo`, `$py`, `$habits`, `$yday`, `$habitsExit`, and `Write-Log`.

- [ ] **Step 2: Insert the pull** immediately after `if (Test-Path $habits) {` and before the `& $py $habits log ...` line:

```powershell
    # Pull FIRST. The phone page commits habits.csv straight to the remote at
    # night; writing yesterday's derived habits on a stale checkout and
    # rebasing afterwards conflicts on that same row and strands the morning.
    Push-Location $htRepo
    git pull --rebase --autostash -q 2>&1 | ForEach-Object { Write-Log "  habits git (pre-pull): $_" }
    $prePull = $LASTEXITCODE
    Pop-Location
    if ($prePull -ne 0) {
        Write-Log "  habits: PULL FAILED before write (git exit $prePull) - skipping habits step so nothing is written on a stale file"
        $habitsExit = 2
    }
    else {
```

and close that `else {` with a `}` after the existing habits commit/push block ends (the block that sets `$habitsExit` for push failure). Keep the existing post-commit `git pull --rebase --autostash` too; it is cheap and covers the seconds-wide window. Indentation is cosmetic; correctness is the brace.

- [ ] **Step 3: Parse-check the script**

Run (PowerShell): `powershell -NoProfile -Command "$null = [scriptblock]::Create((Get-Content -Raw 'C:\Users\Auckie\workspaces\whoop-data\run-once.ps1')); 'parse ok'"`
Expected: `parse ok`. Also run `python -c "open(r'C:\Users\Auckie\workspaces\whoop-data\run-once.ps1','rb').read().decode('ascii')"` — must not raise (the file must stay ASCII; see memory note on `.ps1` files).

- [ ] **Step 4: Run whoop-data's own tests** `cd C:\Users\Auckie\workspaces\whoop-data && .venv\Scripts\python.exe -m unittest discover -s tests -q`. Expected: pass.

- [ ] **Step 5: Commit in whoop-data**

```bash
cd /c/Users/Auckie/workspaces/whoop-data
git add run-once.ps1
git commit -m "run-once: pull Health-Tracker before writing derived habits

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- run-once.ps1
```

---

### Task 4: habits-core.js — pure CSV / upsert / question logic with node tests

**Files:**
- Create: `habits-core.js`
- Create: `tests/habits-core.test.js`
- Fixture: `tests/fixtures/habits-sample.csv` (copy the first 6 lines of the real `habits.csv` after Task 1, converted to LF)

**Interfaces:**
- Produces global `HabitsCore` (browser) / `module.exports` (node) with:
  - `parseCSV(text) -> {header: string[], rows: Array<Object>}` — rows keyed by header, missing cells `""`.
  - `serializeCSV(header, rows) -> string` — LF, trailing `\n`, minimal quoting.
  - `upsertDay(parsed, dateStr, values, loggedAt) -> {header, rows}` — new object; creates the row (with `day_of_week`) if absent; sets each key in `values` (a `""` value clears); sets `logged_at`; keeps every other column; sorts rows by `date`. Throws if a key in `values` is not in `header`.
  - `dayOfWeek(dateStr) -> "Monday"…`
  - `phoneHabits(defs) -> habit[]` — `phone_order` present, `active !== false`, `source === "self"`, `cadence !== "weekly"`, sorted by `phone_order`.
  - `derivedHabits(defs) -> habit[]` — `source !== "self"`, `active !== false`, in file order.
  - `todayLocal(now = new Date()) -> "YYYY-MM-DD"` (device-local).
  - `localISO(now = new Date()) -> "2026-09-11T22:10:00-04:00"`.
  - `formatDateLong("2026-09-11") -> "September 11"`.
  - `formatLoggedAt("2026-09-11T22:10:00-04:00") -> "10:10 pm"`.
  - `draftKey(dateStr) -> "habits_draft_2026-09-11"`.

- [ ] **Step 1: Make the fixture**

```bash
head -6 habits.csv | tr -d '\r' > tests/fixtures/habits-sample.csv   # mkdir -p tests/fixtures first
```

- [ ] **Step 2: Write the failing tests** `tests/habits-core.test.js`

```js
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const core = require('../habits-core.js');

const FIX = fs.readFileSync(path.join(__dirname, 'fixtures', 'habits-sample.csv'), 'utf8');
const DEFS = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'habits', 'definitions.json'), 'utf8'));

test('parse then serialize is byte-identical on the real file', () => {
  const p = core.parseCSV(FIX);
  assert.equal(core.serializeCSV(p.header, p.rows), FIX);
});

test('parse handles quoted commas and doubled quotes', () => {
  const p = core.parseCSV('a,b\n"x, y","say ""hi"""\n');
  assert.deepEqual(p.rows[0], { a: 'x, y', b: 'say "hi"' });
  assert.equal(core.serializeCSV(p.header, p.rows), 'a,b\n"x, y","say ""hi"""\n');
});

test('serialize uses LF, trailing newline, no quoting when not needed', () => {
  assert.equal(core.serializeCSV(['a', 'b'], [{ a: '1', b: '' }]), 'a,b\n1,\n');
});

test('upsertDay creates a sorted row with day_of_week and logged_at', () => {
  const p = core.parseCSV('date,day_of_week,made_bed,teeth,logged_at,note\n2026-09-12,Saturday,yes,,,\n');
  const out = core.upsertDay(p, '2026-09-11', { made_bed: 'yes', teeth: 'no' }, '2026-09-11T22:10:00-04:00');
  assert.equal(out.rows.length, 2);
  assert.deepEqual(out.rows[0], { date: '2026-09-11', day_of_week: 'Friday', made_bed: 'yes', teeth: 'no', logged_at: '2026-09-11T22:10:00-04:00', note: '' });
  assert.equal(out.rows[1].date, '2026-09-12');
  assert.equal(p.rows.length, 1, 'input not mutated');
});

test('upsertDay updates only the given keys and can clear one', () => {
  const p = core.parseCSV('date,day_of_week,made_bed,teeth,slept_7h,logged_at,note\n2026-09-11,Friday,yes,yes,no,old,keep me\n');
  const out = core.upsertDay(p, '2026-09-11', { teeth: '' }, 'new');
  assert.deepEqual(out.rows[0], { date: '2026-09-11', day_of_week: 'Friday', made_bed: 'yes', teeth: '', slept_7h: 'no', logged_at: 'new', note: 'keep me' });
});

test('upsertDay refuses unknown columns', () => {
  const p = core.parseCSV('date,day_of_week,logged_at,note\n');
  assert.throws(() => core.upsertDay(p, '2026-09-11', { nope: 'yes' }, 'x'), /unknown column/);
});

test('phoneHabits are the eleven in order, derivedHabits exclude self and retired', () => {
  const ids = core.phoneHabits(DEFS).map(h => h.id);
  assert.deepEqual(ids, ['made_bed', 'morning_vitamins', 'shower', 'teeth', 'night_vitamins', 'no_junk', 'no_fap', 'read_fiction', 'read_nonfiction', 'devices_off_9pm', 'screentime']);
  const d = core.derivedHabits(DEFS).map(h => h.id);
  assert.ok(d.includes('slept_7h') && d.includes('water') && d.includes('workout') && d.includes('calories_on_target'));
  assert.ok(!d.includes('shower_teeth') && !d.includes('made_bed'));
});

test('date helpers are device-local and formatted for humans', () => {
  const d = new Date(2026, 8, 11, 22, 10, 0);            // local time
  assert.equal(core.todayLocal(d), '2026-09-11');
  assert.match(core.localISO(d), /^2026-09-11T22:10:00[+-]\d\d:\d\d$/);
  assert.equal(core.dayOfWeek('2026-09-11'), 'Friday');
  assert.equal(core.formatDateLong('2026-09-11'), 'September 11');
  assert.equal(core.formatLoggedAt('2026-09-11T22:10:00-04:00'), '10:10 pm');
  assert.equal(core.draftKey('2026-09-11'), 'habits_draft_2026-09-11');
});
```

- [ ] **Step 3: Run to verify they fail** `node --test tests/habits-core.test.js` → cannot find module.

- [ ] **Step 4: Implement `habits-core.js`**

```js
/* habits-core.js — pure logic for habits.html. No DOM, no fetch.
   Loaded by a <script> tag in the page and by node --test. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.HabitsCore = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  function parseCSV(text) {
    const rows = [];
    let field = '', record = [], inQ = false, i = 0;
    const s = text.replace(/\r\n/g, '\n');
    while (i < s.length) {
      const c = s[i];
      if (inQ) {
        if (c === '"') { if (s[i + 1] === '"') { field += '"'; i++; } else inQ = false; }
        else field += c;
      } else if (c === '"') inQ = true;
      else if (c === ',') { record.push(field); field = ''; }
      else if (c === '\n') { record.push(field); rows.push(record); record = []; field = ''; }
      else field += c;
      i++;
    }
    if (field.length || record.length) { record.push(field); rows.push(record); }
    const header = rows.shift() || [];
    return {
      header,
      rows: rows.filter(r => r.length > 1 || r[0] !== '').map(r => {
        const o = {};
        header.forEach((h, k) => { o[h] = r[k] === undefined ? '' : r[k]; });
        return o;
      })
    };
  }

  function quote(v) {
    v = v == null ? '' : String(v);
    return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  }

  function serializeCSV(header, rows) {
    const lines = [header.map(quote).join(',')];
    rows.forEach(r => lines.push(header.map(h => quote(r[h])).join(',')));
    return lines.join('\n') + '\n';
  }

  const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

  function parts(dateStr) { const [y, m, d] = dateStr.split('-').map(Number); return { y, m, d }; }
  function dayOfWeek(dateStr) { const p = parts(dateStr); return DAYS[new Date(p.y, p.m - 1, p.d).getDay()]; }
  function formatDateLong(dateStr) { const p = parts(dateStr); return MONTHS[p.m - 1] + ' ' + p.d; }

  function upsertDay(parsed, dateStr, values, loggedAt) {
    const header = parsed.header.slice();
    Object.keys(values).forEach(k => { if (!header.includes(k)) throw new Error('unknown column: ' + k); });
    const rows = parsed.rows.map(r => Object.assign({}, r));
    let row = rows.find(r => r.date === dateStr);
    if (!row) {
      row = {}; header.forEach(h => { row[h] = ''; });
      row.date = dateStr; row.day_of_week = dayOfWeek(dateStr);
      rows.push(row);
    }
    Object.keys(values).forEach(k => { row[k] = values[k] == null ? '' : String(values[k]); });
    if (header.includes('logged_at')) row.logged_at = loggedAt;
    rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
    return { header, rows };
  }

  function phoneHabits(defs) {
    return defs.habits
      .filter(h => typeof h.phone_order === 'number' && h.active !== false && h.source === 'self' && h.cadence !== 'weekly')
      .sort((a, b) => a.phone_order - b.phone_order);
  }
  function derivedHabits(defs) { return defs.habits.filter(h => h.source !== 'self' && h.active !== false); }

  const pad = n => String(n).padStart(2, '0');
  function todayLocal(now) { now = now || new Date(); return now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate()); }
  function localISO(now) {
    now = now || new Date();
    const off = -now.getTimezoneOffset(), sign = off >= 0 ? '+' : '-', a = Math.abs(off);
    return todayLocal(now) + 'T' + pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds()) + sign + pad(Math.floor(a / 60)) + ':' + pad(a % 60);
  }
  function formatLoggedAt(iso) {
    const m = /T(\d\d):(\d\d)/.exec(iso || '');
    if (!m) return '';
    let h = Number(m[1]); const ap = h >= 12 ? 'pm' : 'am'; h = h % 12 || 12;
    return h + ':' + m[2] + ' ' + ap;
  }
  function draftKey(dateStr) { return 'habits_draft_' + dateStr; }

  return { parseCSV, serializeCSV, upsertDay, dayOfWeek, phoneHabits, derivedHabits, todayLocal, localISO, formatDateLong, formatLoggedAt, draftKey };
}));
```

`formatLoggedAt` reads the wall-clock in the stamp, not the device zone; the stamp was written in Auckie's zone, so that is the time he saw.

- [ ] **Step 5: Run tests** `node --test tests/habits-core.test.js` → all pass. If the byte-identical test fails, diff the two strings; the usual cause is a stray `\r` in the fixture (re-run Step 1) or the last-line handling.

- [ ] **Step 6: Commit**

```bash
git add habits-core.js tests/habits-core.test.js tests/fixtures/habits-sample.csv
git commit -m "habits page: pure CSV/upsert/question core with node tests

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- habits-core.js tests/habits-core.test.js tests/fixtures/habits-sample.csv
```

---

### Task 5: Worker, config, manifest, icon, local dev worker

**Files:**
- Create: `cloudflare-worker/habits-worker.js`
- Create: `habits-config.js`
- Create: `habits.webmanifest`, `habits-icon-192.png`, `habits-icon-512.png`, `tools/make_habits_icon.py`
- Create: `tools/dev_worker.py`

**Interfaces:**
- Produces: Worker endpoints `GET /habits`, `PUT /habits`, `GET /raw/definitions`, `OPTIONS *`. `habits-config.js` defines `var HABITS_CONFIG = { workerUrl: '...' }`. `tools/dev_worker.py --port 8765 [--csv PATH]` serves the same endpoints plus static files at `http://127.0.0.1:8765/`.

- [ ] **Step 1: Worker.** Copy the reference implementation at `C:\Users\Auckie\AppData\Local\Temp\claude\C--Users-Auckie-workspaces\7ad1b5d1-b7d7-4007-b971-86295af106f4\scratchpad\wt2\cloudflare-worker\worker.js` (if missing, `gh repo clone auckiefenstermacher19-cmd/Workout-Tracker-v2` somewhere in the scratchpad) to `cloudflare-worker/habits-worker.js`. Keep `corsHeaders`, `jsonResponse`, `textResponse`, `githubFetch`, `handleGetFile`, `handlePutFile`, `handleRawFile` verbatim. Replace the header comment to name this app and the three env settings, `User-Agent` to `habit-tracker-worker`, and the route table in `fetch` with exactly:

```js
      if (path === '/habits' && method === 'GET')  return await handleGetFile(env, 'habits.csv');
      if (path === '/habits' && method === 'PUT')  return await handlePutFile(env, 'habits.csv', await request.text());
      if (path === '/raw/definitions' && method === 'GET') return await handleRawFile(env, 'habits/definitions.json');
      return jsonResponse({ error: 'Not found', path }, 404, env);
```

`handlePutFile` passes GitHub's status through, so a stale sha surfaces as 409 to the page.

- [ ] **Step 2: `habits-config.js`**

```js
// habits-config.js — no secrets. The GitHub token lives only in the
// Cloudflare Worker (habit-tracker-proxy). Replace workerUrl after deploy.
var HABITS_CONFIG = {
  workerUrl: 'https://habit-tracker-proxy.auckiefenstermacher19.workers.dev'
};
```

- [ ] **Step 3: Manifest** `habits.webmanifest`:

```json
{
  "name": "Habits",
  "short_name": "Habits",
  "start_url": "./habits.html",
  "scope": "./",
  "display": "standalone",
  "orientation": "portrait",
  "background_color": "#0f1117",
  "theme_color": "#0f1117",
  "icons": [
    { "src": "habits-icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any" },
    { "src": "habits-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any" }
  ]
}
```

- [ ] **Step 4: Icon script** `tools/make_habits_icon.py` (model on `../MyFitnessClone/tools/make_water_icon.py`; Pillow is installed):

```python
"""Draw the Habits home-screen icon: a white check on violet. Run once."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
for size in (192, 512):
    im = Image.new("RGBA", (size, size), "#a78bfa")
    d = ImageDraw.Draw(im)
    r = size * 0.22
    d.rounded_rectangle([0, 0, size, size], radius=r, fill="#a78bfa")
    w = max(6, size // 12)
    pts = [(size * 0.26, size * 0.52), (size * 0.44, size * 0.70), (size * 0.76, size * 0.34)]
    d.line(pts, fill="white", width=w, joint="curve")
    im.save(ROOT / f"habits-icon-{size}.png")
    print("wrote", size)
```
Run: `python tools/make_habits_icon.py`.

- [ ] **Step 5: Local dev worker** `tools/dev_worker.py`:

```python
"""Stand-in for the Cloudflare Worker so habits.html can be driven locally.

Serves the repo folder as static files AND the Worker's endpoints, against a
SCRATCH COPY of habits.csv. It never writes the real file.

    python tools/dev_worker.py            # http://127.0.0.1:8765/habits.html
    python tools/dev_worker.py --csv some/copy.csv --port 9000
"""
import argparse, hashlib, json, shutil, sys, tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha_of(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def make_handler(csv_path):
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT), **kw)

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status); self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_OPTIONS(self):
            self.send_response(204); self._cors(); self.end_headers()

        def do_GET(self):
            p = self.path.split("?")[0]
            if p == "/habits":
                text = csv_path.read_text(encoding="utf-8")
                return self._json({"content": text, "sha": sha_of(text)})
            if p == "/raw/definitions":
                body = (ROOT / "habits" / "definitions.json").read_bytes()
                self.send_response(200); self._cors()
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body))); self.end_headers()
                return self.wfile.write(body)
            return super().do_GET()

        def do_PUT(self):
            if self.path.split("?")[0] != "/habits":
                return self._json({"error": "Not found"}, 404)
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            current = csv_path.read_text(encoding="utf-8")
            if body.get("sha") != sha_of(current):
                return self._json({"error": "GitHub write failed", "status": 409, "message": "sha mismatch"}, 409)
            csv_path.write_bytes(body["content"].encode("utf-8"))   # bytes: keeps LF exactly
            print("PUT habits.csv:", body.get("message"), file=sys.stderr)
            return self._json({"success": True, "sha": sha_of(body["content"])})

        def log_message(self, fmt, *args):
            print(self.address_string(), fmt % args, file=sys.stderr)
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--csv", help="scratch CSV to serve; default: fresh temp copy of habits.csv")
    a = ap.parse_args()
    if a.csv:
        csv_path = Path(a.csv)
    else:
        csv_path = Path(tempfile.mkdtemp(prefix="habits-dev-")) / "habits.csv"
        # Normalise to LF so the served bytes match what git stores.
        csv_path.write_bytes((ROOT / "habits.csv").read_bytes().replace(b"\r\n", b"\n"))
    print("scratch csv:", csv_path, file=sys.stderr)
    print("open: http://127.0.0.1:%d/habits.html" % a.port, file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(csv_path)).serve_forever()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Verify the dev worker** — start it in the background, then:

```bash
curl -s http://127.0.0.1:8765/habits | head -c 120; echo
curl -s http://127.0.0.1:8765/raw/definitions | head -c 60; echo
curl -s -X PUT http://127.0.0.1:8765/habits -d '{"content":"x","sha":"bad"}' -w ' %{http_code}\n'
```
Expected: JSON with `content` and `sha`; the definitions text; `409`. Stop the server.

- [ ] **Step 7: Commit**

```bash
git add cloudflare-worker/habits-worker.js habits-config.js habits.webmanifest habits-icon-192.png habits-icon-512.png tools/make_habits_icon.py tools/dev_worker.py
git commit -m "habits page: worker proxy, config, manifest, icon, local dev worker

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- cloudflare-worker/habits-worker.js habits-config.js habits.webmanifest habits-icon-192.png habits-icon-512.png tools/make_habits_icon.py tools/dev_worker.py
```

---

### Task 6: habits.html — the page

**Files:**
- Create: `habits.html`
- Reference for look and PWA head: `../MyFitnessClone/Water_Log.html` (lines 1-60 for head + tokens; its `.card`, button, `#toast` styles further down).

**Interfaces:**
- Consumes: `HabitsCore` (Task 4), `HABITS_CONFIG.workerUrl` (Task 5), Worker/dev endpoints (Task 5).
- Produces: the four views described in the spec. When served from `localhost`/`127.0.0.1`, the page uses `location.origin` as the worker URL so `tools/dev_worker.py` works with no config edit.

- [ ] **Step 1: Head and styles.** Copy the water page's `<head>` meta block, changing title/app-title to `Habits`, manifest to `habits.webmanifest`, icons to `habits-icon-192.png`. Tokens from Global Constraints. Add `<script src="habits-config.js"></script><script src="habits-core.js"></script>` before the inline script. Styles to add:

```css
.view { display: none; width: 100%; max-width: 420px; }
.view.active { display: flex; flex-direction: column; gap: 20px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 24px; display: flex; flex-direction: column; gap: 20px; }
.status { color: var(--muted); font-size: 14px; }
.btn { width: 100%; padding: 18px; border-radius: var(--radius); border: 2px solid var(--accent); background: var(--accent-dim); color: var(--text); font-size: 18px; font-weight: 700; cursor: pointer; }
.btn:active { transform: scale(0.97); }
.btn.secondary { border-color: var(--border); background: transparent; }
.progress { color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: 1px; }
.question { font-size: 28px; font-weight: 700; line-height: 1.2; min-height: 68px; }
.tiles { display: flex; flex-direction: column; gap: 14px; }
.tile { position: relative; min-height: 130px; border-radius: 14px; border: 2px solid; font-size: 30px; font-weight: 800; display: flex; align-items: center; justify-content: center; cursor: pointer; user-select: none; transition: transform .12s, background .2s; }
.tile:active { transform: scale(0.96); }
.tile.yes { border-color: #22c55e; background: #14331f; color: #22c55e; }
.tile.no  { border-color: #ef4444; background: #3a1717; color: #ef4444; }
.tile.chosen.yes { background: #22c55e; color: #052e16; }
.tile.chosen.no  { background: #ef4444; color: #450a0a; }
.tile .mark { position: absolute; font-size: 64px; transform: scale(0); transition: transform .25s cubic-bezier(.34,1.4,.64,1); }
.tile.chosen .mark { transform: scale(1); }
.tile.chosen .word { opacity: 0; }
.skip { align-self: center; color: var(--muted); font-size: 14px; background: none; border: 0; padding: 8px; cursor: pointer; }
.slide-in { animation: slidein .2s ease-out; }
@keyframes slidein { from { transform: translateX(40px); opacity: 0; } to { transform: none; opacity: 1; } }
.done-check { font-size: 96px; text-align: center; color: #22c55e; }
.row { display: flex; align-items: center; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid var(--border); gap: 12px; }
.pills { display: flex; gap: 6px; }
.pill { padding: 8px 12px; border-radius: 999px; border: 1px solid var(--border); background: transparent; color: var(--muted); font-size: 13px; cursor: pointer; }
.pill.on.yes { background: #14331f; border-color: #22c55e; color: #22c55e; }
.pill.on.no  { background: #3a1717; border-color: #ef4444; color: #ef4444; }
.pill.on.blank { border-color: var(--accent); color: var(--text); }
.ro { color: var(--muted); font-size: 14px; }
#toast { position: fixed; bottom: 24px; left: 50%; transform: translate(-50%, 80px); background: var(--surface); border: 1px solid var(--border); padding: 12px 18px; border-radius: var(--radius); transition: transform .25s; max-width: 90vw; }
#toast.show { transform: translate(-50%, 0); }
#toast.error { border-color: var(--error); }
#toast.ok { border-color: #22c55e; }
```

- [ ] **Step 2: Markup.** Four `section.view` elements with ids `view-home`, `view-wizard`, `view-done`, `view-edit`, plus `<div id="toast"></div>`:

```html
<header><h1>Habits</h1><p>One tap per habit. Skip leaves it blank.</p></header>

<section class="view active" id="view-home"><div class="card">
  <label class="lbl" for="date">Date</label>
  <input type="date" id="date">
  <div class="status" id="home-status">Loading…</div>
  <button class="btn" id="home-btn" disabled>Log habits</button>
  <a class="btn secondary" href="index.html" style="text-align:center;text-decoration:none">Health dashboard</a>
</div></section>

<section class="view" id="view-wizard"><div class="card" id="wizard-card">
  <div style="display:flex;justify-content:space-between;align-items:center">
    <button class="skip" id="wiz-back" aria-label="Back">‹ Back</button>
    <div class="progress" id="wiz-progress">1 of 11</div>
  </div>
  <div class="question" id="wiz-question"></div>
  <div class="tiles">
    <div class="tile yes" id="tile-yes" role="button" tabindex="0"><span class="word">Yes</span><span class="mark">✓</span></div>
    <div class="tile no"  id="tile-no"  role="button" tabindex="0"><span class="word">No</span><span class="mark">✕</span></div>
  </div>
  <button class="skip" id="wiz-skip">skip</button>
</div></section>

<section class="view" id="view-done"><div class="card">
  <div class="done-check">✓</div>
  <div class="question" id="done-title" style="text-align:center">Habits tracked</div>
  <div class="status" id="done-sub" style="text-align:center"></div>
  <button class="btn" id="done-back">Back</button>
  <button class="btn secondary" id="done-retry" hidden>Retry save</button>
</div></section>

<section class="view" id="view-edit"><div class="card">
  <div class="progress" id="edit-title"></div>
  <div id="edit-rows"></div>
  <div class="progress" style="margin-top:8px">Automatic</div>
  <div id="edit-derived"></div>
  <button class="btn secondary" id="edit-back">Back</button>
</div></section>
```

- [ ] **Step 3: Script.** State and API:

```js
'use strict';
const C = HabitsCore;
const WORKER = (location.hostname === 'localhost' || location.hostname === '127.0.0.1') ? location.origin : HABITS_CONFIG.workerUrl;
const $ = id => document.getElementById(id);
let defs = null, parsed = null, sha = null;
let date = C.todayLocal();
let wiz = { i: 0, answers: {} };
let queue = Promise.resolve();

const ls = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
             set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
             del(k) { try { localStorage.removeItem(k); } catch (e) {} } };

function toast(msg, kind) { const t = $('toast'); t.textContent = msg; t.className = 'show ' + (kind || ''); setTimeout(() => t.className = '', 3200); }
function show(id) { document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === id)); }

async function apiGetHabits() {
  const r = await fetch(WORKER + '/habits?t=' + Date.now(), { cache: 'no-store' });
  const j = await r.json();
  if (!r.ok) throw new Error('read failed ' + r.status + ': ' + (j.message || j.error || ''));
  parsed = C.parseCSV(j.content); sha = j.sha;
}
async function apiGetDefs() {
  const r = await fetch(WORKER + '/raw/definitions?t=' + Date.now(), { cache: 'no-store' });
  if (!r.ok) throw new Error('definitions failed ' + r.status);
  defs = JSON.parse(await r.text());
}
async function apiPut(content, message) {
  const r = await fetch(WORKER + '/habits', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content, sha, message }) });
  const j = await r.json().catch(() => ({}));
  if (r.status === 409) { const e = new Error('conflict'); e.conflict = true; throw e; }
  if (!r.ok) throw new Error('save failed ' + r.status + ': ' + (j.message || j.error || ''));
  sha = j.sha || sha;
}
/* Read-upsert-write; on a sha clash refetch and try once more. */
async function saveValues(values, message) {
  for (let attempt = 0; attempt < 2; attempt++) {
    if (attempt) await apiGetHabits();
    const out = C.upsertDay(parsed, date, values, C.localISO());
    try { await apiPut(C.serializeCSV(out.header, out.rows), message); parsed = out; return; }
    catch (e) { if (!e.conflict || attempt) throw e; }
  }
}
function rowFor(d) { return parsed && parsed.rows.find(r => r.date === d); }
```

Home:

```js
function renderHome() {
  $('date').value = date;
  const row = rowFor(date), btn = $('home-btn');
  if (!parsed) { $('home-status').textContent = 'Loading…'; btn.disabled = true; return; }
  btn.disabled = false;
  if (row && row.logged_at) { $('home-status').textContent = 'Logged at ' + C.formatLoggedAt(row.logged_at); btn.textContent = 'Edit habits'; btn.onclick = openEdit; }
  else { $('home-status').textContent = ls.get(C.draftKey(date)) ? 'In progress — tap to continue' : 'Not logged yet'; btn.textContent = 'Log habits'; btn.onclick = openWizard; }
}
$('date').addEventListener('change', e => { date = e.target.value || C.todayLocal(); renderHome(); });
```

Wizard (draft in localStorage, back keeps answers, skip = no key):

```js
function habitsToAsk() { return C.phoneHabits(defs); }
function openWizard() {
  const saved = ls.get(C.draftKey(date));
  wiz = saved ? JSON.parse(saved) : { i: 0, answers: {} };
  if (wiz.i >= habitsToAsk().length) wiz.i = 0;
  show('view-wizard'); renderQuestion();
}
function renderQuestion() {
  const list = habitsToAsk(), h = list[wiz.i];
  $('wiz-progress').textContent = (wiz.i + 1) + ' of ' + list.length;
  $('wiz-question').textContent = h.question || h.label + '?';
  ['tile-yes', 'tile-no'].forEach(id => $(id).classList.remove('chosen'));
  $('wiz-back').style.visibility = wiz.i ? 'visible' : 'hidden';
  const card = $('wizard-card'); card.classList.remove('slide-in'); void card.offsetWidth; card.classList.add('slide-in');
}
let answering = false;
function answer(value) {
  if (answering) return; answering = true;
  const list = habitsToAsk(), h = list[wiz.i];
  if (value !== null) wiz.answers[h.id] = value; else delete wiz.answers[h.id];
  if (value !== null) $(value === 'yes' ? 'tile-yes' : 'tile-no').classList.add('chosen');
  const next = () => {
    answering = false;
    wiz.i += 1;
    if (wiz.i < list.length) { ls.set(C.draftKey(date), JSON.stringify(wiz)); renderQuestion(); }
    else finishWizard();
  };
  setTimeout(next, value === null ? 0 : 320);
}
$('tile-yes').onclick = () => answer('yes');
$('tile-no').onclick = () => answer('no');
$('wiz-skip').onclick = () => answer(null);
$('wiz-back').onclick = () => { if (wiz.i > 0) { wiz.i -= 1; renderQuestion(); } };

async function finishWizard() {
  show('view-done');
  $('done-title').textContent = 'Saving…'; $('done-sub').textContent = ''; $('done-retry').hidden = true; $('done-back').disabled = true;
  try {
    await saveValues(wiz.answers, 'habits: phone log ' + date);
    ls.del(C.draftKey(date));
    $('done-title').textContent = 'Habits tracked for ' + C.formatDateLong(date);
    const n = Object.keys(wiz.answers).length, total = habitsToAsk().length;
    $('done-sub').textContent = n + ' of ' + total + ' answered' + (n < total ? ', the rest left blank' : '');
  } catch (e) {
    ls.set(C.draftKey(date), JSON.stringify(wiz));
    $('done-title').textContent = 'Not saved'; $('done-sub').textContent = e.message; $('done-retry').hidden = false;
    toast(e.message, 'error');
  }
  $('done-back').disabled = false;
}
$('done-retry').onclick = finishWizard;
$('done-back').onclick = () => { renderHome(); show('view-home'); };
```

Edit view (three-way pills; each change queued and saved; derived rows read-only):

```js
function openEdit() {
  const row = rowFor(date) || {};
  $('edit-title').textContent = C.formatDateLong(date) + ' · logged ' + C.formatLoggedAt(row.logged_at);
  const rows = $('edit-rows'); rows.innerHTML = '';
  habitsToAsk().forEach(h => {
    const div = document.createElement('div'); div.className = 'row';
    div.innerHTML = '<div>' + h.label + '</div><div class="pills"></div>';
    const pills = div.querySelector('.pills');
    [['yes', 'Yes'], ['no', 'No'], ['', '—']].forEach(([v, txt]) => {
      const b = document.createElement('button'); b.className = 'pill ' + (v || 'blank'); b.textContent = txt;
      b.dataset.v = v; b.dataset.id = h.id;
      if ((row[h.id] || '') === v) b.classList.add('on');
      b.onclick = () => setValue(h.id, v, pills);
      pills.appendChild(b);
    });
    rows.appendChild(div);
  });
  const der = $('edit-derived'); der.innerHTML = '';
  C.derivedHabits(defs).forEach(h => {
    const div = document.createElement('div'); div.className = 'row';
    div.innerHTML = '<div class="ro">' + h.label + '</div><div class="ro">' + (row[h.id] || '—') + '</div>';
    der.appendChild(div);
  });
  show('view-edit');
}
function setValue(id, v, pills) {
  pills.querySelectorAll('.pill').forEach(p => p.classList.toggle('on', p.dataset.v === v));
  queue = queue.then(() => saveValues({ [id]: v }, 'habits: phone edit ' + date + ' ' + id + '=' + (v || 'blank')))
    .then(() => toast('Saved', 'ok'))
    .catch(e => { toast(e.message, 'error'); openEdit(); });
}
$('edit-back').onclick = () => { renderHome(); show('view-home'); };
```

Init and resume:

```js
async function init() {
  renderHome();
  try { await apiGetDefs(); await apiGetHabits(); }
  catch (e) { $('home-status').textContent = 'Cannot reach the habit store: ' + e.message; toast(e.message, 'error'); return; }
  renderHome();
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && parsed) apiGetHabits().then(() => { if ($('view-home').classList.contains('active')) renderHome(); }).catch(() => {}); });
init();
```

- [ ] **Step 4: Browser verification with the dev worker.** Start `python tools/dev_worker.py` (background). Use the Browser pane (`preview_start` with url `http://127.0.0.1:8765/habits.html`) or Playwright at 375x812 and check, taking a screenshot of each view:
  1. Home shows today's date and "Not logged yet"; button enabled.
  2. Tap Log habits; answer Yes ×5, No ×3, skip one (question 9), Yes ×2. Progress counts 1 of 11 … 11 of 11. Chosen tile shows the mark before advancing.
  3. Done view: "Habits tracked for <Month D>", "10 of 11 answered, the rest left blank".
  4. Read the scratch CSV path printed by the dev worker; assert: last row has today's date, correct `day_of_week`, `made_bed=yes`, `read_nonfiction` blank, `logged_at` matches `^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$`, file ends with `\n`, no `\r`, header unchanged.
  5. Back → home says "Logged at h:mm am/pm", button "Edit habits". Tap it; flip `teeth` to No; scratch CSV updates; toast "Saved".
  6. Resume: reload mid-wizard (answer 3, reload, tap Log habits) → progress shows "4 of 11".
  7. Console has no errors (`read_console_messages` onlyErrors).
  Fix anything that fails, re-run. Stop the dev worker.

- [ ] **Step 5: Run both suites** `node --test tests/habits-core.test.js && python -m pytest tests/test_habits.py -q` → all pass.

- [ ] **Step 6: Commit**

```bash
git add habits.html
git commit -m "habits page: one-question-per-screen phone logger with edit view

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- habits.html
```

---

### Task 7: Docs — README, CONTEXT, HANDOFF

**Files:**
- Modify: `habits/README.md` (habit set table, new "Phone page" section, derived list)
- Modify: `CONTEXT.md` floor map (add row: "Log habits from the phone → `habits.html`, read `habits/README.md`")
- Create/overwrite: `HANDOFF.md` in `Health-Tracker`

- [ ] **Step 1: README.** In "The habit set": derived becomes 10 (add water, workout from Workout-Tracker-v2, calories on target with their rules from the spec); self-report becomes the 11 phone questions in order; note screentime is yes/no now; `workout` line: "derived from the Workout Tracker, blank if nothing logged, WHOOP's view in workout_whoop". Add section:

```markdown
## Phone page

`habits.html` (GitHub Pages) asks the 11 self-report habits one per screen
and writes the row through the Cloudflare Worker `habit-tracker-proxy`
(source in `cloudflare-worker/habits-worker.js`, token lives only in
Cloudflare). It stamps `logged_at`, never touches `note` or the audit log:
the commit message `habits: phone log <date>` is its audit trail. Skip
leaves a blank, never a no. Already-logged days open an edit list.

Local testing: `python tools/dev_worker.py` serves the page and a scratch
copy of `habits.csv` at http://127.0.0.1:8765/habits.html.

Concurrency: the phone commits to the remote; the 07:00 WHOOP step pulls
Health-Tracker before writing derived habits, then commits and pushes.
The GTD Year tab reads the local file, so it lags the phone until 07:00.
```

Update the "Files" table with `habits.html`, `habits-core.js`, `habits-config.js`, `tools/dev_worker.py`, `tests/habits-core.test.js`. Update the test count line.

- [ ] **Step 2: HANDOFF.md** — what was built, the Cloudflare step still owed by Auckie, and that `habits-config.js` may need the real Worker URL.

- [ ] **Step 3: Commit**

```bash
git add habits/README.md CONTEXT.md HANDOFF.md
git commit -m "docs: habit phone page, new derived habits, handoff

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" -- habits/README.md CONTEXT.md HANDOFF.md
```

---

## Self-review notes

- Spec coverage: habit set (T1), derivations + sources (T2), pull-first (T3), CSV format + upsert + questions (T4), Worker/config/manifest/icon/dev worker (T5), four views, draft resume, 409 retry, promise queue, visibilitychange (T6), README/concurrency notes (T7). Live phone test happens after Auckie's Cloudflare step, outside the plan.
- Names used across tasks: `HabitsCore.{parseCSV, serializeCSV, upsertDay, phoneHabits, derivedHabits, todayLocal, localISO, formatDateLong, formatLoggedAt, draftKey}`, `HABITS_CONFIG.workerUrl`, endpoints `/habits`, `/raw/definitions`, `_fetch_text`, `read_source_rows`, `prefill_water`, `prefill_workout_log`, `prefill_calories`, config keys `*_sources`, `calorie_tolerance_pct`, `source_fetch_timeout_s`.
