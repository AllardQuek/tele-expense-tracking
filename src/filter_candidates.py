"""
Stage 2: Filter normalized messages to expense candidates.

Recall-first: it is better to pass extra messages to the LLM than to miss
real expenses. The filter is intentionally broad.

A message is kept if it:
  - contains any digit (price amounts), OR
  - contains any known expense-signal word/phrase

Writes filtered records to a JSONL file in the same format as the input.
"""

import json
import re
from pathlib import Path

# Recall-first: broad set of expense-signal terms
# Includes English words and common Singlish/regional terms
EXPENSE_SIGNAL_WORDS = [
    # Transport
    "grab", "gojek", "taxi", "cab", "uber", "lyft", "bus", "mrt", "train",
    "ferry", "boat", "tuk.?tuk", "tuktuk", "motorbike", "bike", "scooter",
    "flight", "airfare", "airport", "transfer", "transit", "ticket",
    # Accommodation
    "hotel", "hostel", "airbnb", "bnb", "guesthouse", "resort", "villa",
    "accommodation", "accomm", "stay", "checkin", "check.in", "checkout",
    # Food & drink
    "lunch", "dinner", "breakfast", "supper", "brunch", "meal", "food",
    "coffee", "cafe", "restaurant", "hawker", "kopitiam", "dabao", "takeaway",
    "caifan", "noodle", "soup", "buffet", "dessert", "drinks", "beer", "wine",
    # Shopping & essentials
    "ntuc", "fairprice", "supermarket", "grocery", "groceries", "convenience",
    "pharmacy", "medicine", "sim", "data", "sunscreen", "toiletries",
    # Entertainment & activities
    "museum", "gallery", "entry", "admission", "tour", "attraction",
    "ticket", "show", "concert", "cinema", "movie", "theme.?park",
    "massage", "spa", "snorkel", "dive", "kayak", "hike",
    # Currency signals
    "sgd", "usd", "eur", "gbp", "jpy", "thb", "myr", "idr", "vnd", "php",
    "baht", "ringgit", "rupiah", "dong", "peso", "yen", "pound", "euro",
    # Generic spend signals
    "paid", "pay", "spent", "cost", "price", "fee", "charge", "bought",
    "purchased", "bill", "receipt", "total", "per pax", "per person",
    "souvenir", "gift", "shopping",
]

# Pre-compile a single regex for efficiency
_SIGNAL_RE = re.compile(
    r"(?<!\w)(" + "|".join(EXPENSE_SIGNAL_WORDS) + r")(?!\w)",
    re.IGNORECASE,
)
_DIGIT_RE = re.compile(r"\d")


def is_candidate(text: str) -> bool:
    if _DIGIT_RE.search(text):
        return True
    if _SIGNAL_RE.search(text):
        return True
    return False


def filter_candidates(input_path: Path, output_path: Path, limit: int = 0) -> tuple[int, int]:
    """
    Read normalized JSONL and write candidate JSONL.
    If limit > 0, stop after writing that many candidates (pilot mode).
    Returns (total_read, candidates_written).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    kept = 0

    with open(input_path, encoding="utf-8") as f_in, \
         open(output_path, "w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            total += 1
            record = json.loads(line)
            if is_candidate(record["text"]):
                f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                kept += 1
                if limit > 0 and kept >= limit:
                    break

    return total, kept


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Filter expense candidate messages")
    parser.add_argument(
        "--input",
        default="output/normalized_messages.jsonl",
        help="Normalized JSONL input",
    )
    parser.add_argument(
        "--output",
        default="output/candidate_messages.jsonl",
        help="Candidate JSONL output",
    )
    parser.add_argument(
        "--pilot",
        type=int,
        default=0,
        help="Limit output to first N candidates (0 = no limit)",
    )
    args = parser.parse_args()

    total, kept = filter_candidates(Path(args.input), Path(args.output), limit=args.pilot)
    print(f"[filter_candidates] {kept}/{total} messages kept as candidates")
