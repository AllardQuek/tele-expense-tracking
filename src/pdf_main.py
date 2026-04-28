"""
Entry point for the PDF statement expense extraction pipeline.

Usage:
  python src/pdf_main.py --input data/youtrip_apr2026.pdf
  python src/pdf_main.py --input data/uob_may2026.pdf --type uob
  python src/pdf_main.py --input data/uob_may2026.pdf --from 2026-04-01 --to 2026-04-15
  python src/pdf_main.py --input data/uob_may2026.pdf --llm-tags

Stages:
  1. parse_pdf          — PDF → raw transaction rows (auto-detects statement type)
  2. filter_by_date     — drop rows outside --from / --to range (optional)
  3. normalize_merchant — clean raw description into readable name
  4. tag_merchant       — keyword rules → semantic fallback
  4b. llm_tag_untagged  — (optional, --llm-tags) send still-untagged rows to OpenRouter
  5. write CSV          — expenses_<type>_MMYYYY.csv
     sidecar            — pdf_untagged_<type>_MMYYYY.json (rows with no tags after all passes)
"""

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import json
from pathlib import Path

from parse_pdf import filter_by_date, parse_pdf
from normalize_merchant import normalize_merchant
from tag_merchant import tag_merchant, llm_tag_untagged


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_period(rows: list[dict]) -> str:
    """Return MMYYYY from the most frequent month among transaction dates."""
    if not rows:
        return datetime.now().strftime("%m%Y")
    from collections import Counter
    month_counts: Counter = Counter()
    for row in rows:
        try:
            d = date.fromisoformat(row["date"])
            month_counts[(d.month, d.year)] += 1
        except ValueError:
            pass
    if not month_counts:
        return datetime.now().strftime("%m%Y")
    month, year = month_counts.most_common(1)[0][0]
    return f"{month:02d}{year}"


def _write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "tags", "cost", "cost(sgd)"])
        writer.writeheader()
        writer.writerows(rows)


