import json
from pathlib import Path

from codegeeko.collectors.repowise_collector import parse_repowise_output

FIXTURE = Path(__file__).parent / "fixtures" / "repowise_sample_output.json"


def test_parse_repowise_output_returns_normalized_findings():
    raw = json.loads(FIXTURE.read_text())
    findings = parse_repowise_output(raw)

    assert isinstance(findings, list)
    assert findings  # the real fixture has both low-scoring files and biomarker findings
    for finding in findings:
        assert finding["source"] == "repowise"
        assert isinstance(finding["file"], str)
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
