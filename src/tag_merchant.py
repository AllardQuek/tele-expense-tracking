"""
Hybrid merchant tagger.

Strategy:
  1. Keyword rules (config/merchant_rules.json): substring match against
     the lowercased combination of normalized name + raw description.
     All matching tags are collected.
  2. Semantic fallback: if no keyword matched, embed the merchant name with
     paraphrase-MiniLM-L6-v2 and compare via cosine similarity against
     per-tag anchor phrases. Returns the highest-scoring tag if it clears
     the similarity threshold.
  3. No match: return empty list (row flagged as untagged).

Semantic model is loaded lazily and cached for the process lifetime —
first call triggers a one-time ~80MB download if not already cached.

LLM fallback (optional, via llm_tag_untagged):
  Sends a batch of untagged rows to OpenRouter. Only fires when --llm-tags
  is passed to pdf_main.py. Reuses the same OpenRouter setup as the
  Telegram pipeline.
"""

import json
import os
import random
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

import requests
import urllib3
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
load_dotenv()

# Tag anchor phrases: rich descriptive text gives the model more signal than
# the bare tag name alone. Each string is embedded as a single unit.
_TAG_ANCHORS: dict[str, str] = {
    "food": "restaurant meal food drink cafe hawker buffet dessert coffee tea snack lunch dinner breakfast",
    "transport": "taxi ride bus train flight transit shuttle airport transfer tram metro subway commute",
    "accomms": "hotel hostel accommodation resort villa airbnb lodge inn room stay overnight check-in",
    "entertainment": "museum cinema concert tour attraction ticket activity show gallery theme park",
    "essentials": "pharmacy grocery supermarket clinic hospital spa salon haircut laundry toiletries medicine",
    "souvenirs": "souvenir gift shopping clothing bag market craft jewelry keepsake",
    "travel": "flight airfare travel insurance visa border crossing international trip",
}

_MODEL_NAME = "paraphrase-MiniLM-L6-v2"
_SIMILARITY_THRESHOLD = 0.30  # conservative — semantic fallback only fires when reasonably confident


@lru_cache(maxsize=1)
def _load_model():
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(_MODEL_NAME)
    except ImportError as e:
        raise ImportError(
            "sentence-transformers is required for semantic fallback: "
            "pip install sentence-transformers"
        ) from e
    except Exception as e:
        # Network, SSL, or other download errors — return None to skip semantic tagging
        print(f"    [warning] could not load semantic model ({type(e).__name__}: {str(e)[:80]}...)")
        print(f"    [warning] skipping semantic tagging pass, using keyword rules only")
        return None


@lru_cache(maxsize=1)
def _get_anchor_embeddings():
    import numpy as np
    model = _load_model()
    if model is None:
        return None, None
    tags = list(_TAG_ANCHORS.keys())
    phrases = [_TAG_ANCHORS[t] for t in tags]
    embeddings = model.encode(phrases, convert_to_numpy=True, normalize_embeddings=True)
    return tags, embeddings


def _semantic_tag(text: str) -> Optional[str]:
    """Return the best-matching tag via cosine similarity, or None if below threshold or model unavailable."""
    import numpy as np
    model = _load_model()
    if model is None:
        return None
    
    result = _get_anchor_embeddings()
    if result is None or result == (None, None):
        return None
    
    tags, anchor_embeddings = result

    query_embedding = model.encode([text], convert_to_numpy=True, normalize_embeddings=True)[0]
    # Cosine similarity = dot product when both vectors are L2-normalised
    scores = anchor_embeddings @ query_embedding
    best_idx = int(np.argmax(scores))
    best_score = float(scores[best_idx])

    if best_score >= _SIMILARITY_THRESHOLD:
        return tags[best_idx]
    return None


def _load_rules(config_dir: Path) -> dict[str, list[str]]:
    rules_path = config_dir / "merchant_rules.json"
    return json.loads(rules_path.read_text(encoding="utf-8"))


def _build_keyword_index(rules: dict[str, list[str]]) -> list[tuple[str, str]]:
    """Return flat list of (keyword, tag) sorted longest-keyword-first."""
    index = []
    for tag, keywords in rules.items():
        for kw in keywords:
            index.append((kw.lower(), tag))
    index.sort(key=lambda x: len(x[0]), reverse=True)
    return index


def tag_merchant(
    name: str,
    raw_description: str,
    config_dir: Path,
) -> list[str]:
    """
    Assign tags to a merchant.

    Pass 1 — keyword rules: fast, exact substring match. Catches known
    merchants and explicit category words.

    Pass 2 — semantic fallback: embeds the merchant name and compares
    against per-tag anchor phrases. Catches English-meaning words like
    "buffet", "tram", "clinic" that have no keyword rule. Will not help
    with opaque local-language merchant names (e.g. Vietnamese abbreviations).

    Args:
        name:            Normalized merchant name.
        raw_description: Original description from the statement.
        config_dir:      Directory containing merchant_rules.json.

    Returns:
        Sorted list of matching tag strings. Empty if no match found.
    """
    rules = _load_rules(config_dir)
    index = _build_keyword_index(rules)

    # Combined search text: normalized name + raw description (lowercased)
    search_text = f"{name} {raw_description}".lower()

    # --- Pass 1: keyword substring match ---
    matched_tags: set[str] = set()
    for keyword, tag in index:
        if keyword in search_text:
            matched_tags.add(tag)

    if matched_tags:
        return sorted(matched_tags)

    # --- Pass 2: semantic similarity fallback ---
    # Use the normalized name only (cleaner signal than raw description)
    semantic_tag = _semantic_tag(name)
    if semantic_tag:
        return [semantic_tag]

    return []


