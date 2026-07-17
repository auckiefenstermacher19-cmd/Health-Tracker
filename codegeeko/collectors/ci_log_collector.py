import sys
import time

import requests

# Every failed run gets the same fixed risk_score -- unlike semgrep/repowise, GitHub's Actions
# run schema carries no categorical severity to bucket on. A failed CI run is a failed CI run.
_FAILURE_RISK = 8.0

MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 1.0


def _report_failure(message: str) -> None:
    """Emit a terminal-failure diagnostic for the operator.

    STDERR specifically: only stdout is teed into the report / $GITHUB_STEP_SUMMARY, so writing
    here reaches the Actions job log without polluting the nightly report.

    This exists because the 2026-07-16 outage was expensive to diagnose for exactly one reason --
    the collector failed silently. The report footer could say "ci_log failed" but never why, so
    root-causing a one-line HTTP 503 cost a temporary-instrumentation commit and a full nightly
    cycle. One line here makes the next incident readable straight from the job log.
    """
    print(f"[ci_log] {message}", file=sys.stderr, flush=True)


def parse_workflow_runs(raw: dict) -> list[dict]:
    """Normalize a `GET /repos/{owner}/{repo}/actions/runs` payload into Code-Geeko findings.

    This collector's findings are repo-level, not file-level -- `file` is always `None` by
    contract (there's no source file a CI run maps to), so unlike repowise/semgrep there's no
    file-type-validity concern here. The concern that DOES carry over from Tasks 2/4's review
    history is `finding_id`: the plan's prescribed `finding_id = str(run["id"])` needs a
    genuine run id behind it. `str()` never raises regardless of input type, so the risk isn't
    a crash -- it's that a missing/explicit-None `id` would silently produce `finding_id =
    "None"`, a string that LOOKS like a valid finding_id but doesn't identify any real run. A
    run without a genuine id can't be given a truthful finding_id at all (unlike a semgrep
    result missing `check_id`, there's no useful placeholder to substitute -- "unknown run" is
    not an identity), so such an entry is skipped entirely rather than faked.

    Each failed run is tracked as its own finding (per the plan: "each failed run is tracked
    as its own event, not merged into one repo-level slot"), so no grouping/dedup step is
    needed here the way repowise/semgrep needed for same-file collisions -- `run["id"]` is
    GitHub's own primary key for a run and is unique by construction whenever it's genuinely
    present.

    Defensive handling, checked with `isinstance` (not just falsy/None) where it matters,
    consistent with the Task 2/4 review history of a falsy-only check letting a wrong-typed
    value through unchanged:
      - `raw` itself: must be a `dict`, else there's nothing to read -- returns `[]`.
      - `raw["workflow_runs"]`: must be a `list`, else treated as empty. GitHub's documented
        schema always makes this a list, but a corrupted/mocked payload could hand it anything.
      - each `workflow_runs` entry: must be a `dict`, else skipped -- a non-dict entry (e.g.
        `None` or a bare string) can't be read at all, and one malformed entry must not crash
        the whole batch (`.get()` on a non-dict raises `AttributeError`).
      - `conclusion`: read via `.get()` and compared with `==` -- a `!=` comparison against the
        literal string `"failure"` can't raise regardless of the actual value's type (including
        `None` or a non-str), so no extra type guard is needed here.
      - `id`: must be present AND of a type that can genuinely represent a run identity --
        `isinstance(run_id, (int, str))`, explicitly excluding `bool` (a `bool` is an `int`
        subclass in Python, but `True`/`False` are never real GitHub run ids). A `None`-only
        check isn't enough: `str()` never raises regardless of input type, so a wrong-typed
        `id` (e.g. `run["id"] = [111, 112]`) would silently produce `finding_id = "[111,
        112]"` -- syntactically a valid non-empty `str` (passes the shape contract) but not a
        genuine run identity. This is the same class of gap `semgrep_collector.py` closed for
        its `path` field (`isinstance(raw_path, str) and raw_path`); applied here for `id`.
        Entries failing this check are skipped, not given a placeholder id, since a fabricated
        id would misrepresent which real CI run failed.
      - `name` / `created_at` / `html_url`: intentionally NOT type-checked beyond `.get()`
        defaults. Unlike `id` (which becomes the load-bearing `finding_id`), these three only
        ever flow into `message` via an f-string, which coerces any type to `str` safely and
        can't violate the normalized contract -- tightening them further would add complexity
        without closing a real gap (matching semgrep_collector.py's documented reasoning for
        `check_id`).
    """
    if not isinstance(raw, dict):
        return []

    runs = raw.get("workflow_runs", [])
    if not isinstance(runs, list):
        return []

    findings = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("conclusion") != "failure":
            continue

        run_id = run.get("id")
        if not isinstance(run_id, (int, str)) or isinstance(run_id, bool):
            continue

        name = run.get("name") or "unknown workflow"
        created_at = run.get("created_at") or "an unknown time"
        html_url = run.get("html_url") or "no URL available"

        findings.append({
            "source": "ci_log",
            "file": None,
            "finding_id": str(run_id),
            "risk_score": _FAILURE_RISK,
            "message": f"Workflow '{name}' failed on {created_at} ({html_url})",
            "raw": run,
        })
    return findings


