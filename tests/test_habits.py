"""Tests for habits.py - the parts where a wrong answer corrupts the log."""

import csv
import importlib.util
import json
import os
import sys
import time as _time
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("habits", REPO / "habits.py")
habits = importlib.util.module_from_spec(spec)
sys.modules["habits"] = habits
spec.loader.exec_module(habits)


@pytest.fixture
def defs():
    return habits.load_defs()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Redirect every write to tmp_path so the real habits.csv is untouched."""
    monkeypatch.setattr(habits, "HABITS_CSV", tmp_path / "habits.csv")
    monkeypatch.setattr(habits, "LOCK_PATH", tmp_path / "habits.lock")
    monkeypatch.setattr(habits, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(habits, "AUDIT_LOG", tmp_path / "logs" / "habits_audit.jsonl")
    return tmp_path


# -- bedtime across midnight --------------------------------------------------

@pytest.mark.parametrize("start,expected", [
    ((22, 38), True),    # comfortably before target
    ((23, 29), True),    # one minute inside
    ((23, 31), False),   # one minute late
    ((0, 40), False),    # after midnight is late, not early
    ((2, 38), False),    # very late
    ((12, 1), True),     # early afternoon nap start still counts as "before"
])
def test_bed_on_time_handles_midnight(start, expected):
    """A 00:40 bedtime is later than 23:30, not 22 hours earlier."""
    assert habits.bed_on_time(time(*start), time(23, 30)) is expected


def test_bed_on_time_with_after_midnight_target():
    """A target past midnight still orders correctly against evening starts."""
    assert habits.bed_on_time(time(23, 0), time(0, 30)) is True
    assert habits.bed_on_time(time(1, 0), time(0, 30)) is False


def test_utc_sleep_start_converts_to_local():
    assert habits.to_local_time("2026-08-26T02:38:04.820Z") is not None
    assert habits.to_local_time("") is None
    assert habits.to_local_time("not-a-timestamp") is None


# -- value normalisation ------------------------------------------------------

def test_binary_accepts_common_words(defs):
    made_bed = habits.habit_by_id(defs, "made_bed")
    for word in ("yes", "Y", "TRUE", "1", "done"):
        assert habits.normalise(made_bed, word) == "yes"
    for word in ("no", "N", "false", "0", "skipped"):
        assert habits.normalise(made_bed, word) == "no"


def test_binary_rejects_ambiguous_input(defs):
    made_bed = habits.habit_by_id(defs, "made_bed")
    with pytest.raises(ValueError):
        habits.normalise(made_bed, "sort of")


def test_numeric_habits_reject_negatives_and_nonsense(defs):
    screen = habits.habit_by_id(defs, "screentime")
    with pytest.raises(ValueError):
        habits.normalise(screen, "-1")
    with pytest.raises(ValueError):
        habits.normalise(screen, "ages")


def test_count_type_requires_a_whole_number():
    """No count habit is active today, but the rule guards the next one."""
    fake = {"id": "glasses", "type": "count"}
    assert habits.normalise(fake, "5") == "5"
    with pytest.raises(ValueError):
        habits.normalise(fake, "2.5")


def test_hours_keeps_fractions(defs):
    screen = habits.habit_by_id(defs, "screentime")
    assert habits.normalise(screen, "1.5") == "1.5"
    assert habits.normalise(screen, "2") == "2"


def test_empty_value_is_a_noop_not_a_no(defs):
    """The whole point: unmentioned is not the same as failed."""
    made_bed = habits.habit_by_id(defs, "made_bed")
    assert habits.normalise(made_bed, "") == ""
    assert habits.normalise(made_bed, "   ") == ""


# -- round trip ---------------------------------------------------------------

def _log(monkeypatch, **kw):
    args = type("A", (), {"date": "2026-08-26", "set": None, "json": None,
                          "whoop": False, "note": None,
                          "tz": habits.DEFAULT_TZ})()
    for k, v in kw.items():
        setattr(args, k, v)
    habits.cmd_log(args)


def test_log_writes_and_reads_back(sandbox, defs, monkeypatch):
    _log(monkeypatch, set=["made_bed=yes", "water=yes", "no_junk=no"])
    rows = habits.read_rows(defs)
    row = rows["2026-08-26"]
    assert row["made_bed"] == "yes"
    assert row["water"] == "yes"
    assert row["no_junk"] == "no"
    assert row["day_of_week"] == "Wednesday"
    # Everything untouched stays blank, not "no".
    assert row["read_fiction"] == ""


def test_blank_never_overwrites_recorded_value(sandbox, defs, monkeypatch):
    _log(monkeypatch, set=["made_bed=yes"])
    _log(monkeypatch, set=["made_bed="])
    assert habits.read_rows(defs)["2026-08-26"]["made_bed"] == "yes"


def test_explicit_correction_overwrites(sandbox, defs, monkeypatch):
    _log(monkeypatch, set=["made_bed=yes"])
    _log(monkeypatch, set=["made_bed=no"])
    assert habits.read_rows(defs)["2026-08-26"]["made_bed"] == "no"


def test_second_log_merges_rather_than_replacing_the_row(sandbox, defs, monkeypatch):
    _log(monkeypatch, set=["made_bed=yes"])
    _log(monkeypatch, set=["water=yes"])
    row = habits.read_rows(defs)["2026-08-26"]
    assert row["made_bed"] == "yes" and row["water"] == "yes"


def test_unknown_habit_id_is_refused(sandbox, monkeypatch):
    with pytest.raises(SystemExit):
        _log(monkeypatch, set=["brushed_dog=yes"])


def test_rows_are_written_oldest_first(sandbox, defs, monkeypatch):
    _log(monkeypatch, date="2026-08-26", set=["made_bed=yes"])
    _log(monkeypatch, date="2026-08-24", set=["made_bed=no"])
    with habits.HABITS_CSV.open(newline="", encoding="utf-8-sig") as fh:
        dates = [r["date"] for r in csv.DictReader(fh)]
    assert dates == ["2026-08-24", "2026-08-26"]


def test_audit_log_records_the_change(sandbox, monkeypatch):
    _log(monkeypatch, set=["made_bed=yes"])
    entries = [json.loads(l) for l in habits.AUDIT_LOG.read_text().splitlines()]
    assert entries[-1]["changes"]["made_bed"] == {"from": "", "to": "yes"}


def test_no_staging_file_survives_a_write(sandbox, monkeypatch):
    _log(monkeypatch, set=["made_bed=yes"])
    assert not list(sandbox.glob("habits.staging.*.csv"))


# -- dates --------------------------------------------------------------------

def test_bad_date_exits():
    with pytest.raises(SystemExit):
        habits.parse_date("08/26/2026")


# -- definitions integrity ----------------------------------------------------

def test_original_spreadsheet_habits_survive_in_order(defs):
    """New habits may be appended, but the backfilled 14 must not shift.

    Their order is the CSV column order, and the March backfill was written
    against it.
    """
    original = [
        "made_bed", "workout", "morning_vitamins", "shower_teeth", "water",
        "read_fiction", "read_nonfiction", "bed_on_time", "night_vitamins",
        "no_junk", "no_fap", "screentime", "clean_sink", "reset_house",
    ]
    assert habits.habit_ids(defs)[:len(original)] == original


def test_added_habit_leaves_older_rows_blank_not_no(sandbox, defs, monkeypatch):
    """Adding a habit must not retroactively mark past days as failures."""
    _log(monkeypatch, date="2026-08-26", set=["made_bed=yes"])
    row = habits.read_rows(defs)["2026-08-26"]
    assert row["logged_food"] == ""


def test_habit_ids_are_unique(defs):
    ids = habits.habit_ids(defs)
    assert len(ids) == len(set(ids))


# -- derived sources ----------------------------------------------------------
# Each source answers only what its data supports. A source that cannot answer
# leaves the habit blank, because a wrong "no" is worse than an empty cell.

def _whoop(tmp_path, monkeypatch, **fields):
    row = {"date": "2026-08-26", "day_strain": "", "workout_count": "",
           "sleep_start": "", "light_sleep_hrs": "", "slow_wave_sleep_hrs": "",
           "rem_sleep_hrs": "", "sleep_consistency_pct": ""}
    row.update(fields)
    path = tmp_path / "whoop.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        w.writeheader()
        w.writerow(row)
    monkeypatch.setattr(habits, "find_whoop_csv", lambda defs: path)
    return path


def _run_whoop(defs, tmp_path, monkeypatch, **fields):
    _whoop(tmp_path, monkeypatch, **fields)
    known, notes = {}, []
    habits.prefill_whoop(defs, date(2026, 8, 26), known, notes)
    return known


def test_slept_7h_needs_all_three_sleep_stages(defs, tmp_path, monkeypatch):
    """Total sleep is the sum of the stages; a missing stage understates it."""
    known = _run_whoop(defs, tmp_path, monkeypatch, light_sleep_hrs="4",
                       slow_wave_sleep_hrs="2", rem_sleep_hrs="1.5")
    assert known["slept_7h"] == "yes"

    known = _run_whoop(defs, tmp_path, monkeypatch, light_sleep_hrs="4",
                       slow_wave_sleep_hrs="1", rem_sleep_hrs="1")
    assert known["slept_7h"] == "no"

    known = _run_whoop(defs, tmp_path, monkeypatch, light_sleep_hrs="4",
                       slow_wave_sleep_hrs="2")
    assert "slept_7h" not in known


def test_active_day_uses_the_strain_threshold(defs, tmp_path, monkeypatch):
    assert _run_whoop(defs, tmp_path, monkeypatch,
                      day_strain="9.1")["active_day"] == "yes"
    assert _run_whoop(defs, tmp_path, monkeypatch,
                      day_strain="4.2")["active_day"] == "no"


def test_active_day_blank_when_strain_is_missing(defs, tmp_path, monkeypatch):
    """A day WHOOP did not score is not a lazy day."""
    assert "active_day" not in _run_whoop(defs, tmp_path, monkeypatch)


def test_consistent_wake_uses_the_percentage(defs, tmp_path, monkeypatch):
    assert _run_whoop(defs, tmp_path, monkeypatch,
                      sleep_consistency_pct="82")["consistent_wake"] == "yes"
    assert _run_whoop(defs, tmp_path, monkeypatch,
                      sleep_consistency_pct="41")["consistent_wake"] == "no"


def test_unparseable_whoop_numbers_leave_the_habit_blank(defs, tmp_path, monkeypatch):
    known = _run_whoop(defs, tmp_path, monkeypatch, day_strain="n/a",
                       sleep_consistency_pct="--")
    assert "active_day" not in known and "consistent_wake" not in known


def _status_file(tmp_path, monkeypatch, payload):
    path = tmp_path / "item-status.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(habits, "find_item_status", lambda defs: path)
    return path


def _run_learning(defs, tmp_path, monkeypatch, payload, day=date(2026, 8, 26)):
    _status_file(tmp_path, monkeypatch, payload)
    known, notes = {}, []
    habits.prefill_learning(defs, day, known, notes)
    return known


def test_learning_counts_an_item_viewed_that_day(defs, tmp_path, monkeypatch):
    known = _run_learning(defs, tmp_path, monkeypatch,
                          {"a": {"viewed": True, "viewed_at": "2026-08-26T20:11:00-04:00"}})
    assert known["learning_consumed"] == "yes"


def test_learning_ignores_a_different_day(defs, tmp_path, monkeypatch):
    known = _run_learning(defs, tmp_path, monkeypatch,
                          {"a": {"viewed": True, "viewed_at": "2026-08-25T20:11:00-04:00"}})
    assert known["learning_consumed"] == "no"


def test_learning_ignores_viewed_without_a_stamp(defs, tmp_path, monkeypatch):
    """Items marked viewed before viewed_at existed have no date to trust."""
    known = _run_learning(defs, tmp_path, monkeypatch, {"a": {"viewed": True}})
    assert known["learning_consumed"] == "no"


def test_learning_ignores_saved_and_archived(defs, tmp_path, monkeypatch):
    """Saving something for later is not reading it."""
    known = _run_learning(defs, tmp_path, monkeypatch,
                          {"a": {"saved": True, "archived": True}})
    assert known["learning_consumed"] == "no"


def test_learning_blank_when_the_status_file_is_missing(defs, monkeypatch):
    monkeypatch.setattr(habits, "find_item_status", lambda defs: None)
    known, notes = {}, []
    habits.prefill_learning(defs, date(2026, 8, 26), known, notes)
    assert "learning_consumed" not in known


def test_learning_survives_a_corrupt_status_file(defs, tmp_path, monkeypatch):
    path = tmp_path / "item-status.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(habits, "find_item_status", lambda defs: path)
    known, notes = {}, []
    habits.prefill_learning(defs, date(2026, 8, 26), known, notes)
    assert "learning_consumed" not in known


# -- active / cadence ---------------------------------------------------------

def test_retired_habit_keeps_its_column_and_its_history(defs):
    """Shower + Teeth cannot be un-merged, so its March data must survive."""
    retired = habits.habit_by_id(defs, "shower_teeth")
    assert retired["active"] is False
    assert "shower_teeth" in habits.columns(defs)
    rows = habits.read_rows(defs)
    assert rows["2026-03-23"]["shower_teeth"] == "no"


def test_nightly_prompt_skips_retired_and_weekly_habits(defs):
    asked = habits.daily_habit_ids(defs)
    assert "shower_teeth" not in asked      # retired
    assert "clean_sink" not in asked        # weekly
    assert "reset_house" not in asked       # weekly
    assert "shower" in asked and "teeth" in asked


def test_retired_habit_can_still_be_written_explicitly(sandbox, defs, monkeypatch):
    """Not asked is not the same as refused - old rows stay correctable."""
    _log(monkeypatch, set=["shower_teeth=yes"])
    assert habits.read_rows(defs)["2026-08-26"]["shower_teeth"] == "yes"


def test_water_is_now_a_yes_no(defs):
    """It was a count with zero entries in its entire life."""
    water = habits.habit_by_id(defs, "water")
    assert water["type"] == "binary"
    assert habits.normalise(water, "yes") == "yes"


# -- text habits ---------------------------------------------------------------

def test_text_kind_trims_and_rejoins():
    assert habits.normalise({"id": "reach_out", "type": "text"},
                            " Dad;Matt Gunter ; ") == "Dad; Matt Gunter"


def test_text_kind_choices_enforced():
    h = {"id": "warning_signs", "type": "text",
         "choices": ["Anger", "Doomscrolling", "none"]}
    assert habits.normalise(h, "Anger;Doomscrolling") == "Anger; Doomscrolling"
    assert habits.normalise(h, "none") == "none"
    with pytest.raises(ValueError):
        habits.normalise(h, "Anger;Hunger")


def test_new_plan_habits_defined_and_workout_is_self(defs):
    ids = set(habits.habit_ids(defs))
    for hid in ["devices_off_9pm", "reach_out", "outbound", "conversations",
                "posts", "warning_signs", "sunday_review", "dj_hour", "mrr",
                "bodyweight", "books_finished", "workout_whoop"]:
        assert hid in ids, hid
    assert habits.habit_by_id(defs, "workout")["source"] == "self"
    assert habits.habit_by_id(defs, "workout_whoop")["source"] == "whoop"
    assert "none" in habits.habit_by_id(defs, "warning_signs")["choices"]


# -- the day is Eastern ---------------------------------------------------------

def test_parse_date_today_and_yesterday_use_the_zone():
    eastern_today = datetime.now(ZoneInfo("America/New_York")).date()
    assert habits.parse_date("today") == eastern_today
    assert habits.parse_date("yesterday") == eastern_today - timedelta(days=1)
    assert (habits.parse_date("today", tz="Pacific/Kiritimati")
            == datetime.now(ZoneInfo("Pacific/Kiritimati")).date())
    assert habits.parse_date("2026-08-26") == date(2026, 8, 26)


def test_bad_timezone_exits_instead_of_tracebacking():
    with pytest.raises(SystemExit):
        habits.parse_date("today", tz="Bogus/Zone")


# -- writes are locked and the rename retries ----------------------------------

def test_write_rows_uses_pid_staging_and_lock(defs, sandbox):
    lock = sandbox / "habits.lock"
    habits.write_rows(defs, {"2026-09-01": {"date": "2026-09-01",
                                            "day_of_week": "Tuesday"}})
    assert (sandbox / "habits.csv").exists()
    assert not list(sandbox.glob("habits.staging.*.csv"))   # staging cleaned up
    assert not lock.exists()                                # lock released


def test_stale_lock_is_reclaimed(defs, sandbox):
    lock = sandbox / "habits.lock"
    lock.write_text("1", encoding="utf-8")
    old = _time.time() - 120
    os.utime(str(lock), (old, old))
    habits.write_rows(defs, {"2026-09-01": {"date": "2026-09-01",
                                            "day_of_week": "Tuesday"}})
    assert (sandbox / "habits.csv").exists()


def test_fresh_lock_times_out_with_a_sentence(defs, sandbox, monkeypatch):
    (sandbox / "habits.lock").write_text("1", encoding="utf-8")
    monkeypatch.setattr(habits, "LOCK_WAIT_S", 0.2)
    with pytest.raises(SystemExit):
        habits.write_rows(defs, {"2026-09-01": {"date": "2026-09-01",
                                                "day_of_week": "Tuesday"}})


def test_replace_retries_transient_failures(monkeypatch, tmp_path):
    src, dst = tmp_path / "a", tmp_path / "b"
    src.write_text("x", encoding="utf-8")
    calls = {"n": 0}
    real = habits.os.replace

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("sharing violation")
        real(a, b)

    monkeypatch.setattr(habits.os, "replace", flaky)
    habits._replace_with_retry(src, dst)
    assert dst.read_text(encoding="utf-8") == "x" and calls["n"] == 3


# -- explicit workout survives --whoop; workout_whoop always recorded -----------

def test_prefill_whoop_emits_workout_whoop(defs, monkeypatch):
    known, notes = {}, []
    monkeypatch.setattr(habits, "find_whoop_csv", lambda defs: Path("x.csv"))
    monkeypatch.setattr(habits, "whoop_latest_date", lambda path: "2026-09-01")
    monkeypatch.setattr(habits, "whoop_row_for", lambda path, day: {
        "workout_count": "1", "sleep_start": "", "light_sleep_hrs": "",
        "slow_wave_sleep_hrs": "", "rem_sleep_hrs": "", "day_strain": "",
        "sleep_consistency_pct": ""})
    habits.prefill_whoop(defs, date(2026, 9, 1), known, notes)
    assert known["workout"] == "yes" and known["workout_whoop"] == "yes"


# -- --whoop fills blanks, end to end through cmd_log --------------------------

def _fake_whoop(monkeypatch, **fields):
    """Point prefill_whoop at one synthetic row without touching the disk."""
    row = {"date": "2026-08-26", "day_strain": "", "workout_count": "",
           "sleep_start": "", "light_sleep_hrs": "", "slow_wave_sleep_hrs": "",
           "rem_sleep_hrs": "", "sleep_consistency_pct": ""}
    row.update(fields)
    monkeypatch.setattr(habits, "find_whoop_csv", lambda defs: Path("whoop.csv"))
    monkeypatch.setattr(habits, "whoop_latest_date", lambda path: "2026-08-26")
    monkeypatch.setattr(habits, "whoop_row_for", lambda path, day: row)
    return row


def test_whoop_never_overwrites_a_stored_self_reported_workout(sandbox, defs, monkeypatch):
    """The 7:00 sync must not argue with what Auckie already ticked."""
    _log(monkeypatch, set=["workout=yes"])
    _fake_whoop(monkeypatch, workout_count="0", day_strain="5")
    _log(monkeypatch, whoop=True)
    row = habits.read_rows(defs)["2026-08-26"]
    assert row["workout"] == "yes"          # stored value survives
    assert row["workout_whoop"] == "no"     # WHOOP's view recorded beside it


def test_whoop_still_fills_a_blank(sandbox, defs, monkeypatch):
    """Filling blanks is the point; only overwriting is forbidden."""
    _log(monkeypatch, set=["made_bed=yes"])
    _fake_whoop(monkeypatch, workout_count="1", day_strain="9")
    _log(monkeypatch, whoop=True)
    row = habits.read_rows(defs)["2026-08-26"]
    assert row["workout"] == "yes" and row["workout_whoop"] == "yes"


def test_explicit_set_still_beats_whoop(sandbox, defs, monkeypatch):
    _fake_whoop(monkeypatch, workout_count="0", day_strain="5")
    _log(monkeypatch, whoop=True, set=["workout=yes"])
    assert habits.read_rows(defs)["2026-08-26"]["workout"] == "yes"


def test_cmd_log_holds_the_lock_across_read_and_write(sandbox, defs, monkeypatch):
    """A writer landing between this one's read and write would be erased."""
    seen = {}
    real_read, real_write = habits.read_rows, habits.write_rows

    def spy_read(d):
        seen["lock_at_read"] = habits.LOCK_PATH.exists()
        return real_read(d)

    def spy_write(d, rows, locked=False):
        seen["locked"] = locked
        return real_write(d, rows, locked=locked)

    monkeypatch.setattr(habits, "read_rows", spy_read)
    monkeypatch.setattr(habits, "write_rows", spy_write)
    _log(monkeypatch, set=["made_bed=yes"])

    assert seen["lock_at_read"] is True
    assert seen["locked"] is True
    assert not habits.LOCK_PATH.exists()    # and released afterwards
