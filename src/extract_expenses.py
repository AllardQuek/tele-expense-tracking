"""
Stage 3: Send candidate messages to the LLM for expense extraction.

Uses OpenRouter API with the model configured in .env.
Processes candidates in micro-batches and writes all results to a JSON file.
"""

import json
import os
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
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5


def _load_system_prompt(config_dir: Path) -> str:
    prompt_path = config_dir / "prompt.md"
    return prompt_path.read_text(encoding="utf-8")


def _build_user_message(batch: list[dict]) -> str:
    return json.dumps(batch, ensure_ascii=False)


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
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except (requests.RequestException, KeyError, json.JSONDecodeError) as exc:
            print(f"  [extract] Attempt {attempt}/{RETRY_ATTEMPTS} failed: {exc}")
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS)

    # Return empty results for all messages in the batch on total failure
    return {"results": []}


def extract_expenses(
    input_path: Path,
    output_path: Path,
    config_dir: Path,
) -> int:
    """
    Read candidate JSONL, batch through LLM, write extracted_expenses.json.
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

    all_results = []
    total_expenses = 0

    for batch_start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[batch_start : batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(candidates) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  [extract] Batch {batch_num}/{total_batches} ({len(batch)} messages)...")

        # Send only message_id and text to the LLM
        llm_input = [{"message_id": m["message_id"], "text": m["text"]} for m in batch]
        response = _call_openrouter(system_prompt, _build_user_message(llm_input), api_key, model)

        batch_results = response.get("results", [])

        # Build a lookup of message_id -> expenses from the LLM response
        result_map = {r["message_id"]: r.get("expenses", []) for r in batch_results if "message_id" in r}

        # Preserve all candidates in the output, even if LLM returned nothing for them
        for msg in batch:
            mid = msg["message_id"]
            expenses = result_map.get(mid, [])
            all_results.append({
                "message_id": mid,
                "timestamp": msg["timestamp"],
                "text": msg["text"],
                "expenses": expenses,
            })
            total_expenses += len(expenses)

        # Brief pause to avoid hammering the rate limit
        if batch_start + BATCH_SIZE < len(candidates):
            time.sleep(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

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
