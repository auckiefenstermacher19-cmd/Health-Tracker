"""
consolidate.py
--------------
Core Health Tracker consolidation engine.

Merges daily_consolidated.csv (WHOOP) and Meal_Data_Dashboard.csv (nutrition)
into a single master CSV:  data/Health_Tracker_Master.csv

Layout (always):
  [All daily_consolidated columns — in their original order]
  [1 blank spacer column]
  [All Meal_Data_Dashboard columns — in their original order]

Design principles
-----------------
  • Zero hardcoded column names or positions.
  • Schema is read dynamically from the source files every run.
  • Joining is done on the 'date' column (YYYY-MM-DD), left-join from WHOOP.
  • If a WHOOP date has no matching meal data → meal columns are blank.
  • If a meal date has no matching WHOOP date → row is still included
    (right-side rows), ensuring no meal data is ever silently dropped.
  • Existing output file is NEVER overwritten in-place — a staging file is
    written first, validated, then atomically renamed to the final path.
  • An audit log entry is appended to logs/consolidation_audit.jsonl after
    every successful run.

Exit codes
----------
  0 — success
  1 — failure (missing inputs, write error, post-write validation failed)
"""

import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
RAW_DIR        = Path("raw")
OUTPUT_DIR     = Path(".")
LOG_DIR        = Path("logs")

WHOOP_CSV      = RAW_DIR / "daily_consolidated.csv"
MEAL_CSV       = RAW_DIR / "Meal_Data_Dashboard.csv"
OUTPUT_PATH    = OUTPUT_DIR / "Health_Tracker_Master.csv"
STAGING_PATH   = OUTPUT_DIR / "Health_Tracker_Master.staging.csv"
AUDIT_LOG      = LOG_DIR / "consolidation_audit.jsonl"

LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SPACER_SENTINEL = "__SPACER__"   # Internal name for the blank spacer column


# ═══════════════════════════════════════════════════════════════════════════════
# CSV Loading
# ═══════════════════════════════════════════════════════════════════════════════

def load_csv_raw(path: Path) -> tuple[list[str], list[list[str]]]:
    """
    Load a CSV file, returning (header, rows) where rows are plain lists.

    Using raw lists (not DictReader) preserves blank column headers
    (the internal section spacers used by both source files) and their
    exact positions.
    """
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows   = list(reader)
    log.info("Loaded %-40s  %3d columns  %4d rows", str(path), len(header), len(rows))
    return header, rows


def rows_to_date_dict(
    header: list[str],
    rows:   list[list[str]],
    date_col: str = "date",
) -> dict[str, list[str]]:
    """
    Index rows by their date value.

    If a date appears more than once (shouldn't happen in these CSVs but
    possible during incremental edge cases), the LAST row wins — matching
    the upstream behaviour in both source repos.

    Returns: { "YYYY-MM-DD": [cell, cell, ...] }
    """
    try:
        date_idx = header.index(date_col)
    except ValueError:
        raise ValueError(
            f"Date column '{date_col}' not found in header.\n"
            f"  Available columns: {header[:15]}…"
        )

    by_date: dict[str, list[str]] = {}
    for row in rows:
        # Pad short rows to avoid IndexError
        if len(row) <= date_idx:
            continue
        date_val = row[date_idx].strip()
        if not date_val:
            continue
        # Pad or trim row to match header length
        padded = (row + [""] * len(header))[: len(header)]
        by_date[date_val] = padded

    return by_date


# ═══════════════════════════════════════════════════════════════════════════════
# Header Construction
# ═══════════════════════════════════════════════════════════════════════════════

def build_output_header(
    whoop_header: list[str],
    meal_header:  list[str],
) -> list[str]:
    """
    Construct the output CSV header:
      [whoop columns] + [spacer column ""] + [meal columns]

    The spacer column is stored internally as SPACER_SENTINEL so we can
    write "" to the CSV header without confusing it with genuinely blank
    section-spacers that exist inside each source file.
    """
    # Rename the meal block's own `date` column to `meal_date` so the output has
    # exactly ONE column named `date` (column 0). Two columns named `date` collide
    # when the dashboard parses with PapaParse header:true (ambiguous which wins).
    meal_header_out = ["meal_date" if col == "date" else col for col in meal_header]
    return whoop_header + [SPACER_SENTINEL] + meal_header_out


def header_for_output(header: list[str]) -> list[str]:
    """Replace SPACER_SENTINEL with "" for actual CSV output."""
    return ["" if col == SPACER_SENTINEL else col for col in header]


