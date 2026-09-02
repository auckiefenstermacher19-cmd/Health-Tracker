"""
habits.py
---------
Daily habit log for Health Tracker.

Three commands:

    prefill  - report what WHOOP already knows for a date (workout, bed on time)
    log      - upsert one date's row from explicit key=value pairs
    show     - print recent rows

The split is deliberate: this script does NOT interpret free text. An agent
reads habits/definitions.json (labels + aliases), turns "made bed, both
vitamins, junk yes" into explicit --set flags, and this script does the
validated write. Parsing lives where judgement lives; storage stays dumb.

Design principles (mirrors consolidate.py)
-----------------------------------------
  * Blank and "no" are different values and always stay different. A habit you
    simply did not mention stays blank, so a quiet night never fabricates a
    failed streak.
  * Blanks never overwrite recorded data. Explicit values do, and the previous
    value is captured in the audit log.
  * Habit set and column order are read from habits/definitions.json - no
    hardcoded column names.
  * Staging file written first, then atomically renamed over the real one.
  * Every write appends an entry to logs/habits_audit.jsonl.

Exit codes
----------
  0 - success
  1 - failure (bad date, unknown habit id, unparseable value, write error)
"""

import argparse
import csv
import json
import os
import sys
import time as _time
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_DIR    = Path(__file__).resolve().parent
DEFS_PATH   = REPO_DIR / "habits" / "definitions.json"
HABITS_CSV  = REPO_DIR / "habits.csv"
LOG_DIR     = REPO_DIR / "logs"
AUDIT_LOG   = LOG_DIR / "habits_audit.jsonl"

# One writer at a time. The dashboard collector and the nightly agent both
# reach for habits.csv, and Windows will not replace a file another process
# holds open.
LOCK_PATH    = REPO_DIR / "habits.lock"
LOCK_WAIT_S  = 10.0
LOCK_STALE_S = 60.0

# The day a habit belongs to is Auckie's day, not the machine's.
DEFAULT_TZ  = "America/New_York"

META_COLS   = ["date", "day_of_week"]
TAIL_COLS   = ["logged_at", "note"]

TRUE_WORDS  = {"yes", "y", "true", "t", "1", "done"}
FALSE_WORDS = {"no", "n", "false", "f", "0", "missed", "skipped"}


# -- Definitions --------------------------------------------------------------

def die(msg):
    print("error: " + str(msg), file=sys.stderr)
    sys.exit(1)


def load_defs():
    if not DEFS_PATH.exists():
        die("definitions not found: " + str(DEFS_PATH))
    with DEFS_PATH.open(encoding="utf-8") as fh:
        defs = json.load(fh)
    if not defs.get("habits"):
        die("definitions.json contains no habits")
    return defs


def habit_ids(defs):
    return [h["id"] for h in defs["habits"]]


def habit_by_id(defs, hid):
    for h in defs["habits"]:
        if h["id"] == hid:
            return h
    return None


def columns(defs):
    return META_COLS + habit_ids(defs) + TAIL_COLS


def daily_habit_ids(defs):
    """The habits the nightly check-in should actually ask about.

    Retired habits keep their column so their history survives, and weekly ones
    are real but do not belong in a nightly prompt. Both stay writable; they are
    just not questions.
    """
    return [h["id"] for h in defs["habits"]
            if h.get("active", True) and h.get("cadence", "daily") == "daily"]


# -- Value normalisation ------------------------------------------------------

def normalise(habit, raw):
    """Return the stored string form of raw for habit, or raise ValueError.

    Empty input returns "" - a deliberate no-op that the log command refuses to
    let overwrite existing data.
    """
    val = str(raw).strip()
    if val == "":
        return ""

    kind = habit.get("type", "binary")

    if kind == "binary":
        low = val.lower()
        if low in TRUE_WORDS:
            return "yes"
        if low in FALSE_WORDS:
            return "no"
        raise ValueError(habit["id"] + ": expected yes/no, got " + repr(val))

    if kind == "text":
        parts = [p.strip() for p in val.split(";") if p.strip()]
        choices = habit.get("choices")
        if choices:
            bad = [p for p in parts if p not in choices]
            if bad:
                raise ValueError(habit["id"] + ": not in choices: " + ", ".join(bad))
        return "; ".join(parts)

    try:
        num = float(val)
    except ValueError:
        raise ValueError(habit["id"] + ": expected a number, got " + repr(val))
    if num < 0:
        raise ValueError(habit["id"] + ": cannot be negative, got " + repr(val))
    if kind == "count":
        if num != int(num):
            raise ValueError(habit["id"] + ": expected a whole number, got " + repr(val))
        return str(int(num))
    return "%g" % num


