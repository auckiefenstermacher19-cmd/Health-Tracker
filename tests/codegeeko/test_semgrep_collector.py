import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from codegeeko.collectors.semgrep_collector import parse_semgrep_output, run_semgrep

FIXTURE = Path(__file__).parent / "fixtures" / "semgrep_sample_output.json"


def test_parse_semgrep_output_returns_normalized_findings():
    raw = json.loads(FIXTURE.read_text())
    findings = parse_semgrep_output(raw)

    assert isinstance(findings, list)
    assert findings  # the real fixture has 8 results, all real GHA mutable-tag findings
    for finding in findings:
        assert finding["source"] == "semgrep"
        assert isinstance(finding["file"], str)
        assert isinstance(finding["finding_id"], str)
        assert finding["finding_id"]
        assert 0.0 <= finding["risk_score"] <= 10.0
        assert isinstance(finding["message"], str)
        assert finding["message"]
        assert finding["raw"]


def test_parse_semgrep_output_handles_no_results():
    assert parse_semgrep_output({"results": []}) == []


def test_parse_semgrep_output_handles_empty_input():
    assert parse_semgrep_output({}) == []


def test_parse_semgrep_output_returns_one_finding_per_result():
    # The real fixture has exactly 8 results entries (a real repo quirk: the same
    # mutable-action-tag rule fires on duplicated workflow files under both
    # .github/workflows/ and workflows/) -- every result must surface as its own finding.
    raw = json.loads(FIXTURE.read_text())
    findings = parse_semgrep_output(raw)
    assert len(findings) == 8


def test_parse_semgrep_output_maps_warning_severity_to_risk_score():
    raw = json.loads(FIXTURE.read_text())
    findings = parse_semgrep_output(raw)

    # every result in the real fixture is severity WARNING
    assert all(f["risk_score"] == 6.0 for f in findings)


def test_parse_semgrep_output_finding_id_uses_check_id_and_start_line():
    raw = json.loads(FIXTURE.read_text())
    findings = parse_semgrep_output(raw)

    consolidate_findings = [
        f for f in findings if f["file"] == ".github/workflows/consolidate.yml"
    ]
    assert {f["finding_id"] for f in consolidate_findings} == {
        "yaml.github-actions.security.github-actions-mutable-action-tag."
        "github-actions-mutable-action-tag:59",
        "yaml.github-actions.security.github-actions-mutable-action-tag."
        "github-actions-mutable-action-tag:65",
    }


def test_parse_semgrep_output_finding_ids_unique_per_file():
    # Regression-style check (see Task 2's repowise collector for the bug class this guards
    # against): finding_id = f"{check_id}:{start_line}" must be unique WITHIN a given file.
    # Verified against the real fixture: the same rule fires twice per file (two different
    # lines), and the same two-line pattern is duplicated across .github/workflows/ and
    # workflows/ (four distinct files total) -- so finding_id collides ACROSS files sharing
    # identical content, but never within a single file. Since `file` is a separate field in
    # the normalized contract and dedup keys on f"{source}:{file}:{finding_id}"
    # (per repowise_collector.py's documented convention), cross-file collisions are fine.
    raw = json.loads(FIXTURE.read_text())
    findings = parse_semgrep_output(raw)

    by_file: dict[str, list[str]] = {}
    for f in findings:
        by_file.setdefault(f["file"], []).append(f["finding_id"])

    assert len(by_file) == 4  # 2 unique workflow files x 2 duplicated tree locations
    for file_path, ids in by_file.items():
        assert len(ids) == len(set(ids)), f"finding_id collision within {file_path}: {ids}"


def test_run_semgrep_calls_semgrep_scan_and_parses_output():
    fake_stdout = json.dumps({"results": []})
    fake_result = MagicMock(stdout=fake_stdout, returncode=0)

    with patch("subprocess.run", return_value=fake_result) as mock_run:
        findings, ok = run_semgrep("/fake/repo")

    assert ok is True
    assert findings == []
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == ["semgrep", "scan", "--config", "auto", "--json"]
    assert kwargs["cwd"] == "/fake/repo"


def test_run_semgrep_treats_returncode_1_as_a_valid_run_with_findings():
    # semgrep exits 1 when findings are present -- that's not a failure.
    fake_stdout = json.dumps({"results": []})
    fake_result = MagicMock(stdout=fake_stdout, returncode=1)

    with patch("subprocess.run", return_value=fake_result):
        findings, ok = run_semgrep("/fake/repo")

    assert ok is True
    assert findings == []