# ═══════════════════════════════════════════════════════════════════════════════
# Row Construction
# ═══════════════════════════════════════════════════════════════════════════════

def build_output_row(
    date:          str,
    whoop_header:  list[str],
    whoop_by_date: dict[str, list[str]],
    meal_header:   list[str],
    meal_by_date:  dict[str, list[str]],
) -> list[str]:
    """
    Build a single output row for a given date.

    WHOOP side: use the matching row or blank list.
    Meal side:  use the matching row or blank list.
    Spacer:     always a single blank cell.
    """
    whoop_row = whoop_by_date.get(date, [""] * len(whoop_header))
    meal_row  = meal_by_date.get(date, [""] * len(meal_header))

    # Safety: ensure lengths match their respective headers
    whoop_row = (whoop_row + [""] * len(whoop_header))[: len(whoop_header)]
    meal_row  = (meal_row  + [""] * len(meal_header))[:  len(meal_header)]

    # Column 0 (the unified `date`) must carry this row's date for EVERY day,
    # including meal-only days that have no WHOOP row. Otherwise the dashboard,
    # which keys off column 0, filters those days out and recent food never shows.
    whoop_row[whoop_header.index("date")] = date

    return whoop_row + [""] + meal_row   # spacer = ""


# ═══════════════════════════════════════════════════════════════════════════════
# Post-Write Validation
# ═══════════════════════════════════════════════════════════════════════════════

def validate_output(
    path:           Path,
    expected_cols:  int,
    expected_rows:  int,
    whoop_dates:    set[str],
    meal_dates:     set[str],
    whoop_col_count:int,
) -> bool:
    """
    Read the written output file and confirm it meets expectations.

    Checks:
      - File exists and is non-empty
      - Column count matches expectation
      - Row count == union of all WHOOP + meal dates
      - Every WHOOP date is present
      - Every meal date is present
    """
    if not path.exists() or path.stat().st_size == 0:
        log.error("Post-write validation: output file missing or empty.")
        return False

    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        rows   = list(reader)

    if len(header) != expected_cols:
        log.error(
            "Post-write validation: column count mismatch. "
            "Expected %d, got %d.",
            expected_cols, len(header),
        )
        return False

    if len(rows) != expected_rows:
        log.error(
            "Post-write validation: row count mismatch. "
            "Expected %d, got %d.",
            expected_rows, len(rows),
        )
        return False

    # Check all source dates are present.
    # The date can live in TWO places per row:
    #   - column 0                              → the WHOOP date (blank if this date is meal-only)
    #   - column (whoop_col_count + 1)           → the meal date  (blank if this date is WHOOP-only)
    #     (whoop_col_count WHOOP columns, then exactly 1 spacer column, then meal columns start)
    # A date only fails validation if it's missing from BOTH columns across all rows.
    whoop_date_idx = 0
    meal_date_idx  = whoop_col_count + 1

    output_dates = set()
    for row in rows:
        if not row:
            continue
        if len(row) > whoop_date_idx and row[whoop_date_idx]:
            output_dates.add(row[whoop_date_idx])
        if len(row) > meal_date_idx and row[meal_date_idx]:
            output_dates.add(row[meal_date_idx])

    missing_whoop = whoop_dates - output_dates
    missing_meal  = meal_dates  - output_dates
    if missing_whoop:
        log.error("Post-write validation: WHOOP dates missing from output: %s",
                  sorted(missing_whoop)[:10])
        return False
    if missing_meal:
        log.error("Post-write validation: Meal dates missing from output: %s",
                  sorted(missing_meal)[:10])
        return False

    log.info(
        "Post-write validation ✓  %d columns, %d rows, all source dates present.",
        len(header), len(rows),
    )
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Audit Logging
# ═══════════════════════════════════════════════════════════════════════════════