# ---------------------------------------------------------------------------
# LLM batch tagger (optional, used by pdf_main.py --llm-tags)
# ---------------------------------------------------------------------------

_OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
_LLM_BATCH_SIZE = 20
_LLM_RETRY_ATTEMPTS = 5
_LLM_BASE_DELAY = 2
_LLM_MAX_DELAY = 120

_LLM_SYSTEM_PROMPT = """You are an expense categorisation assistant.

You will receive a JSON array of merchant objects. Each has:
  - "id": integer index
  - "name": cleaned merchant name
  - "raw": original description from a bank statement

Classify each merchant into exactly one tag from this list:
  accomms, transport, entertainment, food, essentials, souvenirs, travel

Rules:
- Return ONLY a JSON object: {"results": [{"id": <int>, "tags": [<tag>]}, ...]}
- One tag per merchant. No explanation, no markdown.
- If you genuinely cannot determine the category (e.g. a meaningless abbreviation),
  return "tags": [] for that item.
- Use all available context: both "name" and "raw" together.
"""


def _llm_backoff(attempt: int, retry_after: Optional[int]) -> None:
    if retry_after is not None:
        delay = float(retry_after)
    else:
        delay = min(_LLM_BASE_DELAY * (2 ** (attempt - 1)), _LLM_MAX_DELAY)
        delay += random.uniform(0, delay * 0.2)
    print(f"  [llm-tags] Waiting {delay:.1f}s before retry...")
    time.sleep(delay)


def _call_llm(batch: list[dict], api_key: str, model: str) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _LLM_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
    }
    for attempt in range(1, _LLM_RETRY_ATTEMPTS + 1):
        try:
            response = requests.post(
                _OPENROUTER_API_URL,
                headers=headers,
                json=payload,
                timeout=60,
                verify=False,
            )
            if response.status_code == 429:
                retry_after_str = response.headers.get("Retry-After")
                retry_after = int(retry_after_str) if retry_after_str else None
                print(f"  [llm-tags] Rate limited (429). Attempt {attempt}/{_LLM_RETRY_ATTEMPTS}.")
                if attempt < _LLM_RETRY_ATTEMPTS:
                    _llm_backoff(attempt, retry_after)
                continue
            if response.status_code == 400:
                print(f"  [llm-tags] Bad request (400) — skipping batch.")
                return {"results": []}
            response.raise_for_status()
            content = response.json()["choices"][0]["message"].get("content")
            if content is None:
                if attempt < _LLM_RETRY_ATTEMPTS:
                    _llm_backoff(attempt, None)
                continue
            return json.loads(content)
        except (requests.RequestException, KeyError, json.JSONDecodeError) as exc:
            print(f"  [llm-tags] Attempt {attempt}/{_LLM_RETRY_ATTEMPTS} failed: {exc}")
            if attempt < _LLM_RETRY_ATTEMPTS:
                _llm_backoff(attempt, None)
    return {"results": []}


def llm_tag_untagged(
    untagged_rows: list[dict],
    allowed_tags: set[str],
) -> dict[int, list[str]]:
    """
    Send a list of untagged rows to the LLM for classification.

    Args:
        untagged_rows: List of dicts with keys: index (int), name, raw_description.
        allowed_tags:  Set of valid tag strings for post-LLM validation.

    Returns:
        Dict mapping original row index → list of tags (may be empty).
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    model = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-7b-instruct:free")

    if not api_key or api_key == "your_api_key_here":
        raise ValueError(
            "OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key.\n"
            "Or run without --llm-tags to skip LLM classification."
        )

    results: dict[int, list[str]] = {}
    total = len(untagged_rows)
    n_batches = (total + _LLM_BATCH_SIZE - 1) // _LLM_BATCH_SIZE

    for batch_num in range(n_batches):
        start = batch_num * _LLM_BATCH_SIZE
        batch = untagged_rows[start: start + _LLM_BATCH_SIZE]

        payload = [
            {"id": row["index"], "name": row["name"], "raw": row["raw_description"]}
            for row in batch
        ]

        print(f"  [llm-tags] Batch {batch_num + 1}/{n_batches} ({len(batch)} rows)...")
        response = _call_llm(payload, api_key, model)

        for item in response.get("results", []):
            idx = item.get("id")
            tags = item.get("tags", [])
            if idx is None:
                continue
            # Validate — only keep tags in the allowed set
            valid = sorted(t for t in tags if t in allowed_tags)
            results[idx] = valid

    return results
