"""
Entry point for the Telegram expense extraction pipeline.

Usage:
  python src/main.py --input data/result_080426.json
  python src/main.py --input data/result_080426.json --pilot 50

Stages:
  1. parse_export    — JSON → normalized_messages.jsonl
  2. filter_candidates — normalized → candidate_messages.jsonl
  3. extract_expenses  — candidates → extracted_expenses.json  (LLM call)
  4. validate_and_write_csv — extracted → expenses.csv + rejected_rows.json
"""

import argparse
import sys
from pathlib import Path

# Allow running from project root: python src/main.py
sys.path.insert(0, str(Path(__file__).parent))

from parse_export import parse_export
from filter_candidates import filter_candidates
from extract_expenses import extract_expenses
from validate_and_write_csv import validate_and_write_csv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Telegram expense extraction pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/main.py --input data/result_080426.json
  python src/main.py --input data/result_080426.json --pilot 50
        """,
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the raw Telegram JSON export",
    )
    parser.add_argument(
        "--pilot",
        type=int,
        default=0,
        help="Process only the first N expense candidates (0 = all)",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for all intermediate and final outputs (default: output/)",
    )
    parser.add_argument(
        "--config-dir",
        default="config",
        help="Directory containing tags.json and prompt.md (default: config/)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    config_dir = Path(args.config_dir)

    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    normalized_path = output_dir / "normalized_messages.jsonl"
    candidates_path = output_dir / "candidate_messages.jsonl"
    extracted_path = output_dir / "extracted_expenses.json"
    csv_path = output_dir / "expenses.csv"
    rejected_path = output_dir / "rejected_rows.json"

    print("=" * 60)
    print("Telegram Expense Extraction Pipeline")
    if args.pilot:
        print(f"PILOT MODE: first {args.pilot} candidates only")
    print("=" * 60)

    # Stage 1: Parse
    print("\n[1/4] Parsing export...")
    n_messages = parse_export(input_path, normalized_path)
    print(f"      {n_messages} messages normalized → {normalized_path}")

    # Stage 2: Filter
    print("\n[2/4] Filtering candidates...")
    total, candidates = filter_candidates(normalized_path, candidates_path, limit=args.pilot)
    print(f"      {candidates}/{total} messages kept as candidates → {candidates_path}")

    if candidates == 0:
        print("\nNo candidates found. Check your input file and filter rules.")
        sys.exit(0)

    # Stage 3: LLM extraction
    print(f"\n[3/4] Extracting expenses via LLM ({candidates} candidates)...")
    n_expenses = extract_expenses(input_path=candidates_path, output_path=extracted_path, config_dir=config_dir)
    print(f"      {n_expenses} expense(s) extracted → {extracted_path}")

    # Stage 4: Validate and write CSV
    print("\n[4/4] Validating and writing CSV...")
    accepted, rejected = validate_and_write_csv(extracted_path, csv_path, rejected_path, config_dir)
    print(f"      {accepted} rows → {csv_path}")
    print(f"      {rejected} rejected → {rejected_path}")

    print("\n" + "=" * 60)
    print("Done.")
    print(f"  Final CSV:      {csv_path}")
    print(f"  Rejected rows:  {rejected_path}")
    if rejected > 0:
        print(f"\n  Review {rejected} rejected row(s) in {rejected_path} for manual fixes.")
    print("=" * 60)


if __name__ == "__main__":
    main()
