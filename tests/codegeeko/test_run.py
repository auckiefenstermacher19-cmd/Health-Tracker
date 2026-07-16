import pytest
from unittest.mock import patch

from codegeeko.run import collect_all, is_report_only, main


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
