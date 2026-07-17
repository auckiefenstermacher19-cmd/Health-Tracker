import pytest
from unittest.mock import patch

from codegeeko.run import (
    DEFAULT_MAX_FIXES_PER_NIGHT,
    collect_all,
    is_report_only,
    main,
    max_fixes_per_night,
)
from codegeeko.state import compute_deltas


def test_collect_all_merges_findings_and_records_status():
    with (
        patch("codegeeko.run.run_repowise", return_value=([{"source": "repowise", "file": "a.py", "finding_id": "metric", "risk_score": 7.0, "message": "x", "raw": {}}], True)),
        patch("codegeeko.run.run_semgrep", return_value=([], False)),
        patch("codegeeko.run.run_ci_log_check", return_value=([], True)),
    ):
        findings, checked = collect_all(".", "auckiefenstermacher19-cmd", "Health-Tracker", "fake-token")

    assert len(findings) == 1
    assert findings[0]["source"] == "repowise"
    assert checked == {"repowise": "ok", "semgrep": "failed", "ci_log": "ok"}


def test_is_report_only_defaults_to_safe_when_env_var_unset():
    assert is_report_only({}) is True


@pytest.mark.parametrize(
    "value",
    ["true", "True", "TRUE", " true", "true ", "", "yes", "1", "ture", "0", "no", "banana"],
)
def test_is_report_only_stays_safe_for_anything_but_an_explicit_false(value):
    assert is_report_only({"REPORT_ONLY": value}) is True


@pytest.mark.parametrize("value", ["false", "False", "FALSE", " false ", "\tfalse\n"])
def test_is_report_only_only_disarms_on_explicit_false(value):
    assert is_report_only({"REPORT_ONLY": value}) is False


_SAMPLE_FINDING = {"source": "repowise", "file": "a.py", "finding_id": "metric", "risk_score": 7.0, "message": "x", "raw": {}}


