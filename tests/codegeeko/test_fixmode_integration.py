"""Fix-mode integration test: run.py's fix loop over TWO accepted findings, against a REAL git repo.

Every other test in this suite mocks `subprocess.run`, so they assert that the right git commands
were *issued* -- they cannot see what those commands actually do to a repository. Branch
contamination (each fix branch stacking on the previous one instead of forking from main) is
invisible at that level: the command list looks perfectly correct either way. Only a real git
sequence over more than one finding exposes it, which is why the plan calls for exactly this test.

Fully mocked at the external boundaries -- `_run_fix_attempt` (the Claude Agent SDK) and
`open_fix_pr` (the GitHub API) never run. NO billed model calls, no network, no real PRs. The git
operations are real but confined to a pytest tmp_path (system temp, deliberately not the
OneDrive-synced tree, whose file locking breaks git admin directories).
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from codegeeko.run import main


def _git(repo, *args) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _finding(index: int) -> dict:
    return {
        "source": "repowise",
        "file": f"mod{index}.py",
        "finding_id": "metric",
        "risk_score": 8.0,
        "message": f"finding {index}",
        "raw": {},
        "triage_reason": "clear fix available",
    }


@pytest.fixture
def temp_repo(tmp_path):
    """A real git repo with a real `origin` bare remote, so `git push` genuinely succeeds."""
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True
    )

    repo = tmp_path / "work"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "codegeeko@test.local")
    _git(repo, "config", "user.name", "Code-Geeko Test")
    _git(repo, "remote", "add", "origin", str(origin))

    for index in (0, 1):
        Path(repo, f"mod{index}.py").write_text(f"original {index}\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "push", "-u", "origin", "main")

    return repo


def _run_fix_mode(repo, monkeypatch, findings, *, tests=True, pr=None):
    """Drive one full fix-mode run of `main()` against `repo`.

    `tests` is either a bool (every test run gets that result) or a list consumed one call at a
    time, which is how a run where some findings are fixable and others are not gets expressed --
    each finding burns up to MAX_ATTEMPTS calls.
    """
    monkeypatch.chdir(repo)
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("REPORT_ONLY", "false")

    def _fake_fix_attempt(finding, repo_path):
        Path(repo_path, finding["file"]).write_text(f"fixed {finding['file']}\n", encoding="utf-8")

    tests_kwargs = {"side_effect": tests} if isinstance(tests, list) else {"return_value": tests}

    with (
        patch("codegeeko.run.load_state", return_value={"findings": {}, "checked_sources": {}}),
        patch("codegeeko.run.collect_all", return_value=(findings, {"repowise": "ok"})),
        patch("codegeeko.run.triage_findings", return_value=(findings, True)),
        patch("codegeeko.fixer._run_fix_attempt", side_effect=_fake_fix_attempt),
        patch("codegeeko.fixer._run_tests", **tests_kwargs),
        patch(
            "codegeeko.fixer.open_fix_pr",
            return_value=pr or {"ok": True, "html_url": "https://x/pull/1"},
        ),
        patch(
            "codegeeko.fixer.open_flag_issue",
            return_value={"ok": True, "html_url": "https://x/issues/1"},
        ),
    ):
        main()


def test_each_fix_branch_is_cut_from_main_not_from_the_previous_fix_branch(temp_repo, monkeypatch):
    _run_fix_mode(temp_repo, monkeypatch, [_finding(0), _finding(1)])

    first = "codegeeko/repowise-mod0-py-metric"
    second = "codegeeko/repowise-mod1-py-metric"
    stacked = subprocess.run(
        ["git", "merge-base", "--is-ancestor", first, second], cwd=temp_repo, capture_output=True
    )

    assert stacked.returncode != 0, (
        "the second finding's branch was cut from the first finding's branch -- its PR carries the "
        "first fix too"
    )


def test_each_fix_branch_contains_only_its_own_fix(temp_repo, monkeypatch):
    _run_fix_mode(temp_repo, monkeypatch, [_finding(0), _finding(1)])

    second = "codegeeko/repowise-mod1-py-metric"
    changed = _git(temp_repo, "diff", "--name-only", "main", second).split()

    assert changed == ["mod1.py"]


def test_fix_mode_leaves_head_back_on_main(temp_repo, monkeypatch):
    # If the run ends on a fix branch, the caller's save_state writes state.json there and the
    # workflow's `git push origin main` silently pushes nothing.
    _run_fix_mode(temp_repo, monkeypatch, [_finding(0), _finding(1)])

    assert _git(temp_repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_a_rejected_fix_attempts_edits_never_reach_main(temp_repo, monkeypatch):
    # A finding whose tests never pass is abandoned -- but every attempt was `git add -A`'d and
    # never committed, so the staged edits ride `git checkout main` across to main's index. The
    # workflow's next step (`git add .code-geeko/state.json` + commit + push) then sweeps that
    # rejected, test-FAILING LLM output onto main under a "chore: update code-geeko state"
    # message. The tree must be discarded, not carried.
    _run_fix_mode(temp_repo, monkeypatch, [_finding(0)], tests=False)

    # Tracked files only: the run also writes `.code-geeko/state.json`, which is untracked here
    # and which the workflow commits on purpose -- that one is supposed to be there.
    assert _git(temp_repo, "status", "--porcelain", "--untracked-files=no") == ""
    assert Path(temp_repo, "mod0.py").read_text(encoding="utf-8") == "original 0\n"


def test_a_rejected_finding_does_not_contaminate_the_next_findings_pr(temp_repo, monkeypatch):
    # Same staged-tree leak, seen from the next finding's branch: cutting it from a
    # contaminated main puts finding 0's rejected edits inside finding 1's PR.
    _run_fix_mode(
        temp_repo, monkeypatch, [_finding(0), _finding(1)], tests=[False, False, False, True]
    )

    changed = _git(temp_repo, "diff", "--name-only", "main", "codegeeko/repowise-mod1-py-metric")

    assert changed.split() == ["mod1.py"]


def test_a_failed_pr_call_cleans_up_the_branch_it_pushed(temp_repo, monkeypatch):
    _run_fix_mode(temp_repo, monkeypatch, [_finding(0)], pr={"ok": False, "error": "API timeout"})

    assert "codegeeko/repowise-mod0-py-metric" not in _git(temp_repo, "ls-remote", "--heads", "origin")


def test_a_finding_whose_pr_call_failed_can_still_be_fixed_on_the_next_run(temp_repo, monkeypatch, capsys):
    """The retry that fix #4 (never mark an unlanded finding seen) depends on must be idempotent.

    Night 1 pushes the branch, then the PR API call fails -> `pr_failed` -> run.py correctly leaves
    the finding unseen so it re-fires. If night 1's branch is left behind, night 2 cuts a fresh
    branch of the same name from main, the push is rejected as a non-fast-forward, and the finding
    fails identically every night forever -- job green, 3 real Claude fix attempts burned nightly,
    and a permanent slot held under MAX_FIXES_PER_NIGHT. Silent suppression traded for a silent
    infinite loop.
    """
    _run_fix_mode(temp_repo, monkeypatch, [_finding(0)], pr={"ok": False, "error": "API timeout"})
    capsys.readouterr()

    _run_fix_mode(temp_repo, monkeypatch, [_finding(0)])

    out = capsys.readouterr().out
    assert "-> pr: https://x/pull/1" in out
    assert "git_failed" not in out


def test_fix_mode_pushes_every_fix_branch_to_the_remote(temp_repo, monkeypatch):
    _run_fix_mode(temp_repo, monkeypatch, [_finding(0), _finding(1)])

    remote_branches = _git(temp_repo, "ls-remote", "--heads", "origin")

    assert "codegeeko/repowise-mod0-py-metric" in remote_branches
    assert "codegeeko/repowise-mod1-py-metric" in remote_branches
