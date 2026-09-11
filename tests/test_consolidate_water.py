"""Water is a third source in the merge, and the weakest of the three.

WHOOP syncs itself; meals need a human; water needs a human pressing a button several
times a day, which is the easiest of the three to drop. So water is warn-only everywhere:
optional to fetch, optional to validate, never a red run when it goes quiet.

The load-bearing guarantee here is the one that is easy to break by accident: when there
is no water file at all, the output must be byte-identical to the two-block layout the
dashboard has been parsing all along. These tests assert that header equality exactly,
not approximately.
"""

import csv
import json
from datetime import date

import consolidate
from consolidate import (
    SPACER_SENTINEL,
    build_output_header,
    build_output_row,
    header_for_output,
    load_optional_water,
    staleness_report,
    validate_output,
)

WHOOP_HEADER = ["date", "recovery_score", "hrv"]
MEAL_HEADER = ["date", "calories", "protein_g"]
WATER_HEADER = [
    "date",
    "water_fl_oz",
    "water_goal_fl_oz",
    "water_pct_of_goal",
    "water_entries",
    "water_big_count",
    "water_small_count",
]


class TestOutputHeader:
    def test_water_block_follows_a_second_spacer(self):
        header = build_output_header(WHOOP_HEADER, MEAL_HEADER, WATER_HEADER)
        assert header == (
            ["date", "recovery_score", "hrv"]
            + [SPACER_SENTINEL]
            + ["meal_date", "calories", "protein_g"]
            + [SPACER_SENTINEL]
            + [
                "water_date",
                "water_fl_oz",
                "water_goal_fl_oz",
                "water_pct_of_goal",
                "water_entries",
                "water_big_count",
                "water_small_count",
            ]
        )

    def test_waters_own_date_column_is_renamed_so_only_column_zero_is_date(self):
        header = build_output_header(WHOOP_HEADER, MEAL_HEADER, WATER_HEADER)
        assert [c for c in header if c == "date"] == ["date"]
        assert header.index("water_date") == len(WHOOP_HEADER) + 1 + len(MEAL_HEADER) + 1

    def test_no_water_file_yields_the_old_two_block_header_exactly(self):
        # The dashboard has been parsing this exact header. A water source that is
        # missing must change nothing about it - not a trailing spacer, not anything.
        old = ["date", "recovery_score", "hrv", SPACER_SENTINEL,
               "meal_date", "calories", "protein_g"]
        assert build_output_header(WHOOP_HEADER, MEAL_HEADER) == old
        assert build_output_header(WHOOP_HEADER, MEAL_HEADER, water_header=None) == old

    def test_csv_form_writes_both_spacers_as_blanks(self):
        header = header_for_output(build_output_header(WHOOP_HEADER, MEAL_HEADER, WATER_HEADER))
        assert header[len(WHOOP_HEADER)] == ""
        assert header[len(WHOOP_HEADER) + 1 + len(MEAL_HEADER)] == ""
        assert SPACER_SENTINEL not in header


class TestOutputRow:
    def _row(self, day, water_by_date, water_header=WATER_HEADER):
        return build_output_row(
            date=day,
            whoop_header=WHOOP_HEADER,
            whoop_by_date={"2026-09-10": ["2026-09-10", "72", "41"]},
            meal_header=MEAL_HEADER,
            meal_by_date={"2026-09-10": ["2026-09-10", "2100", "150"]},
            water_header=water_header,
            water_by_date=water_by_date,
        )

    def test_a_day_with_water_carries_its_water_cells(self):
        water = {"2026-09-10": ["2026-09-10", "96", "128", "75.0", "5", "3", "2"]}
        row = self._row("2026-09-10", water)
        assert row[-7:] == ["2026-09-10", "96", "128", "75.0", "5", "3", "2"]

    def test_a_day_missing_from_water_gets_blanks_not_a_short_row(self):
        row = self._row("2026-09-10", {})
        assert row[-7:] == [""] * 7
        assert len(row) == len(WHOOP_HEADER) + 1 + len(MEAL_HEADER) + 1 + len(WATER_HEADER)

    def test_a_water_only_day_still_carries_the_date_in_column_zero(self):
        water = {"2026-09-11": ["2026-09-11", "64", "128", "50.0", "4", "2", "2"]}
        row = self._row("2026-09-11", water)
        assert row[0] == "2026-09-11"
        assert row[-7] == "2026-09-11"

    def test_a_short_water_row_is_padded_to_the_water_header(self):
        row = self._row("2026-09-10", {"2026-09-10": ["2026-09-10", "96"]})
        assert row[-7:] == ["2026-09-10", "96", "", "", "", "", ""]

    def test_no_water_source_yields_the_old_two_block_row_exactly(self):
        row = self._row("2026-09-10", None, water_header=None)
        assert row == ["2026-09-10", "72", "41", "", "2026-09-10", "2100", "150"]

    def test_row_width_matches_the_header_width(self):
        header = build_output_header(WHOOP_HEADER, MEAL_HEADER, WATER_HEADER)
        assert len(self._row("2026-09-10", {})) == len(header)