def run_ci_log_check(owner: str, repo: str, token: str) -> tuple[list[dict], bool]:
    """Fetch recent GitHub Actions runs for owner/repo and return normalized findings.

    Every failure path (network error, non-2xx status, malformed/undecodable JSON body) returns
    `([], False)` -- matching `run_repowise`/`run_semgrep`'s established contract that "couldn't
    parse the response" is a FAILED check, not a clean one. A 200 response whose body isn't
    valid JSON at all (e.g. a proxy error page served with a 200 status) can't be distinguished
    from "GitHub is broken right now" -- reporting that as `ok=True, findings=[]` would silently
    read downstream as "checked, all CI runs green" instead of "couldn't tell", corrupting any
    state tracking that keys off `ok`. Note this is distinct from a response that DOES decode as
    JSON but doesn't match the documented `{"workflow_runs": [...]}` shape (e.g. `{}` or a bare
    list) -- that case reaches `parse_workflow_runs`, which already degrades it to `[]` without
    raising, and is still reported as `ok=True` since the request+response cycle itself was
    valid, just empty of the expected structure.

    Transient server errors (5xx) and connection-level failures are retried up to `MAX_ATTEMPTS`
    with exponential backoff, because a single blip would otherwise cost a whole night of CI
    signal -- this collector runs once per night, so there is no next attempt until tomorrow.
    Client errors (4xx) are NOT retried: a 401/403/404 is a real misconfiguration, not a blip,
    and retrying only delays the signal while masking the cause.

    Scope note (2026-07-16 outage): GitHub served HTTP 503 "Unicorn" HTML from this endpoint for
    ~77 minutes, failing six consecutive dispatches. A bounded retry does NOT rescue an outage of
    that length, and is not intended to -- after the budget is spent the collector still degrades
    to `([], False)`, the run stays green, and the next night recovers (which is exactly what
    happened, unaided, on 2026-07-17). The retry exists for the SHORT blip, which is the common
    5xx case and the one a once-nightly job is most vulnerable to.

    No jitter: jitter de-synchronizes a herd of competing clients, and this is one nightly job
    issuing one request. It would add nondeterminism without preventing any contention.
    """
    for attempt in range(MAX_ATTEMPTS):
        is_final_attempt = attempt == MAX_ATTEMPTS - 1

        try:
            response = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/actions/runs",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                params={"per_page": 20},
                timeout=30,
            )
        except requests.RequestException as e:
            # Connection-level failure (DNS, timeout, reset) -- no response to inspect, and
            # retryable by nature.
            if is_final_attempt:
                _report_failure(
                    f"giving up after {MAX_ATTEMPTS} attempts: {type(e).__name__}: {e}"
                )
                return [], False
            time.sleep(_BACKOFF_BASE_SECONDS * (2 ** attempt))
            continue

        # `isinstance(status, int)` is load-bearing, not defensive noise: a status of any other
        # type can't be judged retryable, and comparing a non-int against 500/600 would raise
        # TypeError -- turning an unknown status into a crash instead of a graceful `ok=False`.
        # Anything not provably 5xx falls through to raise_for_status below, which classifies it.
        status = response.status_code
        if isinstance(status, int) and 500 <= status < 600 and not is_final_attempt:
            time.sleep(_BACKOFF_BASE_SECONDS * (2 ** attempt))
            continue

        try:
            response.raise_for_status()
        except requests.RequestException as e:
            # Covers both a non-retryable 4xx (first attempt) and a 5xx that outlived the retry
            # budget (final attempt) -- the attempt count distinguishes them in the log.
            _report_failure(f"HTTP {status} after {attempt + 1} attempt(s): {e}")
            return [], False

        try:
            body = response.json()
        except ValueError as e:
            _report_failure(f"response body was not valid JSON: {e}")
            return [], False

        return parse_workflow_runs(body), True

    # Unreachable: every path inside the loop either returns or continues, and the final attempt
    # never continues. Present so the function has a total contract regardless of MAX_ATTEMPTS.
    return [], False
