# tele-expense-tracking

Extracts expenses from a Telegram channel export and outputs a CSV ready for manual import into Notion.

**Telegram pipeline:** Telegram JSON export → candidate filter → LLM extraction (OpenRouter) → validation → `expenses_telegram_DDMMYY.csv`

**PDF pipeline:** YouTrip / UOB credit card PDF statement → parse → date filter → normalize → tag → `expenses_<type>_MMYYYY.csv`

---

## Setup

```bash
# Clone and enter the project
git clone <repo-url>
cd tele-expense-tracking

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure your API key
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY
```

---

## Usage

### Telegram pipeline

**Pilot run** (first 10 candidates — recommended before a full run):
```bash
python src/main.py --input data/result_080426.json --pilot 10
```

**Full run:**
```bash
python src/main.py --input data/result_080426.json
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--input` | *(required)* | Path to raw Telegram JSON export |
| `--pilot N` | `0` (all) | Process only first N expense candidates |
| `--output-dir` | `output/` | Directory for all outputs |
| `--config-dir` | `config/` | Directory for `tags.json` and `prompt.md` |

If a run is interrupted, re-running the same command will **resume from the last completed batch** automatically.

---

### PDF pipeline

Parses YouTrip or UOB credit card PDF statements into the same expense CSV format — no LLM required.

**Basic run (statement type auto-detected):**
```bash
python src/pdf_main.py --input data/youtrip_apr2026.pdf
```

**With date range** (to extract only trip-relevant transactions from a monthly statement):
```bash
python src/pdf_main.py --input data/uob_may2026.pdf --from 2026-04-01 --to 2026-04-15
```

**Manual type override** (if auto-detection fails):
```bash
python src/pdf_main.py --input data/statement.pdf --type uob
```