class TestValidateOutput:
    def _write(self, tmp_path, header, rows):
        path = tmp_path / "out.csv"
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header_for_output(header))
            for row in rows:
                writer.writerow(row)
        return path

    def _three_block(self, tmp_path, water_by_date):
        header = build_output_header(WHOOP_HEADER, MEAL_HEADER, WATER_HEADER)
        whoop_by_date = {"2026-09-10": ["2026-09-10", "72", "41"]}
        meal_by_date = {"2026-09-09": ["2026-09-09", "2100", "150"]}
        all_dates = sorted(
            set(whoop_by_date) | set(meal_by_date) | set(water_by_date), reverse=True
        )
        rows = [
            build_output_row(
                date=d,
                whoop_header=WHOOP_HEADER,
                whoop_by_date=whoop_by_date,
                meal_header=MEAL_HEADER,
                meal_by_date=meal_by_date,
                water_header=WATER_HEADER,
                water_by_date=water_by_date,
            )
            for d in all_dates
        ]
        return self._write(tmp_path, header, rows), header, all_dates

    def test_accepts_a_three_block_file(self, tmp_path):
        water = {"2026-09-11": ["2026-09-11", "64", "128", "50.0", "4", "2", "2"]}
        path, header, all_dates = self._three_block(tmp_path, water)
        assert validate_output(
            path=path,
            expected_cols=len(header),
            expected_rows=len(all_dates),
            whoop_dates={"2026-09-10"},
            meal_dates={"2026-09-09"},
            whoop_col_count=len(WHOOP_HEADER),
            water_dates={"2026-09-11"},
        )

    def test_meal_dates_are_still_found_at_whoop_col_count_plus_one(self, tmp_path):
        # A meal-only day has nothing in column 0; it is found only at the meal date
        # index. Getting that index wrong is how a three-block layout would silently
        # start dropping meal days.
        water = {"2026-09-11": ["2026-09-11", "64", "128", "50.0", "4", "2", "2"]}
        path, header, all_dates = self._three_block(tmp_path, water)
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))[1:]
        meal_idx = len(WHOOP_HEADER) + 1
        assert "2026-09-09" in {r[meal_idx] for r in rows}
        assert validate_output(
            path=path,
            expected_cols=len(header),
            expected_rows=len(all_dates),
            whoop_dates=set(),
            meal_dates={"2026-09-09"},
            whoop_col_count=len(WHOOP_HEADER),
            water_dates=set(),
        )

    def test_a_water_only_date_missing_from_the_file_fails_validation(self, tmp_path):
        path, header, all_dates = self._three_block(tmp_path, {})
        assert not validate_output(
            path=path,
            expected_cols=len(header),
            expected_rows=len(all_dates),
            whoop_dates={"2026-09-10"},
            meal_dates={"2026-09-09"},
            whoop_col_count=len(WHOOP_HEADER),
            water_dates={"2026-09-11"},
        )

    def test_two_block_file_still_validates_with_no_water_argument(self, tmp_path):
        header = build_output_header(WHOOP_HEADER, MEAL_HEADER)
        rows = [
            build_output_row(
                date="2026-09-10",
                whoop_header=WHOOP_HEADER,
                whoop_by_date={"2026-09-10": ["2026-09-10", "72", "41"]},
                meal_header=MEAL_HEADER,
                meal_by_date={},
            )
        ]
        path = self._write(tmp_path, header, rows)
        assert validate_output(
            path=path,
            expected_cols=len(header),
            expected_rows=1,
            whoop_dates={"2026-09-10"},
            meal_dates=set(),
            whoop_col_count=len(WHOOP_HEADER),
        )


