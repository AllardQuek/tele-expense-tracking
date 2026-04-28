"""
Rules-based merchant name normalization.

Cleans raw bank/wallet description strings into short, readable names.
No external dependencies.

Examples:
  "GRAB*GRABSH1234567"        → "Grab"
  "AGODA.COM SG 12345"        → "Agoda"
  "MCDONALD'S SINGAPORE"      → "Mcdonald's"
  "SPOTIFY AB Q12345678"      → "Spotify"
  "GRAB GRABFOOD*12345"       → "Grab Grabfood"
"""

import re


# Suffixes to strip (case-insensitive, whole word / end of string)
_STRIP_SUFFIXES = [
    r"\bPTE\.?\s*LTD\.?",
    r"\bSINGAPORE\b",
    r"\bSG\b",
    r"\bINT[']?L\b",
    r"\bINTERNATIONAL\b",
    r"\.COM\b",
    r"\.CO\b",
    r"\.SG\b",
]

# Patterns that look like transaction codes / reference numbers to remove
_STRIP_CODES = [
    r"\*[A-Z0-9]{4,}",        # *GRABSH1234567
    r"#[A-Z0-9]{4,}",         # #REF12345
    r"\b[A-Z]{1,3}[0-9]{5,}", # Q12345678, AB9999999
    r"\b[0-9]{5,}\b",         # trailing long numbers
]


def normalize_merchant(raw: str, max_words: int = 4) -> str:
    """
    Clean a raw bank description into a short readable merchant name.

    Args:
        raw:       Raw description string from the statement.
        max_words: Maximum number of words to keep after cleaning.

    Returns:
        Title-cased cleaned name, or the original (title-cased) if cleaning
        produces an empty string.
    """
    text = raw.strip()

    # Remove transaction codes first (before suffix stripping, order matters)
    for pattern in _STRIP_CODES:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # Remove known noise suffixes
    for pattern in _STRIP_SUFFIXES:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # Collapse separators: dots, asterisks, slashes, underscores → space
    text = re.sub(r"[.*/_\-]+", " ", text)

    # Remove any remaining isolated single characters (e.g. stray "Q" or "A")
    text = re.sub(r"\b[A-Z]\b", "", text)

    # Collapse whitespace
    text = " ".join(text.split())

    # Trim to max_words
    words = text.split()
    if len(words) > max_words:
        words = words[:max_words]
    text = " ".join(words)

    # Title-case
    text = text.title()

    # Fallback: if cleaning wiped everything, use original title-cased
    if not text.strip():
        return raw.strip().title()

    return text
