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
    # Regression test: dashboard.js alone produces 12 findings-derived entries plus 1
    # metrics-derived entry, all sharing file="dashboard.js". A downstream dedup dict keyed
    # only by f"{source}:{file}" would silently collapse all 13 into one. Every finding_id
    # within a given file must be distinct so f"{source}:{file}:{finding_id}" is a safe key.
    raw = json.loads(FIXTURE.read_text())
    findings = parse_repowise_output(raw)

    by_file: dict[str, list[str]] = {}
    for f in findings:
        by_file.setdefault(f["file"], []).append(f["finding_id"])

    dashboard_ids = by_file["dashboard.js"]
    assert len(dashboard_ids) == 13  # 12 biomarker findings + 1 metrics finding
    assert len(dashboard_ids) == len(set(dashboard_ids)), (
        f"finding_id collision within dashboard.js: {dashboard_ids}"
    )

    # every file's finding_ids must be unique within that file, not just dashboard.js
    for file_path, ids in by_file.items():
        assert len(ids) == len(set(ids)), f"finding_id collision within {file_path}: {ids}"

    # the specific real collision this regression guards against: two identical
    # buildCoaching/complex_conditional entries on dashboard.js must still get distinct ids
    coaching_ids = [
        f["finding_id"] for f in findings
        if f["file"] == "dashboard.js"
        and f["raw"].get("function_name") == "buildCoaching"
        and f["raw"].get("biomarker_type") == "complex_conditional"
    ]
    assert coaching_ids == ["buildCoaching:complex_conditional", "buildCoaching:complex_conditional#2"]
