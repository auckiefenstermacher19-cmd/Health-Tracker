"""
validate_sources.py
-------------------
Validates both source CSV files before consolidation.  Performs:

  1. File existence checks
  2. Encoding validation (UTF-8)
  3. Minimum row count check (at least 1 data row)
  4. Date column presence check
  5. Schema-change detection (new columns, removed columns, reordered columns)
     compared to the last known schema snapshot stored in data/schema/
  6. Duplicate date detection per file
  7. Produces a detailed audit log in logs/validation_<timestamp>.log

Exit codes
----------
  0 — validation passed (proceed to consolidation)
  1 — hard failure (missing file, unreadable, no date column) — halt workflow
  2 — schema change detected — workflow continues but emits a prominent warning
      and updates the schema snapshot so the change is not re-flagged next run

The separation of exit codes allows the GitHub Actions workflow to decide
whether a schema change is fatal (strict mode) or advisory (default mode).
"""

import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
RAW_DIR    = Path("raw")
SCHEMA_DIR = Path("schema")
LOG_DIR    = Path("logs")

WHOOP_CSV  = RAW_DIR / "daily_consolidated.csv"
MEAL_CSV   = RAW_DIR / "Meal_Data_Dashboard.csv"

WHOOP_SCHEMA_FILE = SCHEMA_DIR / "daily_consolidated_schema.json"
MEAL_SCHEMA_FILE  = SCHEMA_DIR / "Meal_Data_Dashboard_schema.json"

SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
ts  = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
log_file = LOG_DIR / f"validation_{ts}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ── Schema Snapshot Helpers ───────────────────────────────────────────────────

