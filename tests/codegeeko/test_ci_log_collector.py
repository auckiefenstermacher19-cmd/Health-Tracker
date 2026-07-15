import requests
from unittest.mock import MagicMock, patch

from codegeeko.collectors.ci_log_collector import parse_workflow_runs, run_ci_log_check

SAMPLE_RESPONSE = {
    "workflow_runs": [
        {
            "id": 111,
            "name": "Daily CSV Merge",
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://github.com/auckiefenstermacher19-cmd/Health-Tracker/actions/runs/111",
            "created_at": "2026-07-14T06:00:00Z",
        },
        {
            "id": 112,
            "name": "Daily CSV Merge",
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://github.com/auckiefenstermacher19-cmd/Health-Tracker/actions/runs/112",
            "created_at": "2026-07-13T06:00:00Z",
        },
    ]
}


def test_parse_workflow_runs_flags_only_failures():
    findings = parse_workflow_runs(SAMPLE_RESPONSE)

    assert len(findings) == 1
    assert findings[0]["source"] == "ci_log"
    assert findings[0]["file"] is None
    assert findings[0]["finding_id"] == "111"
    assert findings[0]["risk_score"] == 8.0
    assert "Daily CSV Merge" in findings[0]["message"]
    assert findings[0]["raw"]["id"] == 111


def test_parse_workflow_runs_handles_no_runs():
    assert parse_workflow_runs({"workflow_runs": []}) == []


def test_parse_workflow_runs_handles_empty_input():
    assert parse_workflow_runs({}) == []


def test_parse_workflow_runs_returns_normalized_shape_for_every_finding():
    findings = parse_workflow_runs(SAMPLE_RESPONSE)
    for finding in findings:
        assert finding["source"] == "ci_log"
        assert finding["file"] is None
        assert isinstance(finding["finding_id"], str)
        assert finding["finding_id"]
        assert 0.0 <= finding["risk_score"] <= 10.0
        assert isinstance(finding["message"], str)
        assert finding["message"]
        assert isinstance(finding["raw"], dict)


def test_parse_workflow_runs_skips_entry_with_missing_id():
    # A failed run missing its `id` field can't be given a genuine finding_id -- str(None)
    # would produce "None", which LOOKS like a valid finding_id string but isn't a real run
    # identity. Skip the entry rather than fabricate one.
    raw = {"workflow_runs": [{
        "name": "Broken", "conclusion": "failure",
        "html_url": "https://example.com/runs/1", "created_at": "2026-07-14T06:00:00Z",
    }]}
    assert parse_workflow_runs(raw) == []


def test_parse_workflow_runs_skips_entry_with_explicit_none_id():
    # `.get("id")` only substitutes a default on a MISSING key -- an explicit `"id": None`
    # must be caught too, or finding_id would become the string "None".
    raw = {"workflow_runs": [{
        "id": None, "name": "Broken", "conclusion": "failure",
        "html_url": "https://example.com/runs/1", "created_at": "2026-07-14T06:00:00Z",
    }]}
    assert parse_workflow_runs(raw) == []


def test_parse_workflow_runs_skips_entry_with_wrong_typed_id():
    # Regression test (coordinator review): a None-only check on `id` lets a wrong-typed value
    # (e.g. a list) through -- str(run_id) never raises, so `finding_id = "[111, 112]"` would
    # pass the shape contract (non-empty str) while not identifying any real run. Same class of
    # gap semgrep_collector.py closed for `path` via isinstance; applied here for `id`.
    raw = {"workflow_runs": [{
        "id": [111, 112], "name": "Broken", "conclusion": "failure",
        "html_url": "https://example.com/runs/1", "created_at": "2026-07-14T06:00:00Z",
    }]}
    assert parse_workflow_runs(raw) == []


def test_parse_workflow_runs_skips_entry_with_bool_id():
    # bool is an int subclass in Python -- True/False must not be accepted as a genuine run id
    # just because isinstance(True, int) is True.
    raw = {"workflow_runs": [{
        "id": True, "name": "Broken", "conclusion": "failure",
        "html_url": "https://example.com/runs/1", "created_at": "2026-07-14T06:00:00Z",
    }]}
    assert parse_workflow_runs(raw) == []


def test_parse_workflow_runs_skips_non_dict_entry_without_crashing():
    # A malformed workflow_runs entry (e.g. None or a bare string) must not crash the whole
    # batch -- it should degrade by skipping just that entry.
    raw = {"workflow_runs": [None, "not-a-run", SAMPLE_RESPONSE["workflow_runs"][0]]}
    findings = parse_workflow_runs(raw)
    assert len(findings) == 1
    assert findings[0]["finding_id"] == "111"