def parse_date(s, tz=DEFAULT_TZ):
    try:
        zone = ZoneInfo(tz)
    except (KeyError, ValueError, TypeError):
        # ZoneInfoNotFoundError is a KeyError; a malformed key raises ValueError.
        die("unknown timezone " + repr(tz))
    today = datetime.now(zone).date()
    if s is None or s.strip().lower() in ("", "today"):
        return today
    if s.strip().lower() == "yesterday":
        return today - timedelta(days=1)
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        die("bad date " + repr(s) + " - use YYYY-MM-DD, 'today', or 'yesterday'")


# -- WHOOP prefill ------------------------------------------------------------

def find_whoop_csv(defs):
    for rel in defs["config"]["whoop_sources"]:
        p = (REPO_DIR / rel).resolve()
        if p.exists():
            return p
    return None


def whoop_row_for(path, day):
    """Return the WHOOP row dict for day, or None."""
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if (row.get("date") or "").strip() == day.isoformat():
                return row
    return None


def whoop_latest_date(path):
    latest = None
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            d = (row.get("date") or "").strip()
            if len(d) == 10 and (latest is None or d > latest):
                latest = d
    return latest


def to_local_time(iso_utc):
    """'2026-08-26T02:38:04.820Z' -> local-time `time` object, or None."""
    s = (iso_utc or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().time()


def bed_on_time(local_start, cutoff):
    """Was a sleep starting at local_start on the right side of cutoff?

    Bedtimes straddle midnight, so raw clock comparison is wrong: 00:40 is
    later than 23:30, not earlier. Both times are folded onto an axis running
    from noon so that evening and after-midnight starts order correctly.
    """
    def since_noon(t):
        mins = t.hour * 60 + t.minute
        return mins - 720 if mins >= 720 else mins + 720

    return since_noon(local_start) < since_noon(cutoff)


def _num(row, field):
    """float(row[field]), or None when absent or unparseable."""
    raw = (row.get(field) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def find_meal_log(defs):
    for rel in defs["config"].get("meal_log_sources", []):
        p = (REPO_DIR / rel).resolve()
        if p.exists():
            return p
    return None


def prefill_meal_log(defs, day, known, notes):
    """Did the food log gain any entry for this day?

    Unlike WHOOP, this file is the system of record rather than a synced copy,
    so a day with no rows is a real "did not log", not a missing feed.
    """
    path = find_meal_log(defs)
    if path is None:
        notes.append("No meal log found - logged_food left blank.")
        return

    field = defs["config"].get("meal_log_date_field", "log_date")
    target = day.isoformat()
    count = 0
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if field not in (reader.fieldnames or []):
            notes.append("Meal log has no " + field
                         + " column - logged_food left blank.")
            return
        for row in reader:
            if (row.get(field) or "").strip() == target:
                count += 1

    known["logged_food"] = "yes" if count else "no"
    notes.append("Meal log: " + str(count) + " entries for " + target
                 + " -> logged_food=" + known["logged_food"])


def prefill_whoop(defs, day, known, notes):
    """Fill workout and bed_on_time from WHOOP where the data supports it."""
    path = find_whoop_csv(defs)
    if path is None:
        notes.append("No WHOOP CSV found - workout and bed on time left blank.")
        return

    notes.append("WHOOP source: " + str(path))

    latest = whoop_latest_date(path)
    if latest:
        stale_days = (day - datetime.strptime(latest, "%Y-%m-%d").date()).days
        limit = defs["config"].get("whoop_stale_after_days", 2)
        if stale_days > limit:
            notes.append(
                "WHOOP data is stale - latest row is " + latest + ", "
                + str(stale_days) + " days before " + day.isoformat()
                + ". Sync may be broken."
            )

    row = whoop_row_for(path, day)
    if row is None:
        notes.append("No WHOOP row for " + day.isoformat()
                     + " - workout and bed on time stay blank.")
        return

    # Workout: a present row carrying cycle data means a blank workout_count is
    # a real "no workout", not a missing sync.
    wc = (row.get("workout_count") or "").strip()
    has_cycle = (row.get("day_strain") or "").strip() != ""
    if wc:
        try:
            known["workout"] = "yes" if float(wc) > 0 else "no"
            known["workout_whoop"] = known["workout"]
        except ValueError:
            notes.append("workout_count unparseable (" + repr(wc)
                         + ") - leaving workout blank.")
    elif has_cycle:
        known["workout"] = "no"
        known["workout_whoop"] = "no"
        notes.append("No workout recorded by WHOOP for this day.")
    else:
        notes.append("WHOOP row has no cycle data - workout left blank.")

    # Bed on time: sleep_start is UTC, compared against a local-clock target.
    cutoff_s = defs["config"].get("bed_on_time_before", "23:30")
    try:
        hh, mm = [int(x) for x in cutoff_s.split(":")]
        cutoff = time(hh, mm)
    except (ValueError, TypeError):
        die("bad bed_on_time_before in definitions.json: " + repr(cutoff_s))

    local = to_local_time(row.get("sleep_start"))
    if local is None:
        notes.append("No sleep_start in WHOOP - bed on time left blank.")
    else:
        known["bed_on_time"] = "yes" if bed_on_time(local, cutoff) else "no"
        notes.append(
            "sleep_start " + local.strftime("%H:%M") + " local vs target "
            + cutoff_s + " -> bed_on_time=" + known["bed_on_time"]
        )

    # Slept 7+: WHOOP has no total-sleep column, so the stages are summed. A
    # missing stage would understate the total and manufacture a false "no", so
    # all three are required.
    stages = [_num(row, f) for f in
              ("light_sleep_hrs", "slow_wave_sleep_hrs", "rem_sleep_hrs")]
    if all(v is not None for v in stages):
        total = sum(stages)
        target = float(defs["config"].get("sleep_hours_target", 7.0))
        known["slept_7h"] = "yes" if total >= target else "no"
        notes.append("asleep %.2fh vs target %.1fh -> slept_7h=%s"
                     % (total, target, known["slept_7h"]))
    else:
        notes.append("Incomplete sleep stages - slept_7h left blank.")

    strain = _num(row, "day_strain")
    if strain is None:
        notes.append("No day_strain - active_day left blank.")
    else:
        floor = float(defs["config"].get("active_day_strain_min", 6.0))
        known["active_day"] = "yes" if strain >= floor else "no"
        notes.append("day_strain %.2f vs floor %.1f -> active_day=%s"
                     % (strain, floor, known["active_day"]))

    consistency = _num(row, "sleep_consistency_pct")
    if consistency is None:
        notes.append("No sleep_consistency_pct - consistent_wake left blank.")
    else:
        floor = float(defs["config"].get("consistent_wake_min_pct", 70))
        known["consistent_wake"] = "yes" if consistency >= floor else "no"
        notes.append("sleep_consistency %.0f%% vs floor %.0f%% -> consistent_wake=%s"
                     % (consistency, floor, known["consistent_wake"]))


def find_item_status(defs):
    for rel in defs["config"].get("item_status_sources", []):
        p = (REPO_DIR / rel).resolve()
        if p.exists():
            return p
    return None


def prefill_learning(defs, day, known, notes):
    """Was anything in the ai-learning dashboard marked viewed on this day?

    Reads item-status.json directly rather than the dashboard's built state,
    because that file changes the instant an item is clicked while the state is
    only rebuilt on a poll.

    `viewed` without a `viewed_at` does not count. Those are items marked before
    the stamp existed, and guessing a date for them would invent history.
    """
    path = find_item_status(defs)
    if path is None:
        notes.append("No ai-learning item status found - learning_consumed left blank.")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, ValueError):
        notes.append("ai-learning item status unreadable - learning_consumed left blank.")
        return
    if not isinstance(data, dict):
        notes.append("ai-learning item status has an unexpected shape "
                     "- learning_consumed left blank.")
        return

    target = day.isoformat()
    count = 0
    for entry in data.values():
        if not isinstance(entry, dict) or not entry.get("viewed"):
            continue
        stamp = entry.get("viewed_at")
        if isinstance(stamp, str) and stamp[:10] == target:
            count += 1

    known["learning_consumed"] = "yes" if count else "no"
    notes.append("ai-learning: " + str(count) + " items viewed on " + target
                 + " -> learning_consumed=" + known["learning_consumed"])


def prefill(defs, day):
    """Everything the machine already knows for `day`.

    Never guesses: a source that cannot answer leaves the habit blank rather
    than defaulting it to "no".
    """
    known, notes = {}, []
    prefill_whoop(defs, day, known, notes)
    prefill_meal_log(defs, day, known, notes)
    prefill_learning(defs, day, known, notes)
    return known, notes


# -- Read / write -------------------------------------------------------------

def read_rows(defs):
    cols = columns(defs)
    if not HABITS_CSV.exists():
        return {}
    rows = {}
    with HABITS_CSV.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            d = (row.get("date") or "").strip()
            if d:
                rows[d] = dict((c, (row.get(c) or "")) for c in cols)
    return rows


def _replace_with_retry(src, dst, attempts=10):
    """os.replace with backoff. Windows refuses to replace a file another
    process has open (the dashboard collector reads habits.csv every 5 s)."""
    for i in range(attempts):
        try:
            os.replace(str(src), str(dst))
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            _time.sleep(0.05 + 0.01 * i)


def _acquire_lock():
    """Exclusive-create a lock file, waiting for a live holder to finish.

    A lock older than LOCK_STALE_S belonged to a process that died mid-write;
    reclaiming it is safer than wedging every later write for good.
    """
    deadline = _time.time() + LOCK_WAIT_S
    while True:
        try:
            fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            return
        except FileExistsError:
            try:
                age = _time.time() - LOCK_PATH.stat().st_mtime
            except OSError:
                age = 0
            if age > LOCK_STALE_S:
                LOCK_PATH.unlink(missing_ok=True)
                continue
            if _time.time() > deadline:
                die("habits.csv is locked by another writer (habits.lock); "
                    "try again in a moment")
            _time.sleep(0.1)


def _release_lock():
    LOCK_PATH.unlink(missing_ok=True)


def write_rows(defs, rows, locked=False):
    """Rewrite habits.csv from `rows`.

    Pass locked=True when the caller already holds the lock across its own
    read-modify-write; otherwise the lock is taken here.
    """
    cols = columns(defs)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # Per-pid staging: two writers must never share one scratch file.
    staging = HABITS_CSV.parent / ("habits.staging.%d.csv" % os.getpid())
    if not locked:
        _acquire_lock()
    try:
        with staging.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for d in sorted(rows):                  # oldest first
                w.writerow(dict((c, rows[d].get(c, "")) for c in cols))

        # Validate the staging file parses and holds every row before it goes live.
        with staging.open(newline="", encoding="utf-8-sig") as fh:
            got = sum(1 for _ in csv.DictReader(fh))
        if got != len(rows):
            staging.unlink(missing_ok=True)
            die("staging validation failed: wrote " + str(got)
                + " rows, expected " + str(len(rows)))

        try:
            _replace_with_retry(staging, HABITS_CSV)
        except PermissionError:
            staging.unlink(missing_ok=True)
            die("habits.csv is open in another program; close it and retry")
    finally:
        if not locked:
            _release_lock()


def audit(entry):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry["ts"] = datetime.now(timezone.utc).isoformat()
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# -- Commands -----------------------------------------------------------------

def cmd_prefill(args):
    defs = load_defs()
    day = parse_date(args.date, tz=args.tz)
    known, notes = prefill(defs, day)
    existing = read_rows(defs).get(day.isoformat(), {})
    ids = habit_ids(defs)
    unknown = [h for h in daily_habit_ids(defs)
               if h not in known and not (existing.get(h) or "").strip()]
    out = {
        "date": day.isoformat(),
        "day_of_week": day.strftime("%A"),
        "known": known,
        "already_logged": dict((k, v) for k, v in existing.items()
                               if k in ids and v),
        "still_unknown": unknown,
        "notes": notes,
    }
    print(json.dumps(out, indent=2))


def cmd_log(args):
    defs = load_defs()
    day = parse_date(args.date, tz=args.tz)
    key = day.isoformat()
    ids = set(habit_ids(defs))

    incoming = {}
    if args.json:
        try:
            incoming.update(json.loads(args.json))
        except json.JSONDecodeError as exc:
            die("--json is not valid JSON: " + str(exc))
    for pair in args.set or []:
        if "=" not in pair:
            die("--set expects habit=value, got " + repr(pair))
        k, v = pair.split("=", 1)
        incoming[k.strip()] = v

    prefilled = set()
    if args.whoop:
        known, notes = prefill(defs, day)
        # Only what the sources answered that this invocation did not.
        prefilled = set(known) - set(incoming)
        for k, v in known.items():
            incoming.setdefault(k, v)     # explicit values always win
        for n in notes:
            print("note: " + n, file=sys.stderr)

    if not incoming:
        die("nothing to log - pass --set, --json, or --whoop")

    unknown_keys = sorted(set(incoming) - ids)
    if unknown_keys:
        die("unknown habit id(s): " + ", ".join(unknown_keys))

    # The lock spans read and write: another writer landing in between would
    # have its row silently dropped by this one's rewrite.
    _acquire_lock()
    try:
        rows = read_rows(defs)
        row = rows.get(key) or dict((c, "") for c in columns(defs))
        row["date"] = key
        row["day_of_week"] = day.strftime("%A")

        changes = {}
        for hid, raw in incoming.items():
            habit = habit_by_id(defs, hid)
            try:
                val = normalise(habit, raw)
            except ValueError as exc:
                die(str(exc))
            prev = (row.get(hid) or "").strip()
            if hid in prefilled and prev:
                # --whoop fills blanks. It never argues with something already
                # recorded - that disagreement is the whole point of keeping
                # workout and workout_whoop apart.
                print("note: kept existing " + hid + "=" + prev
                      + " (--whoop fills blanks only)", file=sys.stderr)
                continue
            if val == "":
                # Blanks never erase recorded data.
                if prev:
                    print("note: kept existing " + hid + "=" + prev
                          + " (blank ignored)", file=sys.stderr)
                continue
            if val != prev:
                changes[hid] = {"from": prev, "to": val}
                row[hid] = val

        if args.note:
            row["note"] = args.note
        row["logged_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

        rows[key] = row
        write_rows(defs, rows, locked=True)
    finally:
        _release_lock()
    audit({"action": "log", "date": key, "changes": changes,
           "source": "whoop+manual" if args.whoop else "manual"})

    if changes:
        for hid in changes:
            ch = changes[hid]
            arrow = (ch["from"] or "(blank)") + " -> " + ch["to"]
            print(habit_by_id(defs, hid)["label"] + ": " + arrow)
    else:
        print("no changes - every value already matched what was stored")

    still = [h for h in daily_habit_ids(defs) if not (row.get(h) or "").strip()]
    if still:
        labels = [habit_by_id(defs, h)["label"] for h in still]
        print("still blank (" + str(len(still)) + "): " + ", ".join(labels))


def cmd_show(args):
    defs = load_defs()
    rows = read_rows(defs)
    if not rows:
        print("no habit rows logged yet")
        return
    ids = habit_ids(defs)
    if args.date:
        keys = [parse_date(args.date, tz=args.tz).isoformat()]
    else:
        keys = sorted(rows)[-args.last:]
    for k in keys:
        row = rows.get(k)
        if not row:
            print(k + ": no row")
            continue
        done = [habit_by_id(defs, h)["label"] for h in ids
                if (row.get(h) or "") == "yes"]
        miss = [habit_by_id(defs, h)["label"] for h in ids
                if (row.get(h) or "") == "no"]
        blank = sum(1 for h in ids if not (row.get(h) or "").strip())
        print(k + " " + row.get("day_of_week", ""))
        print("  yes (" + str(len(done)) + "): " + (", ".join(done) or "-"))
        print("  no  (" + str(len(miss)) + "): " + (", ".join(miss) or "-"))
        print("  blank: " + str(blank))


def main():
    ap = argparse.ArgumentParser(description="Daily habit log")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prefill", help="what WHOOP already knows for a date")
    p.add_argument("--date", default="today")
    p.add_argument("--tz", default=DEFAULT_TZ)
    p.set_defaults(func=cmd_prefill)

    p = sub.add_parser("log", help="upsert one date's row")
    p.add_argument("--date", default="today")
    p.add_argument("--set", action="append", metavar="habit=value")
    p.add_argument("--json", metavar="JSON", help='e.g. {"made_bed":"yes"}')
    p.add_argument("--whoop", action="store_true",
                   help="fill workout / bed_on_time from WHOOP where not given")
    p.add_argument("--note", help="free-text note for the day")
    p.add_argument("--tz", default=DEFAULT_TZ)
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("show", help="print recent rows")
    p.add_argument("--date")
    p.add_argument("--last", type=int, default=7)
    p.add_argument("--tz", default=DEFAULT_TZ)
    p.set_defaults(func=cmd_show)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
