"""
Stage 3: Send candidate messages to the LLM for expense extraction.

Uses OpenRouter API with the model configured in .env.
Processes candidates in micro-batches and writes all results to a JSON file.
"""

import json
import os
import random
import time
from pathlib import Path

import requests
import urllib3
from dotenv import load_dotenv

# SSL verification is disabled for this device due to a local certificate issue.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
BATCH_SIZE = 20
RETRY_ATTEMPTS = 5
BASE_RETRY_DELAY_SECONDS = 2   # doubles each attempt with jitter
MAX_RETRY_DELAY_SECONDS = 120


def _load_system_prompt(config_dir: Path) -> str:
    prompt_path = config_dir / "prompt.md"
    return prompt_path.read_text(encoding="utf-8")


def _build_user_message(batch: list[dict]) -> str:
    return json.dumps(batch, ensure_ascii=False)


def _backoff_delay(attempt: int, retry_after: int | None) -> None:
    """Sleep before a retry using exponential backoff with jitter, or Retry-After if provided."""
    if retry_after is not None:
        delay = float(retry_after)
    else:
        delay = min(BASE_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)), MAX_RETRY_DELAY_SECONDS)
        delay += random.uniform(0, delay * 0.2)  # add up to 20% jitter
    print(f"  [extract] Waiting {delay:.1f}s before retry...")
    time.sleep(delay)


def _call_openrouter(system_prompt: str, user_message: str, api_key: str, model: str) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "response_format": {"type": "json_object"},
    }

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            response = requests.post(
                OPENROUTER_API_URL,
                headers=headers,
                json=payload,
                timeout=60,
                verify=False,
            )
            if response.status_code == 429:
                retry_after_str = response.headers.get("Retry-After")
                retry_after = int(retry_after_str) if retry_after_str else None
                print(f"  [extract] Rate limited (429). Attempt {attempt}/{RETRY_ATTEMPTS}.")
                if attempt < RETRY_ATTEMPTS:
                    _backoff_delay(attempt, retry_after)
                continue
            if response.status_code == 400:
                # Not retryable — likely context too long or malformed input
                print(f"  [extract] Bad request (400) — skipping batch. Response: {response.text[:300]}")
                return {"results": []}
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"].get("content")
            if content is None:
                print(f"  [extract] Attempt {attempt}/{RETRY_ATTEMPTS} — model returned null content.")
                if attempt < RETRY_ATTEMPTS:
                    _backoff_delay(attempt, None)
                continue
            return json.loads(content)
        except (requests.RequestException, KeyError, json.JSONDecodeError) as exc:
            print(f"  [extract] Attempt {attempt}/{RETRY_ATTEMPTS} failed: {exc}")
            if attempt < RETRY_ATTEMPTS:
                _backoff_delay(attempt, None)

    # Return empty results for all messages in the batch on total failure
    return {"results": []}


def _load_checkpoint(checkpoint_path: Path) -> dict[int, list]:
    """Load previously completed message_id -> expenses from checkpoint file."""
    if not checkpoint_path.exists():
        return {}
    with open(checkpoint_path, encoding="utf-8") as f:
        records = json.load(f)
    return {r["message_id"]: r for r in records}


def _append_checkpoint(checkpoint_path: Path, batch_records: list[dict]) -> None:
    """Append a completed batch to the checkpoint file."""
    existing = []
    if checkpoint_path.exists():
        with open(checkpoint_path, encoding="utf-8") as f:
            existing = json.load(f)
    existing.extend(batch_records)
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def extract_expenses(
    input_path: Path,
    output_path: Path,
    config_dir: Path,
) -> int:
    """
    Read candidate JSONL, batch through LLM, write extracted_expenses.json.
    Supports resuming interrupted runs via a checkpoint file.
    Returns total number of expense objects extracted.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    model = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free")

    if not api_key or api_key == "your_api_key_here":
        raise ValueError(
            "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key."
        )

    system_prompt = _load_system_prompt(config_dir)

    # Load all candidates
    candidates = []
    with open(input_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                candidates.append(json.loads(line))

    # Checkpoint lives alongside the output file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_path.parent / (output_path.stem + "_checkpoint.json")
    completed = _load_checkpoint(checkpoint_path)

    if completed:
        print(f"  [extract] Resuming — {len(completed)} message(s) already processed from checkpoint.")

    total_expenses = 0
    total_batches = (len(candidates) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[batch_start : batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1

        # Skip messages already in checkpoint
        pending = [m for m in batch if m["message_id"] not in completed]
        skipped = len(batch) - len(pending)

        if not pending:
            print(f"  [extract] Batch {batch_num}/{total_batches} — skipped (all {skipped} already done).")
            continue

        skip_info = f", {skipped} already done" if skipped else ""
        print(f"  [extract] Batch {batch_num}/{total_batches} ({len(pending)} messages{skip_info})...")

        # Send only message_id and text to the LLM
        llm_input = [{"message_id": m["message_id"], "text": m["text"]} for m in pending]
        response = _call_openrouter(system_prompt, _build_user_message(llm_input), api_key, model)

        batch_results = response.get("results", [])
        result_map = {r["message_id"]: r.get("expenses", []) for r in batch_results if "message_id" in r}

        batch_records = []
        for msg in pending:
            mid = msg["message_id"]
            expenses = result_map.get(mid, [])
            record = {
                "message_id": mid,
                "timestamp": msg["timestamp"],
                "text": msg["text"],
                "expenses": expenses,
            }
            batch_records.append(record)
            completed[mid] = record
            total_expenses += len(expenses)

        # Persist this batch immediately before moving on
        _append_checkpoint(checkpoint_path, batch_records)

        # Brief pause between batches
        if batch_start + BATCH_SIZE < len(candidates):
            time.sleep(1)

    # Write final output from completed checkpoint
    all_results = list(completed.values())
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    # Clean up checkpoint on successful completion
    if checkpoint_path.exists():
        checkpoint_path.unlink()
        print("  [extract] Checkpoint cleared.")

    return total_expenses


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract expenses via LLM")
    parser.add_argument(
        "--input",
        default="output/candidate_messages.jsonl",
        help="Candidate JSONL input",
    )
    parser.add_argument(
        "--output",
        default="output/extracted_expenses.json",
        help="Extracted expenses JSON output",
    )
    parser.add_argument(
        "--config",
        default="config",
        help="Config directory containing prompt.md and tags.json",
    )
    args = parser.parse_args()

    n = extract_expenses(Path(args.input), Path(args.output), Path(args.config))
    print(f"[extract_expenses] Extracted {n} expense(s) total")
