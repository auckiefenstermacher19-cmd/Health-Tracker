from unittest.mock import patch

from codegeeko.run import collect_all


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
