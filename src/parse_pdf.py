"""
PDF statement parser for YouTrip and UOB credit card statements.

Supports:
  - YouTrip: columns "Completed Date (in SGT) | Description | Money Out | Money In | Balance"
  - UOB credit card: columns "Post Date | Trans Date | Description of Transaction | Transaction Amount SGD"

Auto-detects statement type from first-page text. Override with statement_type arg.

Each row produced:
  {
    "date":            str (YYYY-MM-DD),
    "raw_description": str,
    "cost_sgd":        float,
  }
"""

import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

try:
    import pdfplumber
except ImportError as e:
    raise ImportError("pdfplumber is required: pip install pdfplumber") from e


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

_YOUTRIP_MARKERS = ["youtrip", "you technologies"]
_UOB_MARKERS = ["united overseas bank", "uob"]


def detect_statement_type(pdf_path: Path) -> str:
    """
    Determine statement type via multiple heuristics (in order):
    1. Filename contains 'youtrip' or 'uob' (most reliable in practice)
    2. Scan first 3 pages of PDF text for known brand markers (fallback)

    Raises ValueError if all detection methods fail.

    Note: Text marker matching is not guaranteed for all statement variants.
    If auto-detection fails, use --type youtrip|uob to specify manually.
    """
    # Heuristic 1: filename
    filename_lower = pdf_path.name.lower()
    if "youtrip" in filename_lower:
        return "youtrip"
    if "uob" in filename_lower:
        return "uob"

    # Heuristic 2 & 3: scan text from multiple pages
    with pdfplumber.open(pdf_path) as pdf:
        pages_to_scan = min(3, len(pdf.pages))
        for page_idx in range(pages_to_scan):
            page_text = (pdf.pages[page_idx].extract_text() or "").lower()

            for marker in _YOUTRIP_MARKERS:
                if marker in page_text:
                    return "youtrip"
            for marker in _UOB_MARKERS:
                if marker in page_text:
                    return "uob"

    raise ValueError(
        f"Could not auto-detect statement type from '{pdf_path.name}'.\n"
        "Checked: filename, and first 3 pages of text.\n"
        "Use --type youtrip|uob to specify it manually."
    )


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------

_DATE_FORMATS = [
    "%d %b %Y",   # 01 Apr 2026
    "%d/%m/%Y",   # 01/04/2026
    "%d-%m-%Y",   # 01-04-2026
    "%Y-%m-%d",   # 2026-04-01
    "%d %B %Y",   # 01 April 2026
    "%d/%m/%y",   # 01/04/26
]


def _parse_date(raw: str) -> Optional[date]:
    raw = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Amount parsing helper
# ---------------------------------------------------------------------------

def _parse_amount(raw: str) -> Optional[float]:
    """Strip currency symbols, commas, spaces and return float, or None."""
    if not raw or not raw.strip():
        return None
    cleaned = re.sub(r"[^\d.]", "", raw.strip())
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Column matching helper
# ---------------------------------------------------------------------------

def _find_col(headers: list[str], keyword: str) -> Optional[int]:
    """Return index of first header containing keyword (case-insensitive).
    
    Handles multi-line cells by extracting last line (after split on '\n').
    """
    def clean_cell(cell: str | None) -> str:
        if cell is None or not isinstance(cell, str):
            return ""
        if '\n' in cell:
            return cell.split('\n')[-1].strip()
        return cell.strip()
    
    kw = keyword.lower()
    for i, h in enumerate(headers):
        if kw in clean_cell(h).lower():
            return i
    return None


# ---------------------------------------------------------------------------
# YouTrip parser
# ---------------------------------------------------------------------------

