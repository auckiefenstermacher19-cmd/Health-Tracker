import pytest
from unittest.mock import patch

from codegeeko.run import collect_all, is_report_only


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