class TestABadWaterFileDoesNotKillTheMerge:
    """Warn-only has to mean warn-only for every failure mode, not just the tidy one where
    the file is absent. A zero-byte export or one missing its `date` column would otherwise
    raise straight out of the loader and take WHOOP and meals down with it - the merge would
    publish nothing at all on the day a hydration export went wrong."""

    def test_a_missing_file_degrades_to_two_blocks(self, tmp_path):
        assert load_optional_water(tmp_path / "nope.csv") == (None, {})

    def test_a_zero_byte_file_degrades_instead_of_raising_stopiteration(self, tmp_path):
        path = tmp_path / "Water_Data_Dashboard.csv"
        path.write_text("", encoding="utf-8")
        assert load_optional_water(path) == (None, {})

    def test_a_file_with_no_date_column_degrades_instead_of_raising_valueerror(self, tmp_path):
        path = tmp_path / "Water_Data_Dashboard.csv"
        path.write_text("day,water_fl_oz\n2026-09-11,96\n", encoding="utf-8")
        assert load_optional_water(path) == (None, {})

    def test_a_header_only_file_is_usable_and_simply_has_no_dates(self, tmp_path):
        # Distinct from broken: the column layout is known, so the water block is written
        # with blank cells rather than dropped.
        path = tmp_path / "Water_Data_Dashboard.csv"
        path.write_text(",".join(WATER_HEADER) + "\n", encoding="utf-8")
        header, by_date = load_optional_water(path)
        assert header == WATER_HEADER
        assert by_date == {}

    def test_a_good_file_is_loaded_and_indexed_by_date(self, tmp_path):
        path = tmp_path / "Water_Data_Dashboard.csv"
        path.write_text(
            ",".join(WATER_HEADER) + "\n2026-09-11,96,128,75.0,5,3,2\n", encoding="utf-8"
        )
        header, by_date = load_optional_water(path)
        assert header == WATER_HEADER
        assert by_date["2026-09-11"] == ["2026-09-11", "96", "128", "75.0", "5", "3", "2"]

    def test_the_whole_merge_still_runs_over_a_malformed_water_file(self, tmp_path, monkeypatch):
        # End to end: the one that matters. A broken water file must leave a complete,
        # valid two-block master behind, not a missing one.
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "daily_consolidated.csv").write_text(
            "date,recovery_score\n2026-09-11,72\n", encoding="utf-8")
        (raw / "Meal_Data_Dashboard.csv").write_text(
            "date,calories\n2026-09-10,2100\n", encoding="utf-8")
        (raw / "Water_Data_Dashboard.csv").write_text(
            "day,water_fl_oz\n2026-09-11,96\n", encoding="utf-8")

        out = tmp_path / "Health_Tracker_Master.csv"
        monkeypatch.setattr(consolidate, "WHOOP_CSV", raw / "daily_consolidated.csv")
        monkeypatch.setattr(consolidate, "MEAL_CSV", raw / "Meal_Data_Dashboard.csv")
        monkeypatch.setattr(consolidate, "WATER_CSV", raw / "Water_Data_Dashboard.csv")
        monkeypatch.setattr(consolidate, "OUTPUT_PATH", out)
        monkeypatch.setattr(consolidate, "STAGING_PATH", tmp_path / "staging.csv")
        monkeypatch.setattr(consolidate, "AUDIT_LOG", tmp_path / "audit.jsonl")

        consolidate.build_consolidated()   # must not raise, must not sys.exit

        rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        assert rows[0] == ["date", "recovery_score", "", "meal_date", "calories"]
        assert len(rows) == 3   # header + two dates

    def test_the_merge_writes_a_water_block_when_the_file_is_good(self, tmp_path, monkeypatch):
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "daily_consolidated.csv").write_text(
            "date,recovery_score\n2026-09-11,72\n", encoding="utf-8")
        (raw / "Meal_Data_Dashboard.csv").write_text(
            "date,calories\n2026-09-11,2100\n", encoding="utf-8")
        (raw / "Water_Data_Dashboard.csv").write_text(
            ",".join(WATER_HEADER) + "\n2026-09-11,96,128,75.0,5,3,2\n", encoding="utf-8")

        out = tmp_path / "Health_Tracker_Master.csv"
        audit = tmp_path / "audit.jsonl"
        monkeypatch.setattr(consolidate, "WHOOP_CSV", raw / "daily_consolidated.csv")
        monkeypatch.setattr(consolidate, "MEAL_CSV", raw / "Meal_Data_Dashboard.csv")
        monkeypatch.setattr(consolidate, "WATER_CSV", raw / "Water_Data_Dashboard.csv")
        monkeypatch.setattr(consolidate, "OUTPUT_PATH", out)
        monkeypatch.setattr(consolidate, "STAGING_PATH", tmp_path / "staging.csv")
        monkeypatch.setattr(consolidate, "AUDIT_LOG", audit)

        consolidate.build_consolidated()

        rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        assert rows[0][-8:] == ["", "water_date", "water_fl_oz", "water_goal_fl_oz",
                                "water_pct_of_goal", "water_entries", "water_big_count",
                                "water_small_count"]
        assert rows[1][-7:] == ["2026-09-11", "96", "128", "75.0", "5", "3", "2"]

        record = json.loads(audit.read_text(encoding="utf-8").splitlines()[-1])
        assert "water" in record["source_ages_days"]

    def test_water_is_left_out_of_the_freshness_report_until_the_file_exists(
        self, tmp_path, monkeypatch
    ):
        # A source nobody has wired up yet must not paint every run yellow forever.
        # A warning that is always on is a warning nobody reads.
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "daily_consolidated.csv").write_text(
            "date,recovery_score\n2026-09-11,72\n", encoding="utf-8")
        (raw / "Meal_Data_Dashboard.csv").write_text(
            "date,calories\n2026-09-11,2100\n", encoding="utf-8")

        audit = tmp_path / "audit.jsonl"
        monkeypatch.setattr(consolidate, "WHOOP_CSV", raw / "daily_consolidated.csv")
        monkeypatch.setattr(consolidate, "MEAL_CSV", raw / "Meal_Data_Dashboard.csv")
        monkeypatch.setattr(consolidate, "WATER_CSV", raw / "Water_Data_Dashboard.csv")
        monkeypatch.setattr(consolidate, "OUTPUT_PATH", tmp_path / "master.csv")
        monkeypatch.setattr(consolidate, "STAGING_PATH", tmp_path / "staging.csv")
        monkeypatch.setattr(consolidate, "AUDIT_LOG", audit)

        consolidate.build_consolidated()

        record = json.loads(audit.read_text(encoding="utf-8").splitlines()[-1])
        assert "water" not in record["source_ages_days"]
        assert record["warning_sources"] == []

    def test_an_empty_water_file_on_disk_is_reported_as_no_data_not_omitted(
        self, tmp_path, monkeypatch
    ):
        # Once the file exists, silence is a real signal and gets reported - warn-only,
        # so it still never reddens the run.
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "daily_consolidated.csv").write_text(
            "date,recovery_score\n2026-09-11,72\n", encoding="utf-8")
        (raw / "Meal_Data_Dashboard.csv").write_text(
            "date,calories\n2026-09-11,2100\n", encoding="utf-8")
        (raw / "Water_Data_Dashboard.csv").write_text(
            ",".join(WATER_HEADER) + "\n", encoding="utf-8")

        audit = tmp_path / "audit.jsonl"
        monkeypatch.setattr(consolidate, "WHOOP_CSV", raw / "daily_consolidated.csv")
        monkeypatch.setattr(consolidate, "MEAL_CSV", raw / "Meal_Data_Dashboard.csv")
        monkeypatch.setattr(consolidate, "WATER_CSV", raw / "Water_Data_Dashboard.csv")
        monkeypatch.setattr(consolidate, "OUTPUT_PATH", tmp_path / "master.csv")
        monkeypatch.setattr(consolidate, "STAGING_PATH", tmp_path / "staging.csv")
        monkeypatch.setattr(consolidate, "AUDIT_LOG", audit)
        monkeypatch.setenv("WARN_ONLY_SOURCES", "meal,water")

        consolidate.build_consolidated()

        record = json.loads(audit.read_text(encoding="utf-8").splitlines()[-1])
        assert record["source_ages_days"]["water"] is None
        assert "water" in record["warning_sources"]
        assert "water" not in record["failing_sources"]