def test_parse_workflow_runs_handles_non_list_workflow_runs_without_crashing():
    assert parse_workflow_runs({"workflow_runs": "not-a-list"}) == []


def test_parse_workflow_runs_handles_non_dict_raw_without_crashing():
    assert parse_workflow_runs(None) == []
    assert parse_workflow_runs([]) == []


def test_parse_workflow_runs_falls_back_gracefully_for_missing_name_and_url_fields():
    # A failed run with a genuine id but missing name/created_at/html_url must still produce
    # a finding (those fields only ever flow into `message` via f-string, which can't violate
    # the normalized contract) rather than raising or being dropped.
    raw = {"workflow_runs": [{"id": 999, "conclusion": "failure"}]}
    findings = parse_workflow_runs(raw)
    assert len(findings) == 1
    assert findings[0]["finding_id"] == "999"
    assert isinstance(findings[0]["message"], str)
    assert findings[0]["message"]


def test_parse_workflow_runs_ignores_non_failure_conclusions():
    raw = {"workflow_runs": [
        {"id": 1, "conclusion": "success", "name": "a"},
        {"id": 2, "conclusion": "cancelled", "name": "b"},
        {"id": 3, "conclusion": None, "name": "c"},
        {"id": 4, "conclusion": "failure", "name": "d"},
    ]}
    findings = parse_workflow_runs(raw)
    assert len(findings) == 1
    assert findings[0]["finding_id"] == "4"


def test_run_ci_log_check_calls_github_api_and_parses_output():
    fake_response = MagicMock()
    fake_response.json.return_value = SAMPLE_RESPONSE
    fake_response.raise_for_status.return_value = None

    with patch("requests.get", return_value=fake_response) as mock_get:
        findings, ok = run_ci_log_check("auckiefenstermacher19-cmd", "Health-Tracker", "fake-token")

    assert ok is True
    assert len(findings) == 1
    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.github.com/repos/auckiefenstermacher19-cmd/Health-Tracker/actions/runs"
    assert kwargs["headers"]["Authorization"] == "Bearer fake-token"


def test_run_ci_log_check_returns_not_ok_on_request_exception():
    with patch("requests.get", side_effect=requests.RequestException("boom")):
        findings, ok = run_ci_log_check("owner", "repo", "token")

    assert findings == []
    assert ok is False


def test_run_ci_log_check_returns_not_ok_on_http_error_status():
    fake_response = MagicMock()
    fake_response.raise_for_status.side_effect = requests.HTTPError("401 Unauthorized")

    with patch("requests.get", return_value=fake_response):
        findings, ok = run_ci_log_check("owner", "repo", "bad-token")

    assert findings == []
    assert ok is False


def test_run_ci_log_check_returns_not_ok_on_json_decode_failure():
    # Regression test (coordinator review, issue 2): response.json() raising ValueError (e.g. a
    # proxy error page served with a 200 status, so the body isn't valid JSON at all) must be
    # treated as a FAILED check (ok=False), matching run_repowise/run_semgrep's established
    # contract that "couldn't parse the response" is not a clean run. Previously this returned
    # ([], True), silently reporting "checked, all CI runs green" instead of "couldn't tell".
    fake_response = MagicMock()
    fake_response.json.side_effect = ValueError("not valid JSON")
    fake_response.raise_for_status.return_value = None

    with patch("requests.get", return_value=fake_response):
        findings, ok = run_ci_log_check("owner", "repo", "token")

    assert findings == []
    assert ok is False


def test_run_ci_log_check_returns_ok_when_json_decodes_but_shape_is_wrong():
    # Distinct from the decode-failure case above: requests.get succeeds, raise_for_status
    # passes, AND response.json() successfully decodes -- but the decoded body isn't the
    # documented {"workflow_runs": [...]} shape (e.g. GitHub returned a bare None/list). The
    # request+response cycle itself was valid, so this stays ok=True with zero findings;
    # parse_workflow_runs already degrades the wrong shape to [] without raising.
    fake_response = MagicMock()
    fake_response.json.return_value = None
    fake_response.raise_for_status.return_value = None

    with patch("requests.get", return_value=fake_response):
        findings, ok = run_ci_log_check("owner", "repo", "token")

    assert findings == []
    assert ok is True