def _write_json(data: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run_pdf_pipeline(
    input_path: Path,
    output_dir: Path,
    config_dir: Path,
    statement_type: str | None,
    from_date: date | None,
    to_date: date | None,
    use_llm_tags: bool = False,
    verbose: bool = False,
) -> None:
    print("=" * 60)
    print("PDF Expense Extraction Pipeline")
    print("=" * 60)

    # Stage 1: Parse
    print(f"\n[1/4] Parsing PDF: {input_path.name} ...")
    detected_type, raw_rows = parse_pdf(input_path, statement_type, verbose=verbose)
    print(f"      Detected type: {detected_type}")
    print(f"      {len(raw_rows)} transaction(s) found")

    # Stage 2: Date filter
    filtered_rows = filter_by_date(raw_rows, from_date, to_date)
    if from_date or to_date:
        bounds = f"{from_date or '...'} → {to_date or '...'}"
        print(f"\n[2/4] Date filter ({bounds}): {len(filtered_rows)}/{len(raw_rows)} rows kept")
    else:
        print(f"\n[2/4] Date filter: skipped (no --from/--to specified)")

    if not filtered_rows:
        print("\nNo rows after filtering. Check your --from/--to range.")
        sys.exit(0)

    # Stage 3 + 4: Normalize names and tag
    total_stages = 5 if use_llm_tags else 4
    print(f"\n[3/{total_stages}] Normalizing names and tagging ({len(filtered_rows)} rows)...")

    # Build parallel list so we can patch tags after LLM pass
    rows_working: list[dict] = []  # {name, raw_description, cost_sgd, date, tags}
    for row in filtered_rows:
        name = normalize_merchant(row["raw_description"])
        tags = tag_merchant(name, row["raw_description"], config_dir)
        rows_working.append({
            "name": name,
            "raw_description": row["raw_description"],
            "date": row["date"],
            "cost_sgd": row["cost_sgd"],
            "tags": tags,
        })

    untagged_indices = [i for i, r in enumerate(rows_working) if not r["tags"]]
    tagged_count = len(rows_working) - len(untagged_indices)
    print(f"      {tagged_count} tagged, {len(untagged_indices)} untagged after keyword+semantic passes")

    # Stage 4b: Optional LLM pass on remaining untagged rows
    if use_llm_tags and untagged_indices:
        print(f"\n[4/{total_stages}] LLM tagging {len(untagged_indices)} untagged row(s) via OpenRouter...")
        import json as _json
        tags_file = config_dir / "tags.json"
        allowed_tags = set(_json.loads(tags_file.read_text(encoding="utf-8")))

        llm_input = [
            {"index": i, "name": rows_working[i]["name"], "raw_description": rows_working[i]["raw_description"]}
            for i in untagged_indices
        ]
        llm_results = llm_tag_untagged(llm_input, allowed_tags)

        llm_tagged = 0
        for idx, tags in llm_results.items():
            if tags:
                rows_working[idx]["tags"] = tags
                llm_tagged += 1
        print(f"      LLM tagged {llm_tagged}/{len(untagged_indices)} previously untagged rows")
        # Recalculate untagged after LLM
        untagged_indices = [i for i, r in enumerate(rows_working) if not r["tags"]]

    # Build final accepted + untagged lists
    accepted: list[dict] = [
        {
            "name": r["name"],
            "tags": ", ".join(r["tags"]),
            "cost": "",
            "cost(sgd)": r["cost_sgd"],
        }
        for r in rows_working
    ]
    untagged = [
        {
            "date": rows_working[i]["date"],
            "raw_description": rows_working[i]["raw_description"],
            "name": rows_working[i]["name"],
            "cost_sgd": rows_working[i]["cost_sgd"],
        }
        for i in untagged_indices
    ]

    # Stage 5: Write outputs
    print(f"\n[{total_stages}/{total_stages}] Writing outputs...")
    period = _infer_period(filtered_rows)
    csv_filename = f"expenses_{detected_type}_{period}.csv"
    untagged_filename = f"pdf_untagged_{detected_type}_{period}.json"

    csv_path = output_dir / csv_filename
    untagged_path = output_dir / untagged_filename

    _write_csv(accepted, csv_path)
    print(f"      {len(accepted)} rows → {csv_path}")

    _write_json(untagged, untagged_path)
    if untagged:
        print(f"      {len(untagged)} untagged → {untagged_path}")
        if use_llm_tags:
            print(f"      These rows could not be classified even by the LLM — likely opaque merchant codes.")
        else:
            print(f"      Re-run with --llm-tags to attempt LLM classification, or add keywords to config/merchant_rules.json.")
    else:
        print(f"      0 untagged rows (all transactions classified)")

    print("\n" + "=" * 60)
    print("Done.")
    print(f"  CSV:      {csv_path}")
    if untagged:
        print(f"  Untagged: {untagged_path}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_date_arg(value: str, arg_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date for {arg_name}: '{value}'. Expected YYYY-MM-DD."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PDF statement expense extraction pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/pdf_main.py --input data/youtrip_apr2026.pdf
  python src/pdf_main.py --input data/uob_may2026.pdf --type uob
  python src/pdf_main.py --input data/uob_may2026.pdf --from 2026-04-01 --to 2026-04-15
        """,
    )
    parser.add_argument("--input", required=True, help="Path to the PDF statement")
    parser.add_argument(
        "--llm-tags",
        action="store_true",
        default=False,
        help="Send untagged rows to OpenRouter LLM for a final classification pass (requires OPENROUTER_API_KEY in .env)",
    )
    parser.add_argument(
        "--type",
        choices=["youtrip", "uob"],
        default=None,
        help="Statement type (auto-detected if omitted)",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        default=None,
        help="Include transactions on or after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        default=None,
        help="Include transactions on or before this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for output files (default: output/)",
    )
    parser.add_argument(
        "--config-dir",
        default="config",
        help="Directory containing merchant_rules.json (default: config/)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Print debug info during PDF parsing (table/header/column detection)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    config_dir = Path(args.config_dir)

    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    from_date = _parse_date_arg(args.from_date, "--from") if args.from_date else None
    to_date = _parse_date_arg(args.to_date, "--to") if args.to_date else None

    run_pdf_pipeline(
        input_path=input_path,
        output_dir=output_dir,
        config_dir=config_dir,
        statement_type=args.type,
        from_date=from_date,
        to_date=to_date,
        use_llm_tags=args.llm_tags,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
