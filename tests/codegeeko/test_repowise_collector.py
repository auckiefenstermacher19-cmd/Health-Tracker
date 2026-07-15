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


def test_parse_repowise_output_representative_selection_is_order_independent():
    # Regression test: grouping by (file_path, function_name, biomarker_type) only guarantees
    # finding_id stability. It does NOT guarantee the group's members share the same
    # severity/reason/raw payload. If the representative were picked by list position
    # (items[0]), the SAME finding_id could carry a DIFFERENT risk_score/message across two
    # runs where repowise happened to order the duplicates differently — silently corrupting
    # Task 6's (file, finding_id)-keyed change detection. The representative must instead be
    # chosen deterministically (worst severity wins, tie broken by content), regardless of
    # input order.
    item_low = {
        "biomarker_type": "complex_method",
        "severity": "low",
        "file_path": "foo.py",
        "function_name": "bar",
        "health_impact": 0.1,
        "details": {},
        "reason": "bar low severity duplicate",
    }
    item_critical = {
        "biomarker_type": "complex_method",
        "severity": "critical",
        "file_path": "foo.py",
        "function_name": "bar",
        "health_impact": 0.9,
        "details": {},
        "reason": "bar critical severity duplicate",
    }

    raw_order_a = {"metrics": [], "findings": [item_low, item_critical]}
    raw_order_b = {"metrics": [], "findings": [item_critical, item_low]}

    findings_a = parse_repowise_output(raw_order_a)
    findings_b = parse_repowise_output(raw_order_b)

    assert len(findings_a) == 1
    assert len(findings_b) == 1

    # the worst (critical) instance must win as the representative, in BOTH input orders
    assert findings_a[0]["finding_id"] == findings_b[0]["finding_id"] == "bar:complex_method"
    assert findings_a[0]["risk_score"] == findings_b[0]["risk_score"] == 10.0
    assert findings_a[0]["message"] == findings_b[0]["message"]
    assert findings_a[0]["raw"] == findings_b[0]["raw"] == item_critical
    assert "occurs 2 times" in findings_a[0]["message"]


def test_parse_repowise_output_representative_selection_ties_are_content_deterministic():
    # Same severity on both duplicates (no severity to break the tie on) — the JSON-serialized
    # content tiebreak must still produce the SAME representative regardless of input order.
    item_a = {
        "biomarker_type": "large_method",
        "severity": "medium",
        "file_path": "foo.py",
        "function_name": "baz",
        "health_impact": 0.2,
        "details": {},
        "reason": "baz is 50 lines long (variant A)",
    }
    item_b = {
        "biomarker_type": "large_method",
        "severity": "medium",
        "file_path": "foo.py",
        "function_name": "baz",
        "health_impact": 0.2,
        "details": {},
        "reason": "baz is 50 lines long (variant B)",
    }

    findings_order_1 = parse_repowise_output({"metrics": [], "findings": [item_a, item_b]})
    findings_order_2 = parse_repowise_output({"metrics": [], "findings": [item_b, item_a]})

    assert findings_order_1[0]["raw"] == findings_order_2[0]["raw"]
    assert findings_order_1[0]["message"] == findings_order_2[0]["message"]


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


def test_run_repowise_returns_not_ok_when_repowise_not_installed():
    with patch("subprocess.run", side_effect=FileNotFoundError("repowise not found")):
        findings, ok = run_repowise("/fake/repo")

    assert findings == []
    assert ok is False


def test_run_repowise_returns_not_ok_on_invalid_json_output():
    fake_result = MagicMock(stdout="not valid json{{{")

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [MagicMock(), fake_result]  # init call, then health call
        findings, ok = run_repowise("/fake/repo")

    assert findings == []
    assert ok is False
