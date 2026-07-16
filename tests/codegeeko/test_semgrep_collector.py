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
    assert finding["finding_id"].startswith("unknown-rule:?:")  # placeholder + content hash
    assert finding["risk_score"] == 6.0
    assert "orphaned finding" in finding["message"]


def test_parse_semgrep_output_treats_explicit_none_values_same_as_missing_keys():
    # Regression test (coordinator re-review, round 2): .get(key, default) only applies its
    # default when the key is ABSENT, not when it's present with value None. A corrupted
    # capture with `"check_id": null, "path": null` must still produce a valid non-None `file`
    # str and a usable finding_id -- not `finding["file"] = None`, which would violate the
    # normalized contract that `file` is always `str`.
    raw = {"results": [{
        "check_id": None,
        "path": None,
        "start": {"line": 1},
        "extra": {"severity": "WARNING", "message": "explicit nulls"},
    }]}

    findings = parse_semgrep_output(raw)

    assert len(findings) == 1
    finding = findings[0]
    assert isinstance(finding["file"], str)
    assert finding["file"] == "unknown"
    assert isinstance(finding["finding_id"], str) and finding["finding_id"]
    assert finding["finding_id"].startswith("unknown-rule:1:")


def test_parse_semgrep_output_disambiguates_distinct_malformed_entries_in_same_batch():
    # Regression test (coordinator re-review, round 2): two DIFFERENT malformed entries in the
    # same batch, both missing check_id/path/start, must not collapse onto the identical
    # placeholder finding_id ("unknown-rule:?") -- that would be a real within-file finding_id
    # collision, silently dropping one of them under the f"{source}:{file}:{finding_id}" dedup
    # convention. The chosen fix: a content-hash suffix, so entries that differ in their
    # remaining content (here, severity/message) get distinct finding_ids.
    raw = {"results": [
        {"extra": {"severity": "WARNING", "message": "malformed warning entry"}},
        {"extra": {"severity": "ERROR", "message": "malformed error entry"}},
    ]}

    findings = parse_semgrep_output(raw)

    assert len(findings) == 2
    assert findings[0]["file"] == findings[1]["file"] == "unknown"
    ids = [f["finding_id"] for f in findings]
    assert len(ids) == len(set(ids)), f"finding_id collision between distinct malformed entries: {ids}"
    assert findings[0]["risk_score"] == 6.0
    assert findings[1]["risk_score"] == 9.0


def test_parse_semgrep_output_collapses_byte_identical_malformed_entries_by_design():
    # Documents the deliberate, tested boundary of the content-hash disambiguation: two
    # malformed entries that are byte-identical (same missing fields, same severity, same
    # message) have no content-based way to be told apart, so they hash to the SAME finding_id
    # and collapse -- the same intentional choice repowise_collector.py makes for genuinely
    # indistinguishable duplicates, rather than an arbitrary/unstable position-based numbering.
    # This is an explicit, verified decision, not an untested side effect.
    identical_entry = {"extra": {"severity": "WARNING", "message": "same malformed entry"}}
    raw = {"results": [identical_entry, dict(identical_entry)]}

    findings = parse_semgrep_output(raw)

    assert len(findings) == 2  # parse_semgrep_output never dedupes -- both still appear
    assert findings[0]["finding_id"] == findings[1]["finding_id"]  # but they share a finding_id


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


def test_parse_semgrep_output_handles_non_dict_extra_without_raising():
    # Regression test (coordinator re-review, round 3, Gap 1): `extra` had no type guard, unlike
    # `start`. A truthy-but-non-dict `extra` (e.g. a list) previously left `extra.get(...)` to
    # raise AttributeError uncaught inside parse_semgrep_output itself -- caught only one layer
    # up in run_semgrep, where it drops the ENTIRE batch instead of just this one entry. Now
    # `extra` gets the same isinstance(dict) guard `start` already had, so this degrades to the
    # documented WARNING/empty-message default per-entry, without raising at all.
    raw = {"results": [{
        "check_id": "rule.bad-extra", "path": "foo.py", "start": {"line": 1},
        "extra": ["not", "a", "dict"],
    }]}

    findings = parse_semgrep_output(raw)  # must not raise

    assert len(findings) == 1
    assert findings[0]["risk_score"] == 6.0  # falls back to default "WARNING" severity
    assert findings[0]["message"] == "rule.bad-extra: "


def test_run_semgrep_does_not_drop_whole_batch_on_one_entry_with_invalid_extra_type():
    # Proves the per-entry-degradation promise actually holds now: a batch with ONE entry that
    # has a non-dict `extra` alongside an otherwise well-formed entry must retain BOTH findings,
    # not silently drop the whole batch the way it would have before extra's isinstance guard
    # (when the AttributeError would've propagated out of parse_semgrep_output and been caught
    # by run_semgrep's outer try/except, discarding everything).
    raw = {"results": [
        {"check_id": "rule.bad-extra", "path": "foo.py", "start": {"line": 1}, "extra": "junk"},
        {"check_id": "rule.good", "path": "bar.py", "start": {"line": 2},
         "extra": {"severity": "ERROR", "message": "a real finding"}},
    ]}
    fake_result = MagicMock(stdout=json.dumps(raw), returncode=1)

    with patch("subprocess.run", return_value=fake_result):
        findings, ok = run_semgrep("/fake/repo")

    assert ok is True
    assert len(findings) == 2
    assert any(f["finding_id"] == "rule.good:2" and f["risk_score"] == 9.0 for f in findings)


def test_parse_semgrep_output_wrong_typed_path_falls_back_to_str_and_disambiguates():
    # Regression test (coordinator re-review, round 3, Gap 2): a present-but-wrong-typed `path`
    # (e.g. an int) previously passed through unchanged -- finding["file"] would end up an int,
    # violating the file-must-be-str contract this whole task history has been chasing -- and,
    # since the value was truthy, used_fallback never fired, so no SHA-1 disambiguation suffix
    # was added either. Now a non-str `path` is treated as invalid: falls back to "unknown" AND
    # counts toward used_fallback, exactly like a missing path would.
    raw = {"results": [{"check_id": "rule.bad-path", "path": 123, "start": {"line": 1},
                         "extra": {"severity": "WARNING", "message": "int path"}}]}

    findings = parse_semgrep_output(raw)

    assert len(findings) == 1
    finding = findings[0]
    assert isinstance(finding["file"], str)
    assert finding["file"] == "unknown"
    assert finding["finding_id"].startswith("rule.bad-path:1:")  # hash suffix present


def test_parse_semgrep_output_handles_unhashable_severity_without_raising():
    # Self-audit finding (coordinator re-review, round 3, item 3): `_SEVERITY_TO_RISK.get(severity,
    # ...)` would raise TypeError if `severity` were an unhashable type (e.g. a list) -- a dict
    # lookup can't hash an unhashable key. Guarded by checking isinstance(severity, str) before
    # the lookup; any non-str severity (unhashable or not) falls back to the default risk score.
    raw = {"results": [{"check_id": "rule.weird-severity", "path": "foo.py", "start": {"line": 1},
                         "extra": {"severity": ["WARNING"], "message": "list severity"}}]}

    findings = parse_semgrep_output(raw)  # must not raise

    assert len(findings) == 1
    assert findings[0]["risk_score"] == 5.0