class TestWaterStaleness:
    def test_water_warns_rather_than_failing_the_run(self):
        r = staleness_report(
            {"whoop": {"2026-09-11"}, "meal": {"2026-07-25"}, "water": {"2026-08-01"}},
            max_age_days=2,
            today=date(2026, 9, 11),
            warn_only={"meal", "water"},
        )
        assert r["status"] == "STALE"
        assert r["warning_sources"] == ["meal", "water"]
        assert r["failing_sources"] == []

    def test_an_empty_water_source_warns_but_does_not_mask_a_failing_whoop(self):
        r = staleness_report(
            {"whoop": {"2026-09-01"}, "water": set()},
            max_age_days=2,
            today=date(2026, 9, 11),
            warn_only={"meal", "water"},
        )
        assert r["ages"]["water"] is None
        assert r["warning_sources"] == ["water"]
        assert r["failing_sources"] == ["whoop"]


class TestATransientWaterFetchFailureDoesNotDropTheBlock:
    """fetch_sources.py deletes the stale local copy when a water fetch fails, and the water
    dispatch fires on every tap — so a single flaky fetch would otherwise republish the master
    without its water block and the dashboard's water tiles would blink out and back."""

    def _sources(self, tmp_path, monkeypatch, previous_master: str | None):
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "daily_consolidated.csv").write_text(
            "date,recovery_score\n2026-09-11,72\n", encoding="utf-8")
        (raw / "Meal_Data_Dashboard.csv").write_text(
            "date,calories\n2026-09-11,2100\n", encoding="utf-8")
        # No Water_Data_Dashboard.csv on disk: the fetch failed and the stale copy was removed.

        out = tmp_path / "Health_Tracker_Master.csv"
        if previous_master is not None:
            out.write_text(previous_master, encoding="utf-8")

        audit = tmp_path / "audit.jsonl"
        monkeypatch.setattr(consolidate, "WHOOP_CSV", raw / "daily_consolidated.csv")
        monkeypatch.setattr(consolidate, "MEAL_CSV", raw / "Meal_Data_Dashboard.csv")
        monkeypatch.setattr(consolidate, "WATER_CSV", raw / "Water_Data_Dashboard.csv")
        monkeypatch.setattr(consolidate, "OUTPUT_PATH", out)
        monkeypatch.setattr(consolidate, "STAGING_PATH", tmp_path / "staging.csv")
        monkeypatch.setattr(consolidate, "AUDIT_LOG", audit)
        return out, audit

    def test_the_water_block_is_carried_forward_blank_when_the_master_had_one(
        self, tmp_path, monkeypatch
    ):
        previous = (
            "date,recovery_score,,meal_date,calories,,"
            + ",".join(["water_date"] + WATER_HEADER[1:])
            + "\n2026-09-10,70,,2026-09-10,2000,,2026-09-10,96,128,75.0,5,3,2\n"
        )
        out, audit = self._sources(tmp_path, monkeypatch, previous)

        consolidate.build_consolidated()

        rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        assert rows[0] == [
            "date", "recovery_score", "", "meal_date", "calories", "",
            "water_date", "water_fl_oz", "water_goal_fl_oz", "water_pct_of_goal",
            "water_entries", "water_big_count", "water_small_count",
        ]
        assert rows[1][-7:] == [""] * 7
        assert len(rows) == 2   # header + the single date

        # Freshness is unchanged: water has no raw file, so it is not reported at all.
        record = json.loads(audit.read_text(encoding="utf-8").splitlines()[-1])
        assert "water" not in record["source_ages_days"]

    def test_no_previous_master_still_falls_back_to_two_blocks(self, tmp_path, monkeypatch):
        out, _ = self._sources(tmp_path, monkeypatch, None)

        consolidate.build_consolidated()

        rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        assert rows[0] == ["date", "recovery_score", "", "meal_date", "calories"]

    def test_a_previous_master_without_water_still_falls_back_to_two_blocks(
        self, tmp_path, monkeypatch
    ):
        previous = "date,recovery_score,,meal_date,calories\n2026-09-10,70,,2026-09-10,2000\n"
        out, _ = self._sources(tmp_path, monkeypatch, previous)

        consolidate.build_consolidated()

        rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
        assert rows[0] == ["date", "recovery_score", "", "meal_date", "calories"]
