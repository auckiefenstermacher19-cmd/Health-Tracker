import asyncio
import subprocess

from claude_agent_sdk import ClaudeAgentOptions, query

from codegeeko.pr import branch_name_for, open_fix_pr, open_flag_issue

_FIX_PROMPT_TEMPLATE = """Fix this code health finding in the current repo, on the current git \
branch. Finding: {message} in {file} (source: {source}). Why it was accepted: {reason}. Make the \
smallest change that resolves it, then stop — do not run tests yourself, the caller will."""

MAX_ATTEMPTS = 3

# A fix attempt actually edits files and runs tools (Read/Write/Edit/Bash), unlike
# codegeeko/triage.py's read-only classification call, so it reasonably needs more headroom than
# triage's 90s budget -- 10 minutes gives a real edit-and-iterate attempt room to work without
# leaving a hung external process able to stall the whole nightly run indefinitely.
_FIX_TIMEOUT_SECONDS = 600


def _run_fix_attempt(finding: dict, repo_path: str) -> None:
    """Ask Claude to attempt a fix for `finding` in `repo_path`.

    Deliberately returns nothing (no success/failure signal) -- `fix_and_report`'s retry loop
    already judges an attempt's outcome purely by whether the test suite passes afterward, so a
    fix attempt that hangs, errors, or produces a broken/incomplete change is just "this attempt
    made no usable progress", which the existing MAX_ATTEMPTS retry loop already tolerates.

    Both a timeout and any exception raised by the SDK are swallowed here rather than
    propagated, mirroring codegeeko/triage.py's `_run_triage_query`: this call crosses the same
    external trust boundary (the Claude Agent SDK / underlying Claude Code CLI subprocess we
    don't control), which can fail in ways that have nothing to do with the fix itself -- a
    stalled/hung CLI process, a process that fails to spawn, a broken pipe, an auth/config error,
    etc. Left unguarded, any of those would either hang or crash the entire fix/PR pipeline over
    what should be a single retryable attempt.
    """
    options = ClaudeAgentOptions(
        model="claude-sonnet-5",
        allowed_tools=["Read", "Write", "Edit", "Bash"],
        permission_mode="bypassPermissions",
        cwd=repo_path,
    )
    prompt = _FIX_PROMPT_TEMPLATE.format(
        message=finding["message"], file=finding["file"],
        source=finding["source"], reason=finding["triage_reason"],
    )

    async def _run():
        async for _ in query(prompt=prompt, options=options):
            pass

    try:
        asyncio.run(asyncio.wait_for(_run(), timeout=_FIX_TIMEOUT_SECONDS))
    except asyncio.TimeoutError:
        return
    except Exception:
        # Broad catch is deliberate here, same rationale as codegeeko/triage.py: this is the
        # external trust boundary, and every failure mode already degrades to the same
        # "no progress this attempt" outcome rather than propagating.
        return


def _run_tests(repo_path: str) -> bool:
    result = subprocess.run(["pytest", "-x"], cwd=repo_path, capture_output=True, timeout=300)
    return result.returncode == 0


def fix_and_report(finding: dict, repo_path: str, owner: str, repo: str, token: str) -> dict:
    """Create a branch, ask Claude to fix `finding`, retry up to MAX_ATTEMPTS times against the
    test suite, then open a PR (tests pass) or flag an Issue (tests never pass).

    The `git` subprocess calls below (checkout/add/commit/push/branch -D) intentionally keep
    `check=True` and are NOT wrapped in a try/except, unlike the PR/Issue HTTP calls. This is a
    deliberate asymmetry: `open_fix_pr`/`open_flag_issue` degrade gracefully because they cross a
    genuinely flaky external boundary (network calls to the GitHub API, where a transient
    failure -- rate limit, timeout, blip -- is expected and recoverable by simply reporting
    `*_failed` and moving on). A `git` operation on our own local checkout, by contrast, is
    expected to always succeed under normal preconditions; if one fails (e.g. a stale branch left
    over from a prior crashed run, a dirty working tree, git misconfiguration in the runner) that
    signals an environment/state problem a human should see immediately, not something to quietly
    launder into a misleading "issue" outcome that looks like a normal code-review flag. Letting
    it raise loudly here is the more honest failure mode for a non-recoverable local error.
    That said, one finding's git failure must not take down the whole nightly batch of findings
    or skip `save_state()` for the rest -- callers (see codegeeko/run.py) are expected to catch
    around each per-finding call to `fix_and_report` and continue to the next finding.
    """
    branch = branch_name_for(finding)
    subprocess.run(["git", "checkout", "-b", branch], cwd=repo_path, check=True, capture_output=True)

    passed = False
    for _ in range(MAX_ATTEMPTS):
        _run_fix_attempt(finding, repo_path)
        subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True, capture_output=True)
        passed = _run_tests(repo_path)
        if passed:
            break

    body = f"**Finding:** {finding['message']}\n**File:** {finding['file']}\n**Why flagged:** {finding['triage_reason']}"

    if passed:
        subprocess.run(["git", "commit", "-m", f"fix: {finding['message']}"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "push", "-u", "origin", branch], cwd=repo_path, check=True, capture_output=True)
        pr = open_fix_pr(owner, repo, token, branch, f"Code-Geeko: {finding['message']}", body + "\n\n**Tests:** passing.")
        if not pr.get("ok"):
            return {"outcome": "pr_failed", "error": pr.get("error", "unknown error")}
        return {"outcome": "pr", "url": pr["html_url"]}

    subprocess.run(["git", "checkout", "main"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-D", branch], cwd=repo_path, check=True, capture_output=True)
    issue = open_flag_issue(owner, repo, token, f"Code-Geeko flag: {finding['message']}", body + f"\n\n**Tests:** failed after {MAX_ATTEMPTS} attempts, no fix applied.")
    if not issue.get("ok"):
        return {"outcome": "issue_failed", "error": issue.get("error", "unknown error")}
    return {"outcome": "issue", "url": issue["html_url"]}
