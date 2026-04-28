# PDF Parsing — Technical Notes

A record of non-obvious problems encountered building the YouTrip PDF parser,
their root causes, how they were solved, and what to watch out for.

---

## 1. Alternating-Row Table Detection (the core problem)

### What happened
Running `extract_tables()` on YouTrip PDFs returned only ~57% of transactions.
On page 1 with 7 visible transactions, only 4 were detected.

### Root cause
YouTrip uses a striped table design — every other row has a light-grey background,
alternating with white rows. pdfplumber's table detector works by finding rectangular
fill regions and border lines in the PDF vector layer. White rows have no fill and share
their borders with the rows above and below them — pdfplumber cannot distinguish them
from empty page space.

```
y=304  2 Dec  $18.00   ← SHADED row  →  detected as Table 0
y=355  3 Dec  $17.82   ← WHITE row   →  completely invisible to extract_tables()
y=406  3 Dec  $34.74   ← SHADED row  →  detected as Table 1
y=457  5 Dec   $2.57   ← WHITE row   →  completely invisible to extract_tables()
y=522  5 Dec  $22.76   ← SHADED row  →  detected as Table 2
y=587  5 Dec   $0.94   ← WHITE row   →  completely invisible to extract_tables()
y=653  5 Dec   $5.50   ← SHADED row  →  detected as Table 3
```

### Solution
Abandoned `extract_tables()` entirely. Switched to `page.extract_words()`, which
returns every word on the page regardless of background fill or border presence.
Transactions are reconstructed by grouping words by y-position (±3pt tolerance) into
lines, then identifying transaction block boundaries by looking for a date pattern
(`\d{1,2} Mon YYYY`) in the left-hand (date) column.

### Verification
`debug_pdf.py --words` shows raw word positions; `--blocks` overlays the word-based
block detection in green. Comparing the two makes the gap between table detection
and word-based detection immediately visible.

### Considerations
- `extract_tables()` and `extract_words()` are completely independent. Debug images
  showing "4 tables detected" are correct — that's showing pdfplumber's table layer.
  The parser doesn't use that layer at all.
- The reference implementation by James Allard (youtrip-statement-extraction on GitHub)
  uses a third approach: explicit coordinate mode, where balance-column regex matches
  are used to define horizontal row boundaries, then `extract_table()` is called with
  those explicit lines. That also solves the problem but requires per-page coordinate
  collection and has known description truncation issues.

---

## 2. Merchant Name Positioned Above the Date Line

### What happened
The first word-based implementation produced descriptions like `$18.00 SGD to $13.87 USD`
instead of `SmartExchange™ / $18.00 SGD to $13.87 USD`. The merchant name was missing.

### Root cause
In the raw PDF word layout, the merchant name (e.g. `SmartExchange™`) appears at a
y-position ~6px **above** the date+amount line. It is a description-column-only word with
no corresponding date-column word on the same y-coordinate.

```
y=298  x=143  "SmartExchange™"          ← desc col only — merchant of next transaction
y=304  x=38   "2 Dec 2025"  x=376 "$18.00"
y=312  x=143  "$18.00 SGD to $13.87 USD"
y=326  x=143  "FX rate: ..."
y=349  x=143  "SmartExchange™"          ← merchant of the FOLLOWING transaction
y=355  x=38   "3 Dec 2025"  x=376 "$17.82"
```

The merchant name for transaction N is actually the last line inside transaction N-1's
y-range, not the first line inside transaction N's range.

### Solution
Look-behind block detection: when a new date line is found, check if the last line of the
current (just-closed) block is a desc-only line (no date-column words, not an FX-rate
line). If so, pop it — it belongs to the new block as its merchant name. For the very
first transaction on each page, a `pending_merchant` variable tracks any desc-only line
that appeared before the first date line.

### Considerations
- This assumption holds for all pages in the Dec 2025 statement. If a future template
  moves the merchant name to the same y-level as the date, the look-behind would
  incorrectly attach the prior transaction's last desc line. Verify with `--words` on
  any new statement version.

---

## 3. Footer Text Bleeding into Date Column

### What happened
The last transaction on each page (e.g. `SmartExchange™ $5.50`) was silently dropped.
Page 1 reported 8 blocks but only 6 expenses.