def append_audit_log(record: dict) -> None:
    """Append a JSON audit record to the rolling audit log (JSONL format)."""
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def build_consolidated() -> None:
    run_start = datetime.now(timezone.utc)
    log.info("=" * 60)
    log.info("  Health Tracker — Consolidation Engine")
    log.info("  Run started: %s", run_start.isoformat())
    log.info("=" * 60)

    # ── 1. Load source files ──────────────────────────────────────────────────
    if not WHOOP_CSV.exists():
        log.error("WHOOP source file not found: %s", WHOOP_CSV)
        log.error("Run fetch_sources.py first.")
        sys.exit(1)

    if not MEAL_CSV.exists():
        log.error("Meal source file not found: %s", MEAL_CSV)
        log.error("Run fetch_sources.py first.")
        sys.exit(1)

    whoop_header, whoop_rows = load_csv_raw(WHOOP_CSV)
    meal_header,  meal_rows  = load_csv_raw(MEAL_CSV)

    # ── 2. Index rows by date ─────────────────────────────────────────────────
    whoop_by_date = rows_to_date_dict(whoop_header, whoop_rows, date_col="date")
    meal_by_date  = rows_to_date_dict(meal_header,  meal_rows,  date_col="date")

    whoop_dates = set(whoop_by_date.keys())
    meal_dates  = set(meal_by_date.keys())

    all_dates = sorted(whoop_dates | meal_dates, reverse=True)  # newest first

    log.info("")
    log.info("Date coverage:")
    log.info("  WHOOP dates   : %d  (%s → %s)",
             len(whoop_dates),
             min(whoop_dates) if whoop_dates else "N/A",
             max(whoop_dates) if whoop_dates else "N/A")
    log.info("  Meal dates    : %d  (%s → %s)",
             len(meal_dates),
             min(meal_dates) if meal_dates else "N/A",
             max(meal_dates) if meal_dates else "N/A")
    log.info("  Overlap       : %d dates", len(whoop_dates & meal_dates))
    log.info("  WHOOP-only    : %d dates", len(whoop_dates - meal_dates))
    log.info("  Meal-only     : %d dates", len(meal_dates - whoop_dates))
    log.info("  Union (output): %d dates", len(all_dates))

    # ── 3. Build output header ────────────────────────────────────────────────
    output_header_internal = build_output_header(whoop_header, meal_header)
    output_header_csv      = header_for_output(output_header_internal)
    expected_col_count     = len(output_header_csv)

    log.info("")
    log.info("Output schema:")
    log.info("  WHOOP columns : %d", len(whoop_header))
    log.info("  Spacer        : 1")
    log.info("  Meal columns  : %d", len(meal_header))
    log.info("  Total columns : %d", expected_col_count)

    # ── 4. Write staging file (never touch the real output until validated) ───
    log.info("")
    log.info("Writing staging file → %s", STAGING_PATH)

    try:
        with open(STAGING_PATH, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(output_header_csv)
            for date in all_dates:
                row = build_output_row(
                    date          = date,
                    whoop_header  = whoop_header,
                    whoop_by_date = whoop_by_date,
                    meal_header   = meal_header,
                    meal_by_date  = meal_by_date,
                )
                writer.writerow(row)
    except OSError as exc:
        log.error("Failed to write staging file: %s", exc)
        sys.exit(1)

    # ── 5. Post-write validation ──────────────────────────────────────────────
    log.info("Running post-write validation…")
    valid = validate_output(
        path           = STAGING_PATH,
        expected_cols  = expected_col_count,
        expected_rows  = len(all_dates),
        whoop_dates    = whoop_dates,
        meal_dates     = meal_dates,
        whoop_col_count= len(whoop_header),
    )

    if not valid:
        log.error("Post-write validation FAILED.  Staging file retained for inspection.")
        log.error("Output file NOT updated.")
        sys.exit(1)

    # ── 6. Atomic rename: staging → final ────────────────────────────────────
    STAGING_PATH.replace(OUTPUT_PATH)
    log.info("Output committed → %s", OUTPUT_PATH)

    # ── 7. Audit log ─────────────────────────────────────────────────────────
    run_end = datetime.now(timezone.utc)
    audit_record = {
        "run_at":            run_start.isoformat(),
        "duration_seconds":  round((run_end - run_start).total_seconds(), 2),
        "output_path":       str(OUTPUT_PATH),
        "total_rows":        len(all_dates),
        "total_cols":        expected_col_count,
        "whoop_cols":        len(whoop_header),
        "meal_cols":         len(meal_header),
        "whoop_date_range":  [min(whoop_dates), max(whoop_dates)] if whoop_dates else [],
        "meal_date_range":   [min(meal_dates),  max(meal_dates)]  if meal_dates  else [],
        "overlap_dates":     len(whoop_dates & meal_dates),
        "whoop_only_dates":  len(whoop_dates - meal_dates),
        "meal_only_dates":   len(meal_dates  - whoop_dates),
        "status":            "SUCCESS",
    }
    append_audit_log(audit_record)
    log.info("")
    log.info("=" * 60)
    log.info("  Consolidation complete.")
    log.info("  Output : %s", OUTPUT_PATH)
    log.info("  Rows   : %d  |  Columns: %d", len(all_dates), expected_col_count)
    log.info("  Audit  : %s", AUDIT_LOG)
    log.info("=" * 60)


if __name__ == "__main__":
    build_consolidated()
