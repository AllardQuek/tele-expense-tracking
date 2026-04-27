"""
Stage 1: Parse and normalize a Telegram JSON export.

Reads the raw Telegram export JSON and writes a JSONL file where each line is:
  {"message_id": int, "timestamp": str, "text": str}

Skips:
- service messages (type != "message")
- messages with empty text after flattening
"""

import json
import sys
from pathlib import Path


def flatten_text(text_field) -> str:
    """
    Telegram exports `text` as either:
      - a plain string: "hello world"
      - an array of objects: [{"type": "plain", "text": "hello "}, {"type": "link", "text": "trip.com"}]
    Returns a single flattened string in both cases.
    """
    if isinstance(text_field, str):
        return text_field.strip()
    if isinstance(text_field, list):
        parts = []
        for part in text_field:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(part.get("text", ""))
        return "".join(parts).strip()
    return ""


def parse_export(input_path: Path, output_path: Path) -> int:
    """
    Parse the Telegram export JSON and write normalized JSONL.
    Replies are stitched to their parent message text for context.
    Returns the count of messages written.
    """
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])

    # Build a lookup of message_id -> flattened text for reply stitching.
    # Includes all messages (even photo-only) so we can at least attempt a stitch.
    text_by_id: dict[int, str] = {}
    for msg in messages:
        if msg.get("type") == "message":
            text_by_id[msg["id"]] = flatten_text(msg.get("text", ""))

    count = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as out:
        for msg in messages:
            if msg.get("type") != "message":
                continue

            text = flatten_text(msg.get("text", ""))

            # Stitch parent context if this is a reply
            parent_id = msg.get("reply_to_message_id")
            if parent_id and parent_id in text_by_id:
                parent_text = text_by_id[parent_id]
                if parent_text:
                    text = f"[parent: {parent_text}]\n{text}" if text else f"[parent: {parent_text}]"

            if not text:
                continue

            record = {
                "message_id": msg["id"],
                "timestamp": msg.get("date", ""),
                "text": text,
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    return count


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse Telegram JSON export to JSONL")
    parser.add_argument("--input", required=True, help="Path to raw Telegram export JSON")
    parser.add_argument(
        "--output",
        default="output/normalized_messages.jsonl",
        help="Path to write normalized JSONL",
    )
    args = parser.parse_args()

    n = parse_export(Path(args.input), Path(args.output))
    print(f"[parse_export] Wrote {n} messages to {args.output}")