### Root cause
Each page ends with a "Remarks:" footnote section. Several words in that section sit at
x<110 (the date column threshold): `Remarks:`, `1.`, `Pending`, `2.`, `Completed`, etc.
The original code collected **all** date-column words across every line in the block.
The last block on each page captured the footnote words, making the assembled date string
something like `5 Dec 2025 Remarks: 1. Pending 2. Completed` — which `_parse_date()`
correctly returns `None` for, causing the whole block to be silently skipped.

### Solution
Instead of collecting date-column words from all lines in a block, only collect them from
the **one line that actually matches the date pattern**. A `date_line_found` flag ensures
subsequent lines with x<110 (time words, footnote numbers) are not appended to
`date_words_all`.

```python
date_line_found = False
for line in block:
    for w in line:
        if w["x0"] < _X_DATE_MAX:
            if not date_line_found:
                date_col_words = [x for x in line if x["x0"] < _X_DATE_MAX]
                if is_date_line(date_col_words):
                    date_words_all = date_col_words
                    date_line_found = True
```

### Considerations
- The time line (`5:42 PM`, `11:53 PM`) also sits in the date column but at a different
  y-position. It is filtered at a later step by matching `\d{1,2}:\d{2}` and `AM`/`PM`.
  The `date_line_found` guard alone isn't sufficient — both guards are needed.

---

## 4. Refund Row Silent Skip (charge not cancelled)

### What happened
A `Grab* A-8NWJ56LG3CNMAV` charge of $27.17 was refunded. The refund row was absent
from the output (correct), but so was the original $27.17 charge (incorrect — it should
also be removed). The refund was being silently dropped before its transaction code was
ever recorded.

### Root cause
Two sub-issues compounded:

**Sub-issue A — Wrong x-range for money_in:**
Money Out sits at x≈376–382. Money In (used for refunds and top-ups) sits at x≈451 —
a different column. The original `_X_AMOUNT_MAX = 430` excluded money_in values entirely.
Since the refund row has no money_out, `parsed_amounts` was empty.

**Sub-issue B — Early bail-out before refund classification:**
The original code had:
```python
if not parsed_amounts:
    continue          # ← bailed here for refund rows
is_refund = desc.lower().startswith("refund:")
```
The `is_refund` check came after the guard, so the refund code was never added to
`refund_codes`, and the original charge survived into the output.

### Solution
1. Extend `_X_AMOUNT_MAX` to 490 to cover both money_out (x≈376–430) and money_in
   (x≈431–490).
2. Split amount words into `money_out_words` and `money_in_words` by a threshold at x=431.
3. Move `is_refund` and `is_top_up` classification **before** the amount guard.
4. For refund rows: record the transaction code into `refund_codes` regardless of whether
   an amount was parsed, then `continue`.
5. For normal expenses: only proceed if `money_out` is not None.

### Considerations
- The two-column split (money_out / money_in) is more semantically correct than a single
  bucket because it prevents a money_in value (Top Up, Refund) from being mistakenly
  treated as the expense amount.
- Refund matching has two modes: by transaction code (primary, exact) and by amount
  (fallback, for rows where no `A-XXXXXXX` code appears in the description). The fallback
  is unreliable if two different charges happen to have the same SGD amount — acceptable
  for personal use but worth noting.

---

## 5. FX Rate Lines in Descriptions

### What happened
Raw descriptions contained lines like:
```
SmartExchange™ / $18.00 SGD to $13.87 USD / FX rate: $1 SGD = $0.770555 USD
```
The FX rate line is noise — it's metadata about the exchange rate, not useful for
tagging or display.

### Root cause
YouTrip description cells are multi-line in the PDF. The last line is always the FX rate.
When word-based extraction collects all description-column words, it picks up every line
including the FX rate.

### Solution
After grouping description words back into lines by y-position, skip any line whose first
word starts with `"fx rate:"` (case-insensitive check).

```python
for dl in desc_by_y:
    txt = words_to_text(dl)
    if txt.lower().startswith("fx rate:"):
        continue
    desc_parts.append(txt)
```

### Considerations
- The FX detail line (`$18.00 SGD to $13.87 USD`) is kept in the description since it
  confirms the foreign currency amount, which can be useful for cost tracking.
- If you wanted only the merchant name in the description, you'd also strip lines starting
  with `$` or matching a currency amount pattern. Not done here — the extra context is
  considered useful.

---

## 6. Top Up Rows Included as Expenses