**With LLM fallback** (sends rows that keyword + semantic passes couldn't tag to OpenRouter):
```bash
python src/pdf_main.py --input data/uob_may2026.pdf --llm-tags
```

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--input` | *(required)* | Path to the PDF statement |
| `--type` | *(auto-detected)* | `youtrip` or `uob` — override auto-detection |
| `--from` | *(none)* | Include transactions on or after this date (`YYYY-MM-DD`) |
| `--to` | *(none)* | Include transactions on or before this date (`YYYY-MM-DD`) |
| `--output-dir` | `output/` | Directory for output files |
| `--config-dir` | `config/` | Directory containing `merchant_rules.json` |
| `--llm-tags` | off | Send untagged rows to OpenRouter LLM for a final classification pass |

**How it works:**

1. **Auto-detect** — scans the first page for `"YouTrip"` or `"United Overseas Bank"` to determine the statement type
2. **Parse** — uses `pdfplumber` to extract the transactions table; locates the header row (containing "Description") and skips everything above it (account info, statement period, etc.); rows that don't parse as a valid date + amount are dropped automatically (totals, blank lines)
3. **Date filter** — if `--from`/`--to` are given, drops rows outside that range
4. **Normalize** — cleans raw merchant strings (`"GRAB*GRABSH1234567"` → `"Grab"`, `"AGODA.COM SG 12345"` → `"Agoda"`) by stripping transaction codes, domain suffixes, and location noise
5. **Tag** — three-pass hybrid:
   - **Pass 1 – Keyword rules**: substring match against `config/merchant_rules.json`. Fast and exact. Catches known merchants and explicit category words.
   - **Pass 2 – Semantic similarity**: embeds the merchant name with `paraphrase-MiniLM-L6-v2` and compares against per-tag anchor phrases via cosine similarity. Catches English-meaning words with no keyword rule (e.g. `"buffet"` → food, `"tram"` → transport, `"clinic"` → essentials). First run triggers a one-time ~80 MB model download.
   - **Pass 3 – LLM** *(optional, `--llm-tags`)*: sends still-untagged rows to OpenRouter. Best for non-English merchant names with contextual clues. Rows that remain untagged after all passes are written to `pdf_untagged_<type>_MMYYYY.json`.

**Improving tag coverage:**

After the first run, check `output/pdf_untagged_*.json`. It lists every transaction that matched no keyword. Add new keywords to `config/merchant_rules.json` under the appropriate tag and re-run:

```json
{
  "food": ["hawker chan", "bengawan solo", ...],
  "transport": ["tada", ...]
}
```

**Tagging approach tradeoffs:**

| Merchant type | Example | Keyword rules | Semantic model | LLM |
|---|---|---|---|---|
| Known chain / brand | `GRAB*SH12345`, `AGODA` | ✅ | ✅ | ✅ |
| English-meaning word, no rule | `"Buffet"`, `"Tram"`, `"Clinic"` | ❌ | ✅ | ✅ |
| Local brand, added to rules | `XanhSM` (transport) | ✅ after adding | ❌ | ✅ |
| Non-English opaque name with context | `PAYOO-VUACHACA-CS1` (food) | ❌ | ❌ | ✅ (can reason) |
| Truly undecodable abbreviation | `CTTNHH 1986 VIET NAM` | ❌ correct blank | ❌ correct blank | ❌ correct blank |

The recommended workflow is: keyword + semantic first (free, offline, instant), then add `--llm-tags` only if untagged coverage matters for that particular run. Opaque local-language codes will always have some irreducible blank rate regardless of approach.

---

## Project structure

```
tele-expense-tracking/
│
├── src/
│   ├── main.py                   # Telegram pipeline entry point
│   ├── parse_export.py           # Stage 1: parse Telegram JSON → normalized JSONL
│   ├── filter_candidates.py      # Stage 2: filter likely expense messages
│   ├── extract_expenses.py       # Stage 3: batch LLM extraction via OpenRouter
│   ├── validate_and_write_csv.py # Stage 4: validate + write final CSV
│   │
│   ├── pdf_main.py               # PDF pipeline entry point
│   ├── parse_pdf.py              # PDF parsing: auto-detect + YouTrip/UOB parsers
│   ├── normalize_merchant.py     # Clean raw merchant strings into readable names
│   └── tag_merchant.py           # Keyword rules + fuzzy fallback tagging
│
├── config/
│   ├── tags.json                 # Allowed expense tags (used by Telegram pipeline)
│   ├── merchant_rules.json       # Keyword → tag map (used by PDF pipeline)
│   └── prompt.md                 # System prompt sent to the LLM
│
├── output/                       # Generated at runtime (gitignored except committed samples)
│
├── data/                         # ⚠️ gitignored — place your exports/PDFs here
│
├── .env.example                  # Copy to .env and fill in your API key
├── requirements.txt
└── .gitignore
```

---

## The `data/` folder

The `data/` folder is gitignored because it contains a private Telegram channel export. To run the pipeline, place your export JSON here:

```
data/
└── result_080426.json    # filename format: result_DDMMYY.json
```

To export from Telegram Desktop:
1. Open the channel → ⋯ menu → **Export chat history**
2. Uncheck media/files — text only is sufficient
3. Export format: **JSON**
4. Copy the resulting `result.json` into `data/` and rename it

---

## Intermediate output files

These are written to `output/` during a run and are gitignored. They are useful for debugging which stage produced a problem.

### Telegram pipeline

| File | Stage | Description |
|---|---|---|
| `normalized_messages.jsonl` | Stage 1 | One record per text-bearing message: `{message_id, timestamp, text}`. Reply messages have their parent's text prepended as context. |
| `candidate_messages.jsonl` | Stage 2 | Subset of normalized messages that passed the expense-signal filter (contains a number or a keyword like `grab`, `hotel`, `lunch`, etc.). |
| `extracted_expenses.json` | Stage 3 | LLM output — one record per candidate message with an `expenses[]` array. Messages with no detected expense have an empty array. |
| `extracted_expenses_checkpoint.json` | Stage 3 | Temporary checkpoint written after each batch. Used to resume an interrupted run. Automatically deleted on successful completion. |
| `rejected_rows.json` | Stage 4 | Expenses that failed validation (unknown tag, both cost columns filled, negative amount, etc.), with rejection reasons. |
| `expenses_telegram_DDMMYY.csv` | Stage 4 | **Final output.** Columns: `name`, `tags`, `cost`, `cost(sgd)`. |

### PDF pipeline

| File | Description |
|---|---|
| `expenses_youtrip_MMYYYY.csv` | Final expense output for a YouTrip statement. |
| `expenses_uob_MMYYYY.csv` | Final expense output for a UOB credit card statement. |
| `pdf_untagged_<type>_MMYYYY.json` | Transactions that matched no keyword rule. Review and add to `config/merchant_rules.json`. |

---

## Output CSV format

```csv
name,tags,cost,cost(sgd)
Grab Ride,transport,,12.9
Museum Tickets,"entertainment, travel",25,
NTUC Groceries,"food, essentials",,45.2
Hotel Check-In,accomms,,0
```

- `cost` — filled when the amount was in a foreign/local non-SGD currency
- `cost(sgd)` — filled when the amount was in SGD
- A row with both cost columns empty (`cost=0`) means an expense was detected but no amount was stated — flagged for manual review

Import into Notion via **database menu → Merge with CSV**.

---

## Allowed tags

Defined in `config/tags.json`:

| Tag | Covers |
|---|---|
| `accomms` | Hotels, hostels, Airbnb |
| `transport` | Grab, taxi, bus, MRT, flights |
| `food` | Meals, drinks, cafes |
| `entertainment` | Museums, shows, activities |
| `essentials` | Groceries, pharmacy, SIM cards |
| `souvenirs` | Gifts, shopping |
| `travel` | Flights, airport transfers, cross-border |

---

## Environment variables

| Variable | Description |
|---|---|
| `OPENROUTER_API_KEY` | Your OpenRouter API key — get one at [openrouter.ai](https://openrouter.ai) |
| `OPENROUTER_MODEL` | Model to use (default: `mistralai/mistral-7b-instruct:free`) |
