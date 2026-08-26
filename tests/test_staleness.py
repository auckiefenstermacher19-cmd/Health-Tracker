"""The consolidation reported status: SUCCESS every day for a week while its WHOOP data
sat frozen at 2026-08-19. It fetched faithfully; the upstream had simply stopped moving,
and nothing checked. A dead source and a quiet source looked identical."""

from datetime import date

from consolidate import newest_age_days, staleness_report


class TestNewestAgeDays:
    def test_data_from_today_is_zero_days_old(self):
        assert newest_age_days({"2026-08-26"}, today=date(2026, 8, 26)) == 0

    def test_reports_the_age_of_the_newest_date_not_the_oldest(self):
        dates = {"2024-05-10", "2026-08-19", "2026-08-01"}
        assert newest_age_days(dates, today=date(2026, 8, 26)) == 7

    def test_no_dates_at_all_returns_none(self):
        assert newest_age_days(set(), today=date(2026, 8, 26)) is None

    def test_unparseable_dates_are_ignored_rather_than_crashing_the_run(self):
        assert newest_age_days({"not-a-date", "2026-08-20"}, today=date(2026, 8, 26)) == 6

    def test_only_unparseable_dates_returns_none(self):
        assert newest_age_days({"junk"}, today=date(2026, 8, 26)) is None


class TestStalenessReport:
    def test_fresh_sources_are_reported_ok(self):
        r = staleness_report({"whoop": {"2026-08-26"}}, max_age_days=2, today=date(2026, 8, 26))
        assert r["status"] == "SUCCESS"
        assert r["stale_sources"] == []
        assert r["ages"]["whoop"] == 0

    def test_a_source_past_the_threshold_is_flagged_stale(self):
        # This is the exact case that went unnoticed for a week.
        r = staleness_report({"whoop": {"2026-08-19"}}, max_age_days=2, today=date(2026, 8, 26))
        assert r["status"] == "STALE"
        assert "whoop" in r["stale_sources"]

    def test_one_stale_source_does_not_hide_behind_a_fresh_one(self):
        r = staleness_report(
            {"whoop": {"2026-08-26"}, "meal": {"2026-07-25"}},
            max_age_days=2, today=date(2026, 8, 26),
        )
        assert r["status"] == "STALE"
        assert r["stale_sources"] == ["meal"]

    def test_exactly_at_the_threshold_is_still_acceptable(self):
        r = staleness_report({"whoop": {"2026-08-24"}}, max_age_days=2, today=date(2026, 8, 26))
        assert r["status"] == "SUCCESS"

    def test_an_empty_source_is_stale_not_silently_fine(self):
        # No dates at all is the most broken state, not the healthiest.
        r = staleness_report({"whoop": set()}, max_age_days=2, today=date(2026, 8, 26))
        assert r["status"] == "STALE"
        assert r["ages"]["whoop"] is None


class TestPerSourceSeverity:
    """WHOOP syncs by itself, so 2 days of silence means something broke. Meals depend on
    a human remembering to log, so a lapse is a habit, not an outage. Reporting both as
    hard failures trains you to ignore red checks - which is how the original silent
    staleness went unnoticed for a week in the first place."""

    def test_a_warn_only_source_is_stale_but_does_not_fail_the_run(self):
        r = staleness_report({"meal": {"2026-07-25"}}, max_age_days=2,
                             today=date(2026, 8, 26), warn_only={"meal"})
        assert r["status"] == "STALE"
        assert r["stale_sources"] == ["meal"]
        assert r["failing_sources"] == []
        assert r["warning_sources"] == ["meal"]

    def test_a_normal_source_still_fails_the_run(self):
        r = staleness_report({"whoop": {"2026-08-19"}}, max_age_days=2,
                             today=date(2026, 8, 26), warn_only={"meal"})
        assert r["failing_sources"] == ["whoop"]

    def test_a_stale_warn_only_source_never_masks_a_failing_one(self):
        r = staleness_report({"whoop": {"2026-08-19"}, "meal": {"2026-07-25"}},
                             max_age_days=2, today=date(2026, 8, 26), warn_only={"meal"})
        assert r["failing_sources"] == ["whoop"]
        assert r["warning_sources"] == ["meal"]
        assert sorted(r["stale_sources"]) == ["meal", "whoop"]

    def test_with_no_warn_only_every_stale_source_fails(self):
        r = staleness_report({"whoop": {"2026-08-19"}}, max_age_days=2, today=date(2026, 8, 26))
        assert r["failing_sources"] == ["whoop"]
