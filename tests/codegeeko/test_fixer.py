import asyncio
from unittest.mock import patch

from codegeeko.fixer import fix_and_report

FINDING = {
    "source": "repowise", "file": "consolidate.py", "finding_id": "metric", "risk_score": 8.0,
    "message": "high complexity", "raw": {}, "triage_reason": "clear fix available",
}


async def _fake_query(*args, **kwargs):
    class _Msg:
        subtype = "success"
    yield _Msg()


@patch("codegeeko.fixer.open_fix_pr", return_value={"ok": True, "html_url": "https://github.com/x/y/pull/9"})
@patch("codegeeko.fixer.subprocess.run")
@patch("codegeeko.fixer.query", _fake_query)
def test_fix_and_report_opens_pr_when_tests_pass_on_first_try(mock_subprocess, mock_open_pr):
    mock_subprocess.return_value.returncode = 0

    result = fix_and_report(FINDING, ".", "owner", "repo", "tok")

    assert result == {"outcome": "pr", "url": "https://github.com/x/y/pull/9"}
    mock_open_pr.assert_called_once()


@patch("codegeeko.fixer.open_flag_issue", return_value={"ok": True, "html_url": "https://github.com/x/y/issues/3"})
@patch("codegeeko.fixer.subprocess.run")
@patch("codegeeko.fixer.query", _fake_query)
def test_fix_and_report_opens_issue_after_three_failed_attempts(mock_subprocess, mock_open_issue):
    mock_subprocess.return_value.returncode = 1  # tests keep failing every attempt

    result = fix_and_report(FINDING, ".", "owner", "repo", "tok")

    assert result == {"outcome": "issue", "url": "https://github.com/x/y/issues/3"}
    assert mock_subprocess.call_count >= 3
    mock_open_issue.assert_called_once()


@patch("codegeeko.fixer.open_fix_pr", return_value={"ok": False, "error": "GitHub API timeout"})
@patch("codegeeko.fixer.subprocess.run")
@patch("codegeeko.fixer.query", _fake_query)
def test_fix_and_report_degrades_gracefully_when_pr_creation_fails(mock_subprocess, mock_open_pr):
    mock_subprocess.return_value.returncode = 0  # fix succeeded, tests pass

    result = fix_and_report(FINDING, ".", "owner", "repo", "tok")

    assert result == {"outcome": "pr_failed", "error": "GitHub API timeout"}


@patch("codegeeko.fixer.open_flag_issue", return_value={"ok": False, "error": "GitHub API rate limited"})
@patch("codegeeko.fixer.subprocess.run")
@patch("codegeeko.fixer.query", _fake_query)
def test_fix_and_report_degrades_gracefully_when_issue_creation_fails(mock_subprocess, mock_open_issue):
    # Symmetrical to the PR-creation-failure case: the fix exhausted its attempts without tests
    # ever passing, and the fallback open_flag_issue call itself then fails (network/rate-limit).
    # Must not raise KeyError from an unchecked issue["html_url"] -- degrades to "issue_failed".
    mock_subprocess.return_value.returncode = 1  # tests never pass

    result = fix_and_report(FINDING, ".", "owner", "repo", "tok")

    assert result == {"outcome": "issue_failed", "error": "GitHub API rate limited"}


@patch("codegeeko.fixer.open_fix_pr", return_value={"ok": True, "html_url": "https://github.com/x/y/pull/9"})
@patch("codegeeko.fixer.subprocess.run")
@patch("codegeeko.fixer.query", _fake_query)
def test_fix_and_report_uses_branch_name_for_finding_and_commits_with_message(mock_subprocess, mock_open_pr):
    mock_subprocess.return_value.returncode = 0

    fix_and_report(FINDING, ".", "owner", "repo", "tok")

    first_call_args = mock_subprocess.call_args_list[0][0][0]
    assert first_call_args == ["git", "checkout", "-b", "codegeeko/repowise-consolidate-py-metric"]

    commit_calls = [c[0][0] for c in mock_subprocess.call_args_list if c[0][0][:2] == ["git", "commit"]]
    assert commit_calls == [["git", "commit", "-m", "fix: high complexity"]]


@patch("codegeeko.fixer.open_flag_issue", return_value={"ok": True, "html_url": "https://github.com/x/y/issues/3"})
@patch("codegeeko.fixer.subprocess.run")
@patch("codegeeko.fixer.query", _fake_query)
def test_fix_and_report_abandons_branch_when_tests_never_pass(mock_subprocess, mock_open_issue):
    mock_subprocess.return_value.returncode = 1

    fix_and_report(FINDING, ".", "owner", "repo", "tok")

    all_calls = [c[0][0] for c in mock_subprocess.call_args_list]
    assert ["git", "checkout", "main"] in all_calls
    assert ["git", "branch", "-D", "codegeeko/repowise-consolidate-py-metric"] in all_calls


@patch("codegeeko.fixer.open_fix_pr", return_value={"ok": True, "html_url": "https://github.com/x/y/pull/9"})
@patch("codegeeko.fixer.subprocess.run")
def test_fix_and_report_survives_a_hung_sdk_call_and_still_opens_pr(mock_subprocess, mock_open_pr):
    # A stalled/hung Claude Agent SDK call during a fix attempt must not hang the whole pipeline.
    # Once _FIX_TIMEOUT_SECONDS fires, the attempt is treated as "made no progress" and the retry
    # loop continues -- success is judged purely by whether the tests pass afterward, so a hung
    # attempt with tests already passing (e.g. no code change was actually needed) still reports
    # a PR outcome rather than crashing/hanging the whole run.
    async def _slow_query(*args, **kwargs):
        await asyncio.sleep(0.3)
        class _Msg:
            subtype = "success"
        yield _Msg()

    mock_subprocess.return_value.returncode = 0

    with (
        patch("codegeeko.fixer.query", _slow_query),
        patch("codegeeko.fixer._FIX_TIMEOUT_SECONDS", 0.05),
    ):
        result = fix_and_report(FINDING, ".", "owner", "repo", "tok")

    assert result == {"outcome": "pr", "url": "https://github.com/x/y/pull/9"}


@patch("codegeeko.fixer.open_flag_issue", return_value={"ok": True, "html_url": "https://github.com/x/y/issues/3"})
@patch("codegeeko.fixer.subprocess.run")
def test_fix_and_report_survives_sdk_raising_mid_attempt_and_still_opens_issue(mock_subprocess, mock_open_issue):
    # query() crosses an external trust boundary (the Claude Code CLI subprocess) -- any
    # exception raised mid-iteration (process fails to spawn, exits non-zero, broken pipe,
    # auth/config error) must not propagate out of fix_and_report and crash the nightly run. It
    # should degrade to "this attempt made no progress", same as a timeout, and the existing
    # 3-attempt retry loop already tolerates that.
    async def _raising_query(*args, **kwargs):
        raise RuntimeError("claude code CLI process exited non-zero")
        yield  # pragma: no cover - makes this an async generator; never reached

    mock_subprocess.return_value.returncode = 1  # tests never pass

    with patch("codegeeko.fixer.query", _raising_query):
        result = fix_and_report(FINDING, ".", "owner", "repo", "tok")

    assert result == {"outcome": "issue", "url": "https://github.com/x/y/issues/3"}