def test_main_exits_1_before_triage_when_all_collectors_fail(monkeypatch):
    # An all-failed collector night has zero real signal -- must abort BEFORE paying for a
    # triage SDK call and BEFORE save_state (saving build_next_state([], ...) here would wipe
    # the entire state file, re-firing every finding on recovery).
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    with (
        patch("codegeeko.run.load_state", return_value={"findings": {}, "checked_sources": {}}),
        patch("codegeeko.run.collect_all", return_value=([], {"repowise": "failed", "semgrep": "failed", "ci_log": "failed"})),
        patch("codegeeko.run.triage_findings") as mock_triage,
        patch("codegeeko.run.save_state") as mock_save,
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 1
    mock_triage.assert_not_called()
    mock_save.assert_not_called()


def test_main_exits_1_and_skips_save_state_when_triage_fails(monkeypatch, capsys):
    # A failed triage call must not be indistinguishable from "triage rejected everything" --
    # state must NOT be saved so the deltas retry tomorrow instead of being marked seen forever.
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    with (
        patch("codegeeko.run.load_state", return_value={"findings": {}, "checked_sources": {}}),
        patch("codegeeko.run.collect_all", return_value=([_SAMPLE_FINDING], {"repowise": "ok", "semgrep": "ok", "ci_log": "ok"})),
        patch("codegeeko.run.triage_findings", return_value=([], False)),
        patch("codegeeko.run.save_state") as mock_save,
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 1
    mock_save.assert_not_called()
    assert "triage failed" in capsys.readouterr().out


def test_main_saves_state_when_triage_ok_even_if_everything_was_rejected(monkeypatch):
    # A successful triage run that deliberately accepts nothing is NOT a failure -- state must
    # still be saved as today (deliberate suppression by design; only FAILURE skips the save).
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    with (
        patch("codegeeko.run.load_state", return_value={"findings": {}, "checked_sources": {}}),
        patch("codegeeko.run.collect_all", return_value=([_SAMPLE_FINDING], {"repowise": "ok", "semgrep": "ok", "ci_log": "ok"})),
        patch("codegeeko.run.triage_findings", return_value=([], True)),
        patch("codegeeko.run.save_state") as mock_save,
    ):
        main()

    mock_save.assert_called_once()


def _accepted(count: int) -> list[dict]:
    return [
        {
            "source": "repowise",
            "file": f"f{i}.py",
            "finding_id": "metric",
            "risk_score": 7.0,
            "message": f"finding {i}",
            "raw": {},
            "triage_reason": "worth fixing",
        }
        for i in range(count)
    ]


_CI_FINDING = {
    "source": "ci_log",
    "file": None,
    "finding_id": "run-1",
    "risk_score": 6.0,
    "message": "workflow failed",
    "raw": {},
}


def _fix_mode(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("REPORT_ONLY", "false")


def test_max_fixes_per_night_defaults_when_env_unset():
    assert max_fixes_per_night({}) == DEFAULT_MAX_FIXES_PER_NIGHT


def test_max_fixes_per_night_reads_an_explicit_value():
    assert max_fixes_per_night({"MAX_FIXES_PER_NIGHT": "2"}) == 2


@pytest.mark.parametrize("value", ["", "banana", "0", "-3", "5.5"])
def test_max_fixes_per_night_falls_back_to_the_default_on_a_useless_value(value):
    assert max_fixes_per_night({"MAX_FIXES_PER_NIGHT": value}) == DEFAULT_MAX_FIXES_PER_NIGHT


def test_main_processes_at_most_the_nightly_cap_of_accepted_findings(monkeypatch):
    _fix_mode(monkeypatch)
    accepted = _accepted(12)
    with (
        patch("codegeeko.run.load_state", return_value={"findings": {}, "checked_sources": {}}),
        patch("codegeeko.run.collect_all", return_value=(accepted, {"repowise": "ok"})),
        patch("codegeeko.run.triage_findings", return_value=(accepted, True)),
        patch("codegeeko.fixer.fix_and_report", return_value={"outcome": "pr", "url": "u"}) as mock_fix,
        patch("codegeeko.run.save_state"),
    ):
        main()

    assert mock_fix.call_count == DEFAULT_MAX_FIXES_PER_NIGHT


def test_main_honours_a_cap_set_by_env(monkeypatch):
    _fix_mode(monkeypatch)
    monkeypatch.setenv("MAX_FIXES_PER_NIGHT", "2")
    accepted = _accepted(12)
    with (
        patch("codegeeko.run.load_state", return_value={"findings": {}, "checked_sources": {}}),
        patch("codegeeko.run.collect_all", return_value=(accepted, {"repowise": "ok"})),
        patch("codegeeko.run.triage_findings", return_value=(accepted, True)),
        patch("codegeeko.fixer.fix_and_report", return_value={"outcome": "pr", "url": "u"}) as mock_fix,
        patch("codegeeko.run.save_state"),
    ):
        main()

    assert mock_fix.call_count == 2


def test_main_leaves_findings_deferred_past_the_cap_unseen_so_they_refire(monkeypatch):
    # The Task 11.5 swallow bug, one layer up: a finding deferred past the cap must NOT be marked
    # seen, or state suppresses it forever and it is never fixed.
    _fix_mode(monkeypatch)
    accepted = _accepted(12)
    with (
        patch("codegeeko.run.load_state", return_value={"findings": {}, "checked_sources": {}}),
        patch("codegeeko.run.collect_all", return_value=(accepted, {"repowise": "ok"})),
        patch("codegeeko.run.triage_findings", return_value=(accepted, True)),
        patch("codegeeko.fixer.fix_and_report", return_value={"outcome": "pr", "url": "u"}),
        patch("codegeeko.run.save_state") as mock_save,
    ):
        main()

    saved = mock_save.call_args[0][1]
    assert len(saved["findings"]) == DEFAULT_MAX_FIXES_PER_NIGHT
    assert len(compute_deltas(saved, accepted)) == 12 - DEFAULT_MAX_FIXES_PER_NIGHT


def test_main_reports_how_many_findings_were_deferred(monkeypatch, capsys):
    _fix_mode(monkeypatch)
    accepted = _accepted(12)
    with (
        patch("codegeeko.run.load_state", return_value={"findings": {}, "checked_sources": {}}),
        patch("codegeeko.run.collect_all", return_value=(accepted, {"repowise": "ok"})),
        patch("codegeeko.run.triage_findings", return_value=(accepted, True)),
        patch("codegeeko.fixer.fix_and_report", return_value={"outcome": "pr", "url": "u"}),
        patch("codegeeko.run.save_state"),
    ):
        main()

    out = capsys.readouterr().out
    assert "5 of 12 accepted findings processed tonight; 7 deferred" in out


def test_main_marks_a_successfully_actioned_finding_as_seen(monkeypatch):
    _fix_mode(monkeypatch)
    accepted = _accepted(1)
    with (
        patch("codegeeko.run.load_state", return_value={"findings": {}, "checked_sources": {}}),
        patch("codegeeko.run.collect_all", return_value=(accepted, {"repowise": "ok"})),
        patch("codegeeko.run.triage_findings", return_value=(accepted, True)),
        patch("codegeeko.fixer.fix_and_report", return_value={"outcome": "pr", "url": "u"}),
        patch("codegeeko.run.save_state") as mock_save,
    ):
        main()

    saved = mock_save.call_args[0][1]
    assert list(saved["findings"]) == ["repowise:f0.py:metric"]


@pytest.mark.parametrize("outcome", ["pr_failed", "issue_failed"])
def test_main_leaves_a_finding_unseen_when_its_pr_or_issue_step_failed(monkeypatch, outcome):
    # Only a fix/flag that actually LANDED may mark a finding seen. A transient GitHub API
    # failure must retry tomorrow, not be recorded as handled.
    _fix_mode(monkeypatch)
    accepted = _accepted(1)
    with (
        patch("codegeeko.run.load_state", return_value={"findings": {}, "checked_sources": {}}),
        patch("codegeeko.run.collect_all", return_value=(accepted, {"repowise": "ok"})),
        patch("codegeeko.run.triage_findings", return_value=(accepted, True)),
        patch("codegeeko.fixer.fix_and_report", return_value={"outcome": outcome, "error": "boom"}),
        patch("codegeeko.run.save_state") as mock_save,
    ):
        main()

    assert mock_save.call_args[0][1]["findings"] == {}


def test_main_leaves_a_finding_unseen_when_its_git_step_raised(monkeypatch):
    # fix_and_report lets local git failures raise; run.py catches them per-finding so one bad
    # finding cannot take down the batch. That finding must still be retried, not marked seen.
    _fix_mode(monkeypatch)
    accepted = _accepted(1)
    with (
        patch("codegeeko.run.load_state", return_value={"findings": {}, "checked_sources": {}}),
        patch("codegeeko.run.collect_all", return_value=(accepted, {"repowise": "ok"})),
        patch("codegeeko.run.triage_findings", return_value=(accepted, True)),
        patch("codegeeko.fixer.fix_and_report", side_effect=RuntimeError("git exploded")),
        patch("codegeeko.run.save_state") as mock_save,
    ):
        main()

    assert mock_save.call_args[0][1]["findings"] == {}


def test_main_keeps_processing_after_one_finding_fails(monkeypatch):
    _fix_mode(monkeypatch)
    accepted = _accepted(3)
    with (
        patch("codegeeko.run.load_state", return_value={"findings": {}, "checked_sources": {}}),
        patch("codegeeko.run.collect_all", return_value=(accepted, {"repowise": "ok"})),
        patch("codegeeko.run.triage_findings", return_value=(accepted, True)),
        patch(
            "codegeeko.fixer.fix_and_report",
            side_effect=[
                {"outcome": "pr", "url": "u"},
                RuntimeError("git exploded"),
                {"outcome": "issue", "url": "u"},
            ],
        ) as mock_fix,
        patch("codegeeko.run.save_state") as mock_save,
    ):
        main()

    assert mock_fix.call_count == 3
    saved = mock_save.call_args[0][1]
    assert sorted(saved["findings"]) == ["repowise:f0.py:metric", "repowise:f2.py:metric"]


def test_main_carries_forward_the_findings_of_a_failed_collector(monkeypatch):
    # Wiring check: run.py must hand the previous state to build_next_state, or the carry-forward
    # that stops an outage from re-firing every finding never actually runs in production.
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    previous = {
        "findings": {"ci_log:None:run-1": _CI_FINDING},
        "checked_sources": {"ci_log": "ok"},
    }
    with (
        patch("codegeeko.run.load_state", return_value=previous),
        patch("codegeeko.run.collect_all", return_value=([], {"repowise": "ok", "ci_log": "failed"})),
        patch("codegeeko.run.triage_findings", return_value=([], True)),
        patch("codegeeko.run.save_state") as mock_save,
    ):
        main()

    assert "ci_log:None:run-1" in mock_save.call_args[0][1]["findings"]


def test_main_saves_state_on_a_fully_clean_night_with_no_deltas(monkeypatch):
    # No collector failures, no deltas, no triage call needed -- the ordinary green path must
    # still save state.
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    with (
        patch("codegeeko.run.load_state", return_value={"findings": {}, "checked_sources": {}}),
        patch("codegeeko.run.collect_all", return_value=([], {"repowise": "ok", "semgrep": "ok", "ci_log": "ok"})),
        patch("codegeeko.run.triage_findings", return_value=([], True)) as mock_triage,
        patch("codegeeko.run.save_state") as mock_save,
    ):
        main()

    mock_triage.assert_called_once_with([])
    mock_save.assert_called_once()
