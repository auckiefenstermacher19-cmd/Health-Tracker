import hashlib
import json
import subprocess

# Semgrep's categorical severity -> Code-Geeko's 0-10 risk_score scale.
_SEVERITY_TO_RISK = {
    "ERROR": 9.0,
    "WARNING": 6.0,
    "INFO": 3.0,
}
_DEFAULT_RISK = 5.0  # unrecognized/future severity values fall back here


def parse_semgrep_output(raw: dict) -> list[dict]:
    """Normalize a `semgrep scan --json` payload into Code-Geeko findings.

    The real fixture (tests/codegeeko/fixtures/semgrep_sample_output.json, captured in
    Task 3) confirms `results[]` entries have the publicly-documented long-stable shape:
    `check_id`, `path`, `start.line`, `end.line`, `extra.message`, `extra.severity`. Two
    fields on every result -- `extra.fingerprint` and `extra.lines` -- literally contain the
    string "requires login" in this anonymous-OSS-engine capture (real Semgrep redaction
    behavior, not a data-quality bug); they are opaque here and never read. The top-level
    `errors` array (Semgrep's own PartialParsing warnings about specific files) is separate
    from `results` and is intentionally not surfaced as findings -- out of scope per the plan.

    `finding_id = f"{check_id}:{start_line}"`, per the plan. `finding_id` only needs to be
    unique WITHIN a given `file` (state/triage/PR tasks key dedup by
    f"{source}:{file}:{finding_id}", per repowise_collector.py's documented convention).
    Verified against the real fixture: the same rule fires twice per file at two distinct
    lines, and that same two-line pattern is duplicated across `.github/workflows/` and
    `workflows/` (a real repo quirk -- four distinct files carrying identical content) --
    so `(check_id, start_line)` collides ACROSS different files but never within a single
    file, which is exactly what the contract requires. No representative-selection/collision
    handling (like Task 2 needed for repowise) was needed here because no such within-file
    collision exists in the real data. This function itself never dedupes -- it always emits
    one finding per `results` entry -- so if a future run ever produced two same-file results
    sharing both `check_id` and `start_line`, both would still appear here with the same
    finding_id; only a downstream consumer keyed on (source, file, finding_id) (e.g. Task 6's
    state store) would silently collapse them. That risk didn't warrant added complexity given
    it's unverified in real output, but is called out here for anyone revisiting this.

    Field access is defensive (`.get()` with fallbacks), not hard dict indexing, even though
    every field is present in the real fixture: a single malformed `results[]` entry (e.g. a
    future semgrep version, a corrupted stdout capture, or a mocked/adversarial payload)
    should degrade that one entry gracefully rather than raising and taking down the whole
    batch -- consistent with every other failure path in `run_semgrep` (timeout, missing
    binary, bad returncode, bad JSON) already returning `([], False)` instead of propagating
    an exception. `check_id` falls back to `"unknown-rule"`, `path` falls back to `"unknown"`,
    and `start.line` falls back to `"?"` (restoring the brief's own starter-code precedent for
    that field). A `results[]` entry that isn't a dict at all (e.g. `None` or a bare string)
    is beyond field-level fallbacks -- `run_semgrep` catches that case separately (see below).

    A fallback fires whenever a field is genuinely unusable, and "unusable" is checked with
    `isinstance`, not `.get(key, default)` or plain truthiness -- `.get(key, default)` only
    substitutes on a MISSING key, and plain truthiness/`is not None` checks still let a
    present-but-WRONG-TYPE value (e.g. `"path": 123` or `"path": ["a", "b"]`) through unchanged.
    `isinstance` catches all three shapes of malformed field in one check: absent (`.get()`
    defaults to `None`, fails `isinstance`), explicit `None` (fails `isinstance`), and wrong
    type (fails `isinstance`). This was tightened over two prior review rounds that each closed
    one shape while leaving a structurally identical sibling open (missing-key, then explicit-
    None, then wrong-type) -- `isinstance` closes all three at once instead of adding another
    single-shape special case:
      - `extra`: must be a `dict`, else treated as `{}` (matches the guard `start` already had).
      - `path`: must be a non-empty `str`, else treated as missing (falls back to `"unknown"`
        AND counts toward `used_fallback`, so a wrong-typed path gets the same SHA-1
        disambiguation as a genuinely missing one -- a type-invalid value must never be
        silently treated as a legitimate path).
      - `start`: must be a `dict`, else treated as `{}`.
      - `start.line`: checked with `is not None` (not `isinstance(int)`) -- `0` is a technically
        valid line number, and unlike `path`/`file` there's no `str`-typed contract on the raw
        `start.line` value itself (it's only ever embedded via f-string into `finding_id`, which
        coerces any type to `str` safely, so a wrong-typed line number can't corrupt the output
        contract the way a wrong-typed `path` could corrupt `file`).
      - `check_id`: intentionally NOT type-checked, only falsy-checked (`or "unknown-rule"`).
        Unlike `path` (which flows straight into `finding["file"]`, contractually `str`),
        `check_id` only ever reaches output via an f-string (`finding_id`, `message`), which
        coerces any type to `str` automatically -- there's no way for a wrong-typed `check_id`
        to violate the normalized contract, so tightening it further would add complexity
        without closing any real gap.
      - `severity`: must be a `str` to be looked up in `_SEVERITY_TO_RISK` -- an unhashable
        value (e.g. `"severity": ["WARNING"]`) would otherwise raise `TypeError` straight out of
        a `dict.get()` call, uncaught inside this function. Any non-`str` severity (including
        `None` from an explicit `"severity": null`) falls back directly to `_DEFAULT_RISK`
        without touching the lookup table.
      - `message`, `risk_score`, `raw`: audited and found not to need a fix. `message` is always
        built via f-string (`f"{check_id}: {extra.get('message', '')}"`), which coerces any
        type of `extra["message"]` safely, and its `f"{check_id}: "` prefix guarantees the
        result is always non-empty even if `extra["message"]` is missing/empty. `risk_score` is
        always one of the `_SEVERITY_TO_RISK` float values or `_DEFAULT_RISK` (never derived
        from unvalidated input). `raw` is the original `result` dict itself -- no type
        constraint beyond "the dict this finding came from", which it always is by construction.

    When any of `check_id`/`path`/`start.line` falls back (including a wrong-typed `path`),
    `finding_id` additionally gets a short content-hash suffix (of the entry's own remaining
    fields, order-independent). Without this, two DIFFERENT malformed entries in the same batch
    -- e.g. one WARNING and one ERROR, both missing check_id/path/start -- would otherwise
    collapse onto the identical placeholder triple `("unknown", "unknown-rule:?")`, a real
    finding_id collision within a single file that would silently drop one of them under the
    f"{source}:{file}:{finding_id}" dedup convention. The hash is derived from content, not list
    position, matching the codebase's established convention (see repowise_collector.py) of
    never keying disambiguation on unstable list order. This does NOT fully solve the degenerate
    case of two BYTE-IDENTICAL malformed entries (same missing fields, same severity, same
    message) -- those still hash identically and collapse into one finding, by the same
    deliberate design repowise_collector uses for genuinely indistinguishable duplicates: there
    is no content-based way to tell them apart, so collapsing (rather than arbitrarily numbering
    by position) is the documented, intentional choice, not an oversight. A malformed-but-valid-
    type `extra` (e.g. `"extra": "junk"`, reset to `{}`) does NOT by itself trigger the SHA-1
    suffix -- it doesn't touch `check_id`/`path`/`start.line`, so it can't reproduce the specific
    placeholder-collision this suffix defends against; it can only ever fall back to the same
    default severity (`"WARNING"`) two DIFFERENTLY-malformed `extra` entries would already share
    with any other well-formed WARNING finding, which is the pre-existing, accepted,
    non-`finding_id`-affecting behavior of a missing/absent `extra.severity`.

    Beyond field-level fallbacks: a `results[]` entry that isn't a dict at all (e.g. `None` or a
    bare string) still can't be rescued here -- `result.get(...)` itself raises on a non-dict
    `result` before any of the above logic runs. That residual is caught one layer up, in
    `run_semgrep`, which -- for that specific case only -- drops the whole batch rather than
    just the one entry (see `run_semgrep`'s docstring). This is an intentional, previously
    reviewed and accepted boundary: it would take restructuring `parse_semgrep_output` around a
    per-entry try/except (skipping just the unusable entry) to make even a non-dict `result`
    degrade per-entry instead of failing the whole batch, and that was judged disproportionate
    complexity for a shape of corruption (a `results[]` array containing a bare `None`/string
    instead of an object) that would mean semgrep's own JSON output format changed in a way with
    no other precedent.
    """
    findings = []
    for result in raw.get("results", []):
        extra = result.get("extra")
        extra = extra if isinstance(extra, dict) else {}
        severity = extra.get("severity", "WARNING")
        risk_score = (
            _SEVERITY_TO_RISK.get(severity, _DEFAULT_RISK)
            if isinstance(severity, str)
            else _DEFAULT_RISK
        )

        raw_check_id = result.get("check_id")
        raw_path = result.get("path")
        start = result.get("start")
        start = start if isinstance(start, dict) else {}
        raw_start_line = start.get("line")

        check_id = raw_check_id or "unknown-rule"
        path_valid = isinstance(raw_path, str) and raw_path
        path = raw_path if path_valid else "unknown"
        start_line = raw_start_line if raw_start_line is not None else "?"

        finding_id = f"{check_id}:{start_line}"
        used_fallback = not raw_check_id or not path_valid or raw_start_line is None
        if used_fallback:
            # Disambiguate the shared placeholder finding_id across malformed entries in the
            # same batch. Content-derived (not position-derived): two malformed entries with
            # different remaining content (e.g. different severity) get different suffixes.
            digest = hashlib.sha1(
                json.dumps(result, sort_keys=True, default=str).encode()
            ).hexdigest()[:8]
            finding_id = f"{finding_id}:{digest}"

        findings.append({
            "source": "semgrep",
            "file": path,
            "finding_id": finding_id,
            "risk_score": risk_score,
            "message": f"{check_id}: {extra.get('message', '')}",
            "raw": result,
        })
    return findings