def test_run_semgrep_returns_not_ok_on_unexpected_returncode():
    fake_result = MagicMock(stdout="{}", returncode=2)

    with patch("subprocess.run", return_value=fake_result):
        findings, ok = run_semgrep("/fake/repo")

    assert findings == []
    assert ok is False


def test_run_semgrep_returns_not_ok_on_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("semgrep", 300)):
        findings, ok = run_semgrep("/fake/repo")

    assert findings == []
    assert ok is False


def test_run_semgrep_returns_not_ok_when_semgrep_not_installed():
    with patch("subprocess.run", side_effect=FileNotFoundError("semgrep not found")):
        findings, ok = run_semgrep("/fake/repo")

    assert findings == []
    assert ok is False


def test_run_semgrep_returns_not_ok_on_invalid_json_output():
    fake_result = MagicMock(stdout="not valid json{{{", returncode=0)

    with patch("subprocess.run", return_value=fake_result):
        findings, ok = run_semgrep("/fake/repo")

    assert findings == []
    assert ok is False


def test_run_semgrep_against_real_fixture_via_mocked_subprocess():
    fake_stdout = FIXTURE.read_text()
    fake_result = MagicMock(stdout=fake_stdout, returncode=1)

    with patch("subprocess.run", return_value=fake_result):
        findings, ok = run_semgrep("/fake/repo")

    assert ok is True
    assert len(findings) == 8


def test_parse_semgrep_output_handles_result_missing_fields_with_fallbacks():
    # Regression test: a malformed results[] entry missing check_id/path/start.line must not
    # raise -- it should fall back to sensible defaults rather than KeyError. Field access in
    # parse_semgrep_output is defensive (.get()) precisely so this degrades instead of crashing.
    raw = {"results": [{"extra": {"severity": "WARNING", "message": "orphaned finding"}}]}

    findings = parse_semgrep_output(raw)

    assert len(findings) == 1
    finding = findings[0]
    assert finding["source"] == "semgrep"
    assert finding["file"] == "unknown"
    assert finding["finding_id"] == "unknown-rule:?"
    assert finding["risk_score"] == 6.0
    assert "orphaned finding" in finding["message"]


def test_run_semgrep_returns_not_ok_on_structurally_malformed_results_entry():
    # Regression test proving the fix for the coordinator-flagged gap: a results[] entry that
    # isn't a dict at all (e.g. `None`) can't be rescued by field-level .get() fallbacks inside
    # parse_semgrep_output (None.get(...) raises AttributeError). Previously this propagated
    # an uncaught exception straight out of run_semgrep, breaking its own documented contract
    # that every failure mode returns ([], False). Now run_semgrep's try/except around the
    # parse_semgrep_output call catches it and degrades gracefully instead of raising.
    fake_stdout = json.dumps({"results": [None]})
    fake_result = MagicMock(stdout=fake_stdout, returncode=1)

    with patch("subprocess.run", return_value=fake_result):
        findings, ok = run_semgrep("/fake/repo")  # must not raise

    assert findings == []
    assert ok is False


def test_parse_semgrep_output_maps_error_severity_to_risk_score():
    raw = {"results": [{
        "check_id": "rule.error", "path": "foo.py", "start": {"line": 1},
        "extra": {"severity": "ERROR", "message": "bad"},
    }]}
    findings = parse_semgrep_output(raw)
    assert findings[0]["risk_score"] == 9.0


def test_parse_semgrep_output_maps_info_severity_to_risk_score():
    raw = {"results": [{
        "check_id": "rule.info", "path": "foo.py", "start": {"line": 1},
        "extra": {"severity": "INFO", "message": "fyi"},
    }]}
    findings = parse_semgrep_output(raw)
    assert findings[0]["risk_score"] == 3.0


def test_parse_semgrep_output_maps_unrecognized_severity_to_default_risk_score():
    raw = {"results": [{
        "check_id": "rule.weird", "path": "foo.py", "start": {"line": 1},
        "extra": {"severity": "CRITICAL", "message": "future severity level"},
    }]}
    findings = parse_semgrep_output(raw)
    assert findings[0]["risk_score"] == 5.0