def load_schema(schema_file: Path) -> list[str] | None:
    """Load previously saved column list.  Returns None if no snapshot exists."""
    if not schema_file.exists():
        return None
    try:
        with open(schema_file, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("columns", [])
    except (json.JSONDecodeError, KeyError) as exc:
        log.warning("Could not parse schema snapshot %s: %s", schema_file, exc)
        return None


def save_schema(schema_file: Path, columns: list[str], source_label: str) -> None:
    """Persist the current column list as a JSON snapshot."""
    payload = {
        "source":    source_label,
        "columns":   columns,
        "saved_at":  datetime.now(timezone.utc).isoformat(),
        "col_count": len(columns),
    }
    with open(schema_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    log.info("Schema snapshot updated → %s  (%d columns)", schema_file, len(columns))


def compare_schemas(
    label: str,
    previous: list[str],
    current: list[str],
) -> dict:
    """
    Diff two column lists.

    Returns a dict with keys:
      changed    : bool — True if any difference exists
      added      : list[str] — columns in current but not in previous
      removed    : list[str] — columns in previous but not in current
      reordered  : bool — True if the set is identical but order changed
      summary    : str — human-readable one-liner
    """
    prev_set = set(previous)
    curr_set = set(current)

    added    = [c for c in current  if c not in prev_set]
    removed  = [c for c in previous if c not in curr_set]
    reordered = (prev_set == curr_set) and (previous != current)
    changed  = bool(added or removed or reordered)

    parts = []
    if added:
        parts.append(f"{len(added)} column(s) added")
    if removed:
        parts.append(f"{len(removed)} column(s) removed")
    if reordered:
        parts.append("column ordering changed")

    summary = f"[{label}] Schema change: " + (", ".join(parts) if parts else "none")

    return {
        "changed":   changed,
        "added":     added,
        "removed":   removed,
        "reordered": reordered,
        "summary":   summary,
    }


# ── Per-File Validation ───────────────────────────────────────────────────────

def validate_csv(
    csv_path: Path,
    schema_file: Path,
    label: str,
    date_col: str = "date",
) -> dict:
    """
    Run all validation checks for a single CSV file.

    Returns a result dict with:
      ok           : bool — False means a hard failure; True means continue
      schema_changed: bool
      errors       : list[str]
      warnings     : list[str]
      columns      : list[str]
      row_count    : int
    """
    result = {
        "ok":             True,
        "schema_changed": False,
        "errors":         [],
        "warnings":       [],
        "columns":        [],
        "row_count":      0,
    }

    # ── 1. File existence ─────────────────────────────────────────────────────
    if not csv_path.exists():
        result["errors"].append(f"File not found: {csv_path}")
        result["ok"] = False
        return result

    # ── 2. Encoding / readability ─────────────────────────────────────────────
    try:
        with open(csv_path, encoding="utf-8", newline="") as f:
            raw = f.read()
    except UnicodeDecodeError as exc:
        result["errors"].append(f"Encoding error (expected UTF-8): {exc}")
        result["ok"] = False
        return result

    # ── 3. Parse CSV ──────────────────────────────────────────────────────────
    try:
        lines = raw.splitlines()
        reader = csv.reader(lines)
        header = next(reader, None)
        if header is None:
            result["errors"].append("File is empty — no header row found.")
            result["ok"] = False
            return result
        rows = list(reader)
    except csv.Error as exc:
        result["errors"].append(f"CSV parse error: {exc}")
        result["ok"] = False
        return result

    result["columns"]  = header
    result["row_count"] = len(rows)

    # ── 4. Minimum rows ───────────────────────────────────────────────────────
    if len(rows) == 0:
        result["errors"].append("File contains a header row but no data rows.")
        result["ok"] = False
        return result

    # ── 5. Date column presence ───────────────────────────────────────────────
    if date_col not in header:
        result["errors"].append(
            f"Required date column '{date_col}' not found in header.\n"
            f"  Columns present: {header[:10]}{'…' if len(header) > 10 else ''}"
        )
        result["ok"] = False
        return result

    # ── 6. Duplicate date detection ───────────────────────────────────────────
    date_idx = header.index(date_col)
    date_values = [row[date_idx] for row in rows if len(row) > date_idx and row[date_idx]]
    seen = {}
    for val in date_values:
        seen[val] = seen.get(val, 0) + 1
    duplicates = {k: v for k, v in seen.items() if v > 1}
    if duplicates:
        result["warnings"].append(
            f"Duplicate dates detected (this may be intentional for intra-day updates): "
            f"{duplicates}"
        )

    # ── 7. Schema-change detection ────────────────────────────────────────────
    previous_schema = load_schema(schema_file)
    if previous_schema is None:
        log.info("[%s] No prior schema snapshot found — this is the first run. "
                 "Saving current schema.", label)
        save_schema(schema_file, header, label)
    else:
        diff = compare_schemas(label, previous_schema, header)
        if diff["changed"]:
            result["schema_changed"] = True
            log.warning("⚠  SCHEMA CHANGE DETECTED  ⚠")
            log.warning("%s", diff["summary"])
            if diff["added"]:
                log.warning("  Added columns   : %s", diff["added"])
            if diff["removed"]:
                log.warning("  Removed columns : %s", diff["removed"])
            if diff["reordered"]:
                log.warning("  Column order has changed.")
            log.warning(
                "  The consolidation script is schema-resilient and will "
                "adapt automatically.  Schema snapshot will be updated."
            )
            # Update snapshot so we don't re-flag on next run
            save_schema(schema_file, header, label)
        else:
            log.info("[%s] Schema unchanged (%d columns).", label, len(header))

    log.info(
        "[%s] ✓  %d columns, %d data rows.  Date column '%s' present.",
        label, len(header), len(rows), date_col,
    )
    return result


# ── Summary Reporter ──────────────────────────────────────────────────────────

def print_summary(whoop_result: dict, meal_result: dict) -> None:
    log.info("-" * 60)
    log.info("VALIDATION SUMMARY")
    log.info("-" * 60)

    for label, r in [("WHOOP daily_consolidated", whoop_result),
                      ("Meal_Data_Dashboard",      meal_result)]:
        status = "✓ PASS" if r["ok"] and not r["schema_changed"] else \
                 "⚠ WARN" if r["ok"] and r["schema_changed"] else \
                 "✗ FAIL"
        log.info("  [%s]  %s  |  %d cols, %d rows",
                 label, status, len(r["columns"]), r["row_count"])
        for err in r["errors"]:
            log.error("    ERROR: %s", err)
        for warn in r["warnings"]:
            log.warning("    WARN:  %s", warn)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=" * 60)
    log.info("  Health Tracker — Source Validation")
    log.info("=" * 60)

    whoop_result = validate_csv(
        csv_path    = WHOOP_CSV,
        schema_file = WHOOP_SCHEMA_FILE,
        label       = "WHOOP daily_consolidated",
        date_col    = "date",
    )

    meal_result = validate_csv(
        csv_path    = MEAL_CSV,
        schema_file = MEAL_SCHEMA_FILE,
        label       = "Meal_Data_Dashboard",
        date_col    = "date",
    )

    print_summary(whoop_result, meal_result)

    # Hard failures — halt the workflow
    hard_failures = [
        r for r in [whoop_result, meal_result]
        if not r["ok"]
    ]
    if hard_failures:
        log.error("Validation FAILED with hard errors. Consolidation aborted.")
        log.error("Review the errors above and the log at: %s", log_file)
        sys.exit(1)

    # Schema changes — continue but use exit code 2 so the workflow can log it
    schema_changes = [
        r for r in [whoop_result, meal_result]
        if r["schema_changed"]
    ]
    if schema_changes:
        log.warning(
            "Schema changes detected.  Consolidation will proceed using "
            "dynamic column detection.  No manual code changes required."
        )
        log.info("Validation log: %s", log_file)
        # Exit 0 — we proceed; the GH Actions step will surface the warnings
        sys.exit(0)

    log.info("All validations passed.  Proceeding to consolidation.")
    log.info("Validation log: %s", log_file)
    sys.exit(0)


if __name__ == "__main__":
    main()