def _parse_youtrip(pdf_path: Path, verbose: bool = False) -> list[dict]:
    """
    Parse a YouTrip PDF statement using word-level extraction.

    pdfplumber's table detection misses ~half the transactions because alternating
    rows share borders and get merged or skipped. Instead we read all words,
    group them into transaction blocks by the y-position of the date column,
    then reconstruct each transaction from fixed x-coordinate columns:
      x≈28–90   Date line (e.g. '2 Dec 2025') and time line below it
      x≈143+    Description lines
      x≈360–410 Money Out amount
      x≈360–410 Money In amount (same x-range, non-empty on refund/top-up rows)
      x≈500+    Balance

    Refund handling: rows starting with "Refund:" in description are matched to
    the original charge by transaction code (A-XXXXXXX), and both are dropped.

    Returns list of {date, raw_description, cost_sgd} with refunded transactions excluded.
    """
    import re as _re

    # x-coordinate buckets (from empirical observation of word positions)
    _X_DATE_MAX = 110       # date and time words sit left of this
    _X_DESC_MIN = 130       # description words sit right of this
    _X_AMOUNT_MIN = 355     # money out: x≈376-382; money in (refunds/top-ups): x≈451
    _X_AMOUNT_MAX = 490     # extended to cover money_in column at x≈451
    _X_BALANCE_MIN = 495    # balance sits right of this — we ignore it

    def is_date_line(words: list) -> bool:
        """True if this group of words looks like a date: '2 Dec 2025'."""
        text = " ".join(w["text"] for w in words)
        return bool(_re.match(r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$", text.strip()))

    def words_to_text(words: list) -> str:
        return " ".join(w["text"] for w in words)

    def extract_txn_code(text: str) -> Optional[str]:
        m = _re.search(r"\bA-[A-Z0-9]{10,}\b", text)
        return m.group(0) if m else None

    expense_rows: list[dict] = []
    refund_codes: set[str] = set()
    refund_amounts: list[float] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            words = page.extract_words()
            if not words:
                continue

            # Bucket each word into its column by x position
            # Group words into lines by y (tolerance ±3pt)
            lines: list[list[dict]] = []
            for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
                if lines and abs(w["top"] - lines[-1][0]["top"]) <= 3:
                    lines[-1].append(w)
                else:
                    lines.append([w])

            # Find transaction blocks.
            #
            # YouTrip PDF layout quirk: the merchant name line appears one row
            # ABOVE the date+amount line in the PDF, not inside the same bordered
            # cell as seen visually.  Word-level layout (confirmed via debug_pdf.py
            # --words) shows e.g.:
            #
            #   y=298  x=143  "SmartExchange™"      ← desc col, no date col
            #   y=304  x=38   "2 Dec 2025"  x=376 "$18.00"   ← date + amount
            #   y=312  x=143  "$18.00 SGD to $13.87 USD"     ← desc detail
            #   y=326  x=143  "FX rate: ..."                 ← filtered out
            #   y=349  x=143  "SmartExchange™"      ← merchant name of NEXT block
            #   y=355  x=38   "3 Dec 2025"  x=376 "$17.82"
            #
            # Strategy:
            #  - Lines before the first date line: track the last desc-only line
            #    as a pending merchant name.
            #  - When a date line is found and there is an existing block: if the
            #    last line of that block is desc-only and not an FX-rate line,
            #    it belongs to the NEW block (it is its merchant name) — pop it.
            #  - Otherwise use the pending pre-first-block desc line.
            blocks: list[list[list[dict]]] = []
            current_block: list[list[dict]] = []
            pending_merchant: list[dict] | None = None  # desc-only line before first date

            def _is_desc_only_line(ln: list[dict]) -> bool:
                """True if all words are in the description column (no date-col words)."""
                has_desc = any(w["x0"] >= _X_DESC_MIN for w in ln)
                has_date = any(w["x0"] < _X_DATE_MAX for w in ln)
                first_desc_text = next(
                    (w["text"] for w in sorted(ln, key=lambda w: w["x0"])
                     if w["x0"] >= _X_DESC_MIN), ""
                )
                is_fx = first_desc_text.lower().startswith("fx")
                return has_desc and not has_date and not is_fx

            for line in lines:
                date_words = [w for w in line if w["x0"] < _X_DATE_MAX]
                if date_words and is_date_line(date_words):
                    merchant_line: list[dict] | None = None
                    if current_block:
                        # The last desc-only line of the current block is actually
                        # the merchant name for this new transaction.
                        if _is_desc_only_line(current_block[-1]):
                            merchant_line = current_block.pop()
                        blocks.append(current_block)
                    else:
                        # First transaction: use the pre-block pending line.
                        merchant_line = pending_merchant
                    current_block = []
                    if merchant_line is not None:
                        current_block.append(merchant_line)
                    current_block.append(line)
                    pending_merchant = None
                elif current_block:
                    current_block.append(line)
                else:
                    # Before any block starts — track the last desc-only line
                    # in case it is the merchant name for the first transaction.
                    if _is_desc_only_line(line):
                        pending_merchant = line

            if current_block:
                blocks.append(current_block)

            if verbose:
                print(f"    [debug] Page {page_num}: {len(blocks)} transaction block(s) from word extraction")

            for block in blocks:
                # Collect words by column across all lines in the block.
                # date_words_all: only from the FIRST line that matches the date
                # pattern — subsequent lines with x<110 are time stamps, footnote
                # numbers, or footer text (e.g. "Remarks: 1. Pending...") that
                # would corrupt the date string if included.
                date_words_all: list[dict] = []
                desc_words_all: list[dict] = []
                amount_words: list[dict] = []

                date_line_found = False
                for line in block:
                    for w in line:
                        if w["x0"] < _X_DATE_MAX:
                            # Only collect date-column words from the actual date line
                            if not date_line_found:
                                date_col_words = [x for x in line if x["x0"] < _X_DATE_MAX]
                                if is_date_line(date_col_words):
                                    date_words_all = date_col_words
                                    date_line_found = True
                        elif _X_AMOUNT_MIN <= w["x0"] <= _X_AMOUNT_MAX:
                            amount_words.append(w)
                        elif w["x0"] >= _X_BALANCE_MIN:
                            pass  # balance — ignore
                        elif w["x0"] >= _X_DESC_MIN:
                            desc_words_all.append(w)

                # Parse date — filter out time words (HH:MM and AM/PM)
                date_line_words = [w for w in date_words_all if not _re.match(r"^\d{1,2}:\d{2}$", w["text"]) and w["text"] not in ("AM", "PM")]
                date_str = words_to_text(date_line_words)
                parsed_date = _parse_date(date_str)
                if parsed_date is None:
                    continue

                # Build description: all desc words except FX rate lines
                desc_lines_sorted = sorted(desc_words_all, key=lambda w: (round(w["top"]), w["x0"]))
                desc_by_y: list[list[dict]] = []
                for w in desc_lines_sorted:
                    if desc_by_y and abs(w["top"] - desc_by_y[-1][0]["top"]) <= 3:
                        desc_by_y[-1].append(w)
                    else:
                        desc_by_y.append([w])

                desc_parts = []
                for dl in desc_by_y:
                    txt = words_to_text(dl)
                    if txt.lower().startswith("fx rate:"):
                        continue
                    desc_parts.append(txt)
                desc = " / ".join(desc_parts).strip()

                if not desc:
                    continue

                # Classify the row before checking amounts — refunds have money_in
                # (x≈451) not money_out (x≈376), so parsed_amounts might be empty
                # for Top Up rows; we still need to record refund codes.
                is_refund = desc.lower().startswith("refund:")
                is_top_up = bool(_re.match(r"^top.?up", desc.lower()))

                if is_top_up:
                    if verbose:
                        print(f"      skipped  {parsed_date} (top up)")
                    continue

                # Separate money_out (x≈355-430) from money_in (x≈431-490)
                _X_MONEY_IN_MIN = 431
                money_out_words = [w for w in amount_words if w["x0"] < _X_MONEY_IN_MIN]
                money_in_words  = [w for w in amount_words if w["x0"] >= _X_MONEY_IN_MIN]

                money_out = next(
                    (v for w in sorted(money_out_words, key=lambda w: w["top"])
                     if (v := _parse_amount(w["text"])) is not None), None
                )
                money_in = next(
                    (v for w in sorted(money_in_words, key=lambda w: w["top"])
                     if (v := _parse_amount(w["text"])) is not None), None
                )

                if is_refund:
                    txn_code = extract_txn_code(" ".join(w["text"] for w in desc_words_all))
                    amount = money_in or money_out
                    if txn_code:
                        refund_codes.add(txn_code)
                    elif amount is not None:
                        refund_amounts.append(amount)
                    if verbose:
                        print(f"      refund   {parsed_date} {desc[:40]} code={txn_code}")
                    continue

                # Normal expense — must have money_out
                if money_out is None:
                    continue

                amount = money_out
                txn_code = extract_txn_code(" ".join(w["text"] for w in desc_words_all))

                expense_rows.append({
                    "date": parsed_date.isoformat(),
                    "raw_description": desc,
                    "cost_sgd": amount,
                    "_txn_code": txn_code,
                })
                if verbose:
                    print(f"      expense  {parsed_date} {desc[:40]} {amount} code={txn_code}")

    # Drop expenses that were refunded
    rows = []
    for r in expense_rows:
        txn_code = r.pop("_txn_code")
        if txn_code and txn_code in refund_codes:
            if verbose:
                print(f"    [debug] Cancelled (refunded by code {txn_code}): {r['raw_description'][:40]}")
            continue
        if txn_code is None and r["cost_sgd"] in refund_amounts:
            refund_amounts.remove(r["cost_sgd"])
            if verbose:
                print(f"    [debug] Cancelled (refunded by amount {r['cost_sgd']}): {r['raw_description'][:40]}")
            continue
        rows.append(r)

    return rows


# ---------------------------------------------------------------------------
# UOB parser
# ---------------------------------------------------------------------------

def _parse_uob(pdf_path: Path, verbose: bool = False) -> list[dict]:
    """
    Parse a UOB credit card PDF statement.
    Expected columns: Post Date | Trans Date | Description of Transaction | Transaction Amount SGD
    Returns list of {date, raw_description, cost_sgd}.
    """
    rows = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            table = page.extract_table()
            if not table:
                if verbose:
                    print(f"    [debug] Page {page_num}: no table found")
                continue
            if verbose:
                print(f"    [debug] Page {page_num}: table found with {len(table)} rows")

            # Find header row — contains "trans date" or "description of transaction"
            header_idx = None
            for i, row in enumerate(table):
                if row and any("trans date" in (c or "").lower() for c in row):
                    header_idx = i
                    break
            if header_idx is None:
                if verbose:
                    print(f"    [debug] Page {page_num}: no header row found. First 3 rows:")
                    for i, row in enumerate(table[:3]):
                        print(f"      Row {i}: {row}")
                continue

            headers = table[header_idx]
            if verbose:
                print(f"    [debug] Page {page_num}: header at row {header_idx}: {headers}")
            col_trans_date = _find_col(headers, "trans date")
            col_desc = _find_col(headers, "description")
            col_amount = _find_col(headers, "transaction amount")

            if any(c is None for c in [col_trans_date, col_desc, col_amount]):
                if verbose:
                    print(f"    [debug] Page {page_num}: column detection failed:")
                    print(f"      col_trans_date={col_trans_date}, col_desc={col_desc}, col_amount={col_amount}")
                continue

            for row_num, row in enumerate(table[header_idx + 1:], 1):
                if not row or len(row) <= max(col_trans_date, col_desc, col_amount):
                    continue

                date_str = row[col_trans_date] or ""
                desc = (row[col_desc] or "").strip()
                amount_str = row[col_amount] or ""

                parsed_date = _parse_date(date_str)
                amount = _parse_amount(amount_str)

                if parsed_date is None or amount is None or not desc:
                    if verbose and row_num <= 3:
                        print(f"    [debug] Page {page_num}, row {row_num}: skipped")
                        print(f"      date_str={repr(date_str)} → {parsed_date}")
                        print(f"      amount_str={repr(amount_str)} → {amount}")
                        print(f"      desc={repr(desc[:50] if desc else '')}")
                    continue

                rows.append({
                    "date": parsed_date.isoformat(),
                    "raw_description": desc,
                    "cost_sgd": amount,
                })

    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_pdf(
    pdf_path: Path,
    statement_type: Optional[str] = None,
    verbose: bool = False,
) -> tuple[str, list[dict]]:
    """
    Parse a PDF bank/wallet statement.

    Args:
        pdf_path:       Path to the PDF file.
        statement_type: "youtrip" or "uob". Auto-detected if None.
        verbose:        Print debug info during parsing (table/header/column detection).

    Returns:
        (statement_type, rows) where rows is a list of:
            {"date": str, "raw_description": str, "cost_sgd": float}
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if statement_type is None:
        statement_type = detect_statement_type(pdf_path)
    else:
        statement_type = statement_type.lower()
        if statement_type not in ("youtrip", "uob"):
            raise ValueError(f"Unknown statement type '{statement_type}'. Use 'youtrip' or 'uob'.")

    if statement_type == "youtrip":
        rows = _parse_youtrip(pdf_path, verbose=verbose)
    else:
        rows = _parse_uob(pdf_path, verbose=verbose)

    return statement_type, rows


def filter_by_date(
    rows: list[dict],
    from_date: Optional[date],
    to_date: Optional[date],
) -> list[dict]:
    """Drop rows outside [from_date, to_date]. None means no bound."""
    if from_date is None and to_date is None:
        return rows
    result = []
    for row in rows:
        d = date.fromisoformat(row["date"])
        if from_date and d < from_date:
            continue
        if to_date and d > to_date:
            continue
        result.append(row)
    return result