### What happened
YouTrip account top-up transactions (adding money to the wallet) appeared in the expense
output. A top-up of e.g. $50 would show as an expense.

### Root cause
Top-up rows have money_in populated and money_out empty. An earlier version of the parser
had fallback logic: if no money_out, use money_in. This made top-ups look like expenses.

### Solution
Top-up rows are detected by matching `^top.?up` (case-insensitive) against the
description. They are skipped before amount parsing.

```python
is_top_up = bool(re.match(r"^top.?up", desc.lower()))
if is_top_up:
    continue
```

Covers: `Top Up`, `Top-Up`, `TOPUP` variants.

---

## 7. SSL Certificate Error for Semantic Tagging Model

### What happened
`sentence-transformers` failed to download `paraphrase-MiniLM-L6-v2` from HuggingFace:
```
[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate
```
The pipeline crashed.

### Root cause
macOS system Python SSL certificates are not automatically updated. HuggingFace uses a
certificate chain that the system trust store couldn't verify. Not a code problem — a
local machine configuration issue.

### Solution
Catch `Exception` (not just `ImportError`) in `_load_model()` and return `None`. All
downstream callers (`_get_anchor_embeddings`, `_semantic_tag`) handle a `None` model by
skipping the semantic pass silently, falling through to keyword-only tagging.

```python
@lru_cache(maxsize=1)
def _load_model():
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(_MODEL_NAME)
    except ImportError as e:
        raise
    except Exception as e:
        print(f"    [warning] could not load semantic model ({type(e).__name__}: {str(e)[:80]}...)")
        print(f"    [warning] skipping semantic tagging pass, using keyword rules only")
        return None
```

### Considerations
- The fix for the cert issue itself (not the code workaround) is to run
  `/Applications/Python\ 3.x/Install\ Certificates.command` on macOS, or
  `pip install certifi && python -c "import ssl; ssl.create_default_context()"`.
- Keyword-only tagging is sufficient for common merchants (Grab, SmartExchange, hotel
  names). Semantic tagging would only help for novel/ambiguous merchant names.

---

## 8. x-Coordinate Column Constants — Stability and Limitations

### Overview
The word-based parser depends on hardcoded x-coordinate thresholds to bucket words into
columns:

| Constant | Value | Column | Empirical basis |
|---|---|---|---|
| `_X_DATE_MAX` | 110 | Date + time | Words at x≈38–68; time at x≈38–56 |
| `_X_DESC_MIN` | 130 | Description | Words at x≈143+ |
| `_X_AMOUNT_MIN` | 355 | Money Out | Words at x≈376–382 |
| `_X_MONEY_IN_MIN` | 431 | Money In split | Money In at x≈451 |
| `_X_AMOUNT_MAX` | 490 | Money In (upper) | Money In at x≈451; balance starts ≈495 |
| `_X_BALANCE_MIN` | 495 | Balance (ignored) | Words at x≈520 |

### Stability
These values are stable **within** a given YouTrip statement template. The PDF is
machine-generated from a fixed layout — column positions don't vary by account holder,
date, or transaction count. Every Dec 2025 statement will have identical x-positions.

### Risk
If YouTrip redesigns their statement layout (new template), these break silently —
transactions get misfiled or dropped without errors. No version marker is embedded in the
PDF that the parser could check.

### Mitigation
- `debug_pdf.py --words` gives a fast readout of all word x-positions on any page.
  Running it on the first page of a new statement takes <5 seconds and immediately
  reveals if columns have shifted.
- A more robust approach would auto-detect column positions from the header row words
  (find x-position of `"Out"`, `"In"`, `"Balance"` in the header line and derive
  thresholds from those). Not implemented — over-engineering for current use.
- These constants are **not portable to UOB**. UOB will have completely different values
  and requires its own set.

---

## 9. `extract_table()` vs `extract_tables()` vs `extract_words()`

Three pdfplumber APIs were tried in sequence on this project:

| API | Returns | YouTrip result |
|---|---|---|
| `page.extract_table()` | First table on page only | 1 transaction/page (~10 total) |
| `page.extract_tables()` | All tables on page | 4 of 7 transactions/page (~35 total) |
| `page.extract_words()` | All words on page | All 7 transactions/page (~70 total) |

The progression maps directly to the three discovery phases of this project. Only
`extract_words()` is immune to the alternating-row shading problem because it operates
on the text layer, not the vector/border layer.
