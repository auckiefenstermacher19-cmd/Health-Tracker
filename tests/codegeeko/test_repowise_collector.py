import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from codegeeko.collectors.repowise_collector import parse_repowise_output, run_repowise

FIXTURE = Path(__file__).parent / "fixtures" / "repowise_sample_output.json"


def test_parse_repowise_output_returns_normalized_findings():
    raw = json.loads(FIXTURE.read_text())
    findings = parse_repowise_output(raw)

    assert isinstance(findings, list)
    assert findings  # the real fixture has both low-scoring files and biomarker findings
    for finding in findings:
        assert finding["source"] == "repowise"
        assert isinstance(finding["file"], str)
        assert isinstance(finding["finding_id"], str)
        assert finding["finding_id"]
        assert 0.0 <= finding["risk_score"] <= 10.0
        assert isinstance(finding["message"], str)
        assert finding["message"]
        assert finding["raw"]


def test_parse_repowise_output_handles_empty_input():
    assert parse_repowise_output({}) == []


def test_parse_repowise_output_maps_worst_file_metric_to_high_risk():
    raw = json.loads(FIXTURE.read_text())
    findings = parse_repowise_output(raw)

    # dashboard.js is the fixture's worst performer: metrics score 6.0/10 -> risk_score 4.0
    dashboard_metric_findings = [
        f for f in findings
        if f["file"] == "dashboard.js" and f["raw"].get("file_path") == "dashboard.js"
        and "score" in f["raw"]
    ]
    assert dashboard_metric_findings
    assert any(f["risk_score"] == 4.0 for f in dashboard_metric_findings)


def test_parse_repowise_output_includes_biomarker_findings():
    raw = json.loads(FIXTURE.read_text())
    findings = parse_repowise_output(raw)

    # the critical renderDay complex_method biomarker should surface as a high-risk finding
    critical = [
        f for f in findings
        if f["raw"].get("biomarker_type") == "complex_method"
        and f["raw"].get("function_name") == "renderDay"
    ]
    assert critical
    assert critical[0]["risk_score"] == 10.0
    assert "renderDay" in critical[0]["message"]


def test_parse_repowise_output_skips_perfect_score_files():
    raw = json.loads(FIXTURE.read_text())
    findings = parse_repowise_output(raw)

    # README.md scored a perfect 10.0/10 with no biomarkers -> no finding emitted for it
    assert not any(f["file"] == "README.md" for f in findings)


def test_parse_repowise_output_finding_ids_unique_per_file():
    # Regression test: dashboard.js alone produces 11 distinct (function_name, biomarker_type)
    # groups in raw["findings"] plus 1 metrics entry, all sharing file="dashboard.js". A
    # downstream dedup dict keyed only by f"{source}:{file}" would silently collapse all 12
    # into one. Every finding_id within a given file must be distinct so
    # f"{source}:{file}:{finding_id}" is a safe key. (Verified programmatically against the
    # fixture: raw["findings"] has 27 entries but only 26 distinct (file_path, function_name,
    # biomarker_type) triples — dashboard.js/buildCoaching/complex_conditional appears twice —
    # so after collapsing, dashboard.js has 11 distinct findings-derived groups, not 12.)
    raw = json.loads(FIXTURE.read_text())
    findings = parse_repowise_output(raw)

    by_file: dict[str, list[str]] = {}
    for f in findings:
        by_file.setdefault(f["file"], []).append(f["finding_id"])

    dashboard_ids = by_file["dashboard.js"]
    assert len(dashboard_ids) == 12  # 11 collapsed biomarker groups + 1 metrics finding
    assert len(dashboard_ids) == len(set(dashboard_ids)), (
        f"finding_id collision within dashboard.js: {dashboard_ids}"
    )

    # every file's finding_ids must be unique within that file, not just dashboard.js
    for file_path, ids in by_file.items():
        assert len(ids) == len(set(ids)), f"finding_id collision within {file_path}: {ids}"

    # the specific real collision this regression guards against: two field-identical
    # buildCoaching/complex_conditional entries on dashboard.js collapse into ONE finding
    # (not two positionally-numbered ones, since raw["findings"]'s order is not documented as
    # stable across repowise runs), with the occurrence count surfaced in the message instead.
    coaching_findings = [
        f for f in findings
        if f["file"] == "dashboard.js"
        and f["raw"].get("function_name") == "buildCoaching"
        and f["raw"].get("biomarker_type") == "complex_conditional"
    ]
    assert len(coaching_findings) == 1
    assert coaching_findings[0]["finding_id"] == "buildCoaching:complex_conditional"
    assert "occurs 2 times" in coaching_findings[0]["message"]


def test_run_repowise_calls_init_then_health_and_parses_output():
    fake_stdout = json.dumps({"metrics": [], "findings": []})
    fake_result = MagicMock(stdout=fake_stdout)

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [MagicMock(), fake_result]  # init call, then health call
        findings, ok = run_repowise("/fake/repo")

    assert ok is True
    assert findings == []
    assert mock_run.call_count == 2

    init_args, init_kwargs = mock_run.call_args_list[0]
    assert init_args[0] == ["repowise", "init", ".", "--index-only"]
    assert init_kwargs["cwd"] == "/fake/repo"

    health_args, health_kwargs = mock_run.call_args_list[1]
    assert health_args[0] == ["repowise", "health", "--format", "json"]
    assert health_kwargs["cwd"] == "/fake/repo"


def test_run_repowise_returns_not_ok_on_called_process_error():
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "repowise")):
        findings, ok = run_repowise("/fake/repo")

    assert findings == []
    assert ok is False


def test_run_repowise_returns_not_ok_on_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("repowise", 60)):
        findings, ok = run_repowise("/fake/repo")

    assert findings == []
    assert ok is False
