from codegeeko.report import format_report

TRIAGED = [{
    "source": "repowise", "file": "consolidate.py", "finding_id": "metric", "risk_score": 8.0,
    "message": "high complexity", "raw": {}, "triage_reason": "clear fix available",
}]


def test_format_report_includes_each_triaged_finding():
    report = format_report(TRIAGED, {"repowise": "ok", "semgrep": "ok", "ci_log": "ok"})

    assert "consolidate.py" in report
    assert "clear fix available" in report
    assert "high complexity" in report


def test_format_report_flags_failed_collectors():
    report = format_report([], {"repowise": "ok", "semgrep": "failed", "ci_log": "ok"})

    assert "semgrep" in report.lower()
    assert "failed" in report.lower()


def test_format_report_handles_no_findings():
    report = format_report([], {"repowise": "ok", "semgrep": "ok", "ci_log": "ok"})
    assert "no new" in report.lower() or "nothing" in report.lower()
