"""
Stage 4: Validate extracted expenses and write the final CSV.

Reads extracted_expenses.json, validates each expense row, normalizes fields,
writes valid rows to expenses.csv and rejected rows to rejected_rows.json.
"""

import csv
import json
from pathlib import Path


def _load_allowed_tags(config_dir: Path) -> set[str]:
    tags_path = config_dir / "tags.json"
    tags = json.loads(tags_path.read_text(encoding="utf-8"))
    return set(tags)


def _normalize_name(name: str) -> str:
    return name.strip().title()


def _normalize_tags(tags: list, allowed: set[str]) -> tuple[list[str], list[str]]:
    """Returns (valid_tags, unknown_tags)."""
    seen = set()
    valid = []
    unknown = []
    for tag in tags:
        tag = tag.strip().lower()
        if tag in seen:
            continue
        seen.add(tag)
        if tag in allowed:
            valid.append(tag)
        else:
            unknown.append(tag)
    return sorted(valid), unknown


def validate_and_write_csv(
    input_path: Path,
    csv_output_path: Path,
    rejected_output_path: Path,
    config_dir: Path,
) -> tuple[int, int]:
    """
    Validate expenses and write CSV.
    Returns (accepted_count, rejected_count).
    """
    allowed_tags = _load_allowed_tags(config_dir)

    with open(input_path, encoding="utf-8") as f:
        extracted = json.load(f)

    accepted_rows = []
    rejected_rows = []
    seen_keys = set()

    for message in extracted:
        message_id = message.get("message_id")
        expenses = message.get("expenses", [])

        for expense in expenses:
            name_raw = expense.get("name", "")
            tags_raw = expense.get("tags", [])
            cost = expense.get("cost")
            cost_sgd = expense.get("cost_sgd")

            rejection_reasons = []

            # Validate name
            if not name_raw or not name_raw.strip():
                rejection_reasons.append("empty name")

            # Validate tags
            valid_tags, unknown_tags = _normalize_tags(tags_raw, allowed_tags)
            if not tags_raw:
                rejection_reasons.append("no tags provided")
            if unknown_tags:
                rejection_reasons.append(f"unknown tags: {unknown_tags}")
            if not valid_tags and not rejection_reasons:
                rejection_reasons.append("no valid tags after filtering")

            # Validate cost columns: both filled is an error
            cost_is_set = cost is not None and cost != ""
            cost_sgd_is_set = cost_sgd is not None and cost_sgd != ""

            if cost_is_set and cost_sgd_is_set:
                rejection_reasons.append("both cost and cost_sgd are filled — only one allowed")
            elif cost_is_set and float(cost) < 0:
                rejection_reasons.append(f"negative cost: {cost}")
            elif cost_sgd_is_set and float(cost_sgd) < 0:
                rejection_reasons.append(f"negative cost_sgd: {cost_sgd}")

            # Deduplicate: same message + same normalized name
            name_norm = _normalize_name(name_raw)
            dedup_key = (message_id, name_norm.lower())
            if dedup_key in seen_keys:
                rejection_reasons.append("duplicate expense in same message")
            else:
                seen_keys.add(dedup_key)

            if rejection_reasons:
                rejected_rows.append({
                    "message_id": message_id,
                    "text": message.get("text", ""),
                    "expense": expense,
                    "reasons": rejection_reasons,
                })
                continue

            # Build final row — only one cost column is filled
            accepted_rows.append({
                "name": name_norm,
                "tags": ", ".join(valid_tags),
                "cost": "" if not cost_is_set else cost,
                "cost(sgd)": "" if not cost_sgd_is_set else cost_sgd,
            })

    # Write CSV
    csv_output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "tags", "cost", "cost(sgd)"])
        writer.writeheader()
        writer.writerows(accepted_rows)

    # Write rejected rows
    rejected_output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(rejected_output_path, "w", encoding="utf-8") as f:
        json.dump(rejected_rows, f, ensure_ascii=False, indent=2)

    return len(accepted_rows), len(rejected_rows)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate expenses and write CSV")
    parser.add_argument(
        "--input",
        default="output/extracted_expenses.json",
        help="Extracted expenses JSON input",
    )
    parser.add_argument(
        "--output",
        default="output/expenses.csv",
        help="Final CSV output",
    )
    parser.add_argument(
        "--rejected",
        default="output/rejected_rows.json",
        help="Rejected rows JSON output",
    )
    parser.add_argument(
        "--config",
        default="config",
        help="Config directory containing tags.json",
    )
    args = parser.parse_args()

    accepted, rejected = validate_and_write_csv(
        Path(args.input),
        Path(args.output),
        Path(args.rejected),
        Path(args.config),
    )
    print(f"[validate] {accepted} accepted → {args.output}")
    print(f"[validate] {rejected} rejected → {args.rejected}")
