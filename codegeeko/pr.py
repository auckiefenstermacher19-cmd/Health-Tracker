import hashlib
import re

import requests

_INVALID_CHARS = re.compile(r"[^a-z0-9]+")


def _slugify(value, fallback_prefix: str) -> str:
    """Slugify `value` into a lowercase, git-ref-safe, non-empty token.

    `value` may legitimately be `None` -- ci_log_collector's findings always have `file=None`
    (repo-level findings have no source file; see codegeeko/collectors/ci_log_collector.py),
    and a bare `finding["file"].lower()` would raise AttributeError on that input. `str(value)`
    also may slugify down to `""` for a pathological-but-real value (e.g. a `file` that is only
    punctuation/whitespace, or a `finding_id` with no alphanumeric characters).

    Both cases fall back to `f"{fallback_prefix}-{sha1(text)[:8]}"` rather than emitting an
    empty token. This matters for two reasons: (1) an empty slug joined into the branch name
    would leave a doubled/trailing "-", and (2) two DIFFERENT raw values that both happen to
    slugify to "" would otherwise collapse into the SAME empty token and collide -- exactly the
    class of bug `branch_name_for` exists to prevent (per the finding_id plan amendment). Hashing
    the actual (pre-slug) text keeps distinct raw inputs distinct even in this fallback path.
    """
    text = "" if value is None else str(value)
    slug = _INVALID_CHARS.sub("-", text.lower()).strip("-")
    if slug:
        return slug
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"{fallback_prefix}-{digest}"


def branch_name_for(finding: dict) -> str:
    """Build a unique, slug-safe git branch name for `finding`.

    MUST incorporate `finding["finding_id"]`, not just `finding["file"]` -- two different
    findings commonly share one file (e.g. repowise's file-level "metric" finding and a
    function-level "someFn:complex_method" finding both on the same file; Task 6's dedup key is
    `f"{source}:{file}:{finding_id}"` for the same reason). A branch name built from `file` alone
    would collide across such findings, and the second finding's `git push` would silently
    overwrite the first fix branch's history (plan amendment following Task 2's review, which
    found repowise commonly emits multiple findings per file).
    """
    file_slug = _slugify(finding["file"], "nofile")
    id_slug = _slugify(finding["finding_id"], "noid")
    return f"codegeeko/{finding['source']}-{file_slug}-{id_slug}"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _post_github(url: str, token: str, payload: dict) -> dict:
    """POST `payload` to the GitHub REST API and normalize the outcome into a `dict`.

    Degrades gracefully instead of raising, mirroring the contract every other external-I/O call
    in this codebase already uses (codegeeko/collectors/ci_log_collector.py:run_ci_log_check --
    network error / timeout / non-2xx status / undecodable JSON body all collapse to one failure
    outcome rather than propagating). The brief's starter code called bare
    `response.raise_for_status()` with nothing catching the resulting exception; that is NOT
    sufficient here, because Task 11 (not yet built) is designed to call `open_fix_pr` /
    `open_flag_issue` as one step of a 3-attempt fix pipeline. If PR/Issue creation raised on a
    transient GitHub failure (rate limit, network blip, timeout), an uncaught `requests`
    exception would crash the entire nightly run over what should be a single retryable,
    per-finding failure -- exactly the failure mode the sibling collectors were already hardened
    against.

    The public functions' documented return type is `dict` (not the `(result, ok)` tuple the
    collectors use), so the sentinel is a dict too: `{"ok": False, "error": <str>}` on any
    failure. This is reliably distinguishable from a genuine GitHub PR/Issue response, which
    always carries `html_url`/`number`/`id` and never an `ok` key of its own. A success response
    gets `"ok": True` merged in, so a caller (Task 11) can branch uniformly on `result["ok"]`
    instead of having to infer success from key presence.
    """
    try:
        response = requests.post(url, headers=_headers(token), json=payload, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}

    try:
        body = response.json()
    except ValueError as exc:
        return {"ok": False, "error": f"invalid JSON response: {exc}"}

    if not isinstance(body, dict):
        return {"ok": False, "error": f"unexpected response shape: {type(body).__name__}"}

    body["ok"] = True
    return body


def open_fix_pr(owner: str, repo: str, token: str, branch: str, title: str, body: str, base: str = "main") -> dict:
    return _post_github(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        token,
        {"title": title, "head": branch, "base": base, "body": body},
    )


def open_flag_issue(owner: str, repo: str, token: str, title: str, body: str) -> dict:
    return _post_github(
        f"https://api.github.com/repos/{owner}/{repo}/issues",
        token,
        {"title": title, "body": body},
    )
