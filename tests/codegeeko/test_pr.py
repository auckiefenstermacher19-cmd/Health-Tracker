import requests
from unittest.mock import Mock, patch

from codegeeko.pr import branch_name_for, open_fix_pr, open_flag_issue

FINDING = {"source": "repowise", "file": "consolidate.py", "finding_id": "metric", "risk_score": 8.0, "message": "x", "raw": {}}
OTHER_FINDING_SAME_FILE = {"source": "repowise", "file": "consolidate.py", "finding_id": "run_pipeline:complex_method", "risk_score": 9.0, "message": "y", "raw": {}}


def test_branch_name_for_is_slug_safe_and_unique_per_finding():
    name = branch_name_for(FINDING)
    assert name.startswith("codegeeko/")
    assert " " not in name
    assert "consolidate" in name


def test_branch_name_for_differs_for_two_findings_on_the_same_file():
    assert branch_name_for(FINDING) != branch_name_for(OTHER_FINDING_SAME_FILE)


def test_branch_name_for_handles_none_file_without_crashing():
    # ci_log_collector's findings always have file=None (repo-level, no source file). A naive
    # `finding["file"].lower()` would raise AttributeError on this legitimate, real input.
    finding = {"source": "ci_log", "file": None, "finding_id": "111", "risk_score": 8.0, "message": "m", "raw": {}}
    name = branch_name_for(finding)
    assert name.startswith("codegeeko/")
    assert " " not in name
    assert name  # non-empty, well-formed


def test_branch_name_for_two_none_file_findings_with_different_ids_still_differ():
    a = branch_name_for({"source": "ci_log", "file": None, "finding_id": "111", "risk_score": 8.0, "message": "m", "raw": {}})
    b = branch_name_for({"source": "ci_log", "file": None, "finding_id": "112", "risk_score": 8.0, "message": "m", "raw": {}})
    assert a != b


def test_branch_name_for_handles_symbol_only_file_that_slugifies_empty():
    # A file/finding_id that is entirely non-alphanumeric (e.g. "???") slugifies to "" via the
    # regex substitution alone -- must fall back to something non-empty and well-formed, not
    # silently collapse the branch name's structure.
    finding = {"source": "repowise", "file": "???", "finding_id": "!!!", "risk_score": 8.0, "message": "m", "raw": {}}
    name = branch_name_for(finding)
    assert name.startswith("codegeeko/")
    assert " " not in name
    assert not name.endswith("-")
    assert "--" not in name


def test_branch_name_for_two_symbol_only_findings_with_different_content_still_differ():
    a = branch_name_for({"source": "repowise", "file": "???", "finding_id": "x", "risk_score": 8.0, "message": "m", "raw": {}})
    b = branch_name_for({"source": "repowise", "file": "!!!", "finding_id": "x", "risk_score": 8.0, "message": "m", "raw": {}})
    assert a != b


@patch("codegeeko.pr.requests.post")
def test_open_fix_pr_posts_to_pulls_endpoint(mock_post):
    mock_post.return_value = Mock(status_code=201, json=lambda: {"html_url": "https://github.com/x/y/pull/1"})

    result = open_fix_pr("owner", "repo", "tok", "codegeeko/fix-x", "Fix x", "body", base="main")

    mock_post.assert_called_once()
    called_url = mock_post.call_args.args[0]
    assert called_url == "https://api.github.com/repos/owner/repo/pulls"
    assert result["html_url"] == "https://github.com/x/y/pull/1"
    assert result["ok"] is True


@patch("codegeeko.pr.requests.post")
def test_open_fix_pr_sends_auth_header_and_expected_payload(mock_post):
    mock_post.return_value = Mock(status_code=201, json=lambda: {"html_url": "https://github.com/x/y/pull/1"})

    open_fix_pr("owner", "repo", "tok", "codegeeko/fix-x", "Fix x", "the body", base="main")

    kwargs = mock_post.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    assert kwargs["json"] == {"title": "Fix x", "head": "codegeeko/fix-x", "base": "main", "body": "the body"}
    assert kwargs["timeout"] == 30


@patch("codegeeko.pr.requests.post")
def test_open_fix_pr_degrades_gracefully_on_request_exception(mock_post):
    # A network error/timeout must not raise out of open_fix_pr -- Task 11 calls this as one
    # step of a multi-attempt fix pipeline, and an uncaught exception here would crash the whole
    # nightly run over what should be a single retryable, per-finding failure.
    mock_post.side_effect = requests.RequestException("boom")

    result = open_fix_pr("owner", "repo", "tok", "codegeeko/fix-x", "Fix x", "body")

    assert result["ok"] is False
    assert "boom" in result["error"]


@patch("codegeeko.pr.requests.post")
def test_open_fix_pr_degrades_gracefully_on_http_error_status(mock_post):
    response = Mock(status_code=422)
    response.raise_for_status.side_effect = requests.HTTPError("422 Unprocessable Entity")
    mock_post.return_value = response

    result = open_fix_pr("owner", "repo", "tok", "codegeeko/fix-x", "Fix x", "body")

    assert result["ok"] is False
    assert "422" in result["error"]


@patch("codegeeko.pr.requests.post")
def test_open_fix_pr_degrades_gracefully_on_undecodable_json_body(mock_post):
    response = Mock(status_code=201)
    response.json.side_effect = ValueError("not valid JSON")
    mock_post.return_value = response

    result = open_fix_pr("owner", "repo", "tok", "codegeeko/fix-x", "Fix x", "body")

    assert result["ok"] is False


@patch("codegeeko.pr.requests.post")
def test_open_flag_issue_posts_to_issues_endpoint(mock_post):
    mock_post.return_value = Mock(status_code=201, json=lambda: {"html_url": "https://github.com/x/y/issues/2"})

    result = open_flag_issue("owner", "repo", "tok", "Flag: x", "body")

    called_url = mock_post.call_args.args[0]
    assert called_url == "https://api.github.com/repos/owner/repo/issues"
    assert result["html_url"] == "https://github.com/x/y/issues/2"
    assert result["ok"] is True


@patch("codegeeko.pr.requests.post")
def test_open_flag_issue_degrades_gracefully_on_request_exception(mock_post):
    mock_post.side_effect = requests.RequestException("boom")

    result = open_flag_issue("owner", "repo", "tok", "Flag: x", "body")

    assert result["ok"] is False
    assert "boom" in result["error"]
