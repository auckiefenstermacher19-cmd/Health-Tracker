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


def test_count_requires_whole_non_negative_number(defs):
    water = habits.habit_by_id(defs, "water")
    assert habits.normalise(water, "5") == "5"
    with pytest.raises(ValueError):
        habits.normalise(water, "2.5")
    with pytest.raises(ValueError):
        habits.normalise(water, "-1")


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
    _log(monkeypatch, set=["made_bed=yes", "water=6", "no_junk=no"])
    rows = habits.read_rows(defs)
    row = rows["2026-08-26"]
    assert row["made_bed"] == "yes"
    assert row["water"] == "6"
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
    _log(monkeypatch, set=["water=5"])
    row = habits.read_rows(defs)["2026-08-26"]
    assert row["made_bed"] == "yes" and row["water"] == "5"


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
        "Made bed", "Workout", "Morning Vitamins", "Shower + Teeth", "Water",
        "Read Fiction", "Read Non-fiction", "Bed on time", "Night Vitamins",
        "No Junk", "No Fap", "Screentime", "Clean Sink", "Reset House",
    ]
    assert [h["label"] for h in defs["habits"]][:len(original)] == original


def test_added_habit_leaves_older_rows_blank_not_no(sandbox, defs, monkeypatch):
    """Adding a habit must not retroactively mark past days as failures."""
    _log(monkeypatch, date="2026-08-26", set=["made_bed=yes"])
    row = habits.read_rows(defs)["2026-08-26"]
    assert row["logged_food"] == ""


def test_habit_ids_are_unique(defs):
    ids = habits.habit_ids(defs)
    assert len(ids) == len(set(ids))
