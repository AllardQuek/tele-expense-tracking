# tele-expense-tracking

Extracts expenses from a Telegram channel export and outputs a CSV ready for manual import into Notion.

**Pipeline:** Telegram JSON export → candidate filter → LLM extraction (OpenRouter) → validation → `expenses.csv`

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

## Project structure

```
tele-expense-tracking/
│
├── src/
│   ├── main.py                   # Entry point — runs all 4 stages in sequence
│   ├── parse_export.py           # Stage 1: parse Telegram JSON → normalized JSONL
│   ├── filter_candidates.py      # Stage 2: filter likely expense messages
│   ├── extract_expenses.py       # Stage 3: batch LLM extraction via OpenRouter
│   └── validate_and_write_csv.py # Stage 4: validate + write final CSV
│
├── config/
│   ├── tags.json                 # Allowed expense tags
│   └── prompt.md                 # System prompt sent to the LLM
│
├── output/                       # Generated at runtime (see below)
│   └── expenses.csv              # ✅ committed — final expense output
│
├── data/                         # ⚠️ gitignored — place your export here (see below)
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

These are written to `output/` during a run and are gitignored (except `expenses.csv`). They are useful for debugging which stage produced a problem.

| File | Stage | Description |
|---|---|---|
| `normalized_messages.jsonl` | Stage 1 | One record per text-bearing message: `{message_id, timestamp, text}`. Reply messages have their parent's text prepended as context. |
| `candidate_messages.jsonl` | Stage 2 | Subset of normalized messages that passed the expense-signal filter (contains a number or a keyword like `grab`, `hotel`, `lunch`, etc.). |
| `extracted_expenses.json` | Stage 3 | LLM output — one record per candidate message with an `expenses[]` array. Messages with no detected expense have an empty array. |
| `extracted_expenses_checkpoint.json` | Stage 3 | Temporary checkpoint written after each batch. Used to resume an interrupted run. Automatically deleted on successful completion. |
| `rejected_rows.json` | Stage 4 | Expenses that failed validation (unknown tag, both cost columns filled, negative amount, etc.), with rejection reasons. |
| `expenses.csv` | Stage 4 | **Final output.** Columns: `name`, `tags`, `cost`, `cost(sgd)`. Only one of the two cost columns is filled per row. |

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