def run_semgrep(repo_path: str) -> tuple[list[dict], bool]:
    """Run `semgrep scan --config auto --json` against repo_path and return normalized findings.

    returncode 0 (clean) and 1 (findings present) are both valid runs; anything else (config
    error, crash, etc.) is treated as a failed run, same as a timeout or missing binary.

    `parse_semgrep_output` itself is defensive against malformed *fields* on a results entry
    (see its docstring), but a results entry that isn't a dict at all (e.g. `None` or a bare
    string in `results[]`) would still raise `AttributeError`/`TypeError` out of its `.get()`
    calls. That's caught here so no single malformed entry -- however broken -- can make
    `run_semgrep` raise; it degrades to the same `([], False)` contract as every other failure
    path (timeout, missing binary, bad returncode, bad JSON) instead.
    """
    try:
        result = subprocess.run(
            ["semgrep", "scan", "--config", "auto", "--json"],
            capture_output=True, timeout=300, cwd=repo_path, text=True,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return [], False

    if result.returncode not in (0, 1):
        return [], False

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], False

    try:
        findings = parse_semgrep_output(raw)
    # parse_semgrep_output no longer does hard dict indexing (it's all .get()-based now), so
    # KeyError shouldn't actually fire here -- kept as a defensive no-op in case that changes.
    except (AttributeError, TypeError, KeyError):
        return [], False
    return findings, True
