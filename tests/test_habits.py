"""Tests for habits.py - the parts where a wrong answer corrupts the log."""

import csv
import importlib.util
import json
import sys
from datetime import date, time
from pathlib import Path

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
    monkeypatch.setattr(habits, "STAGING_CSV", tmp_path / "habits.staging.csv")
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
                          "whoop": False, "note": None})()
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
    assert not habits.STAGING_CSV.exists()


# -- dates --------------------------------------------------------------------

def test_relative_dates():
    assert habits.parse_date("today") == date.today()
    assert (date.today() - habits.parse_date("yesterday")).days == 1
    assert habits.parse_date("2026-08-26") == date(2026, 8, 26)


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
