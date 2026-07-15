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
    """
    findings = []
    for result in raw.get("results", []):
        extra = result.get("extra", {}) or {}
        severity = extra.get("severity", "WARNING")
        check_id = result.get("check_id", "unknown-rule")
        path = result.get("path", "unknown")
        start = result.get("start", {}) or {}
        start_line = start.get("line", "?")
        findings.append({
            "source": "semgrep",
            "file": path,
            "finding_id": f"{check_id}:{start_line}",
            "risk_score": _SEVERITY_TO_RISK.get(severity, _DEFAULT_RISK),
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
    except (AttributeError, TypeError, KeyError):
        return [], False
    return findings, True
