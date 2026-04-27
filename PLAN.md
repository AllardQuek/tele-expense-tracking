Yes — with source JSON already available, I’d build this as a small **offline extraction pipeline** with the LLM only responsible for structured expense extraction, and everything else deterministic. The cleanest v1 is: JSON in → candidate filtering → batched LLM extraction → validation → CSV out → manual Notion merge. [notion](https://www.notion.com/help/import-data-into-notion)

## Scope

Your target output is a CSV with exactly these columns:

- `name`
- `tags`
- `cost`
- `cost(sgd)`

Your allowed tags are fixed:

- `accomms`
- `transport`
- `entertainment`
- `food`
- `essentials`
- `souvenirs`
- `travel`

That fixed schema is a good fit for structured outputs because the model can be constrained to a small object shape and a limited tag set, which usually improves reliability. [digitalapplied](https://www.digitalapplied.com/blog/openai-structured-outputs-complete-guide)

## Pipeline

Build the project in six stages:

1. Read and normalize Telegram export JSON.
2. Filter likely expense candidates with deterministic rules.
3. Send candidates to the LLM in micro-batches.
4. Validate and repair outputs deterministically.
5. Write the final CSV.
6. Import the CSV into Notion manually with **Merge with CSV**. [resynced](https://resynced.io/blog/how-to-import-data-into-an-existing-notion-database)

This separation matters because structured output guarantees format, but not semantic correctness, so you still want validation after the model step. [mbrenndoerfer](https://mbrenndoerfer.com/writing/structured-outputs-schema-validated-data-extraction-language-models)

## Stage 1: Normalize JSON

Write a parser that extracts only the fields you need from the Telegram export:

- `message_id`
- `timestamp`
- `text`

Skip non-text messages (`type: "service"`) and photo-only messages (empty text after flattening). The Telegram export uses two `text` formats — either a plain string or an array of `{"type": "plain"|"link", "text": "..."}` objects — so the parser must flatten both into a single string.

Suggested normalized internal record:

```json
{
  "message_id": 12345,
  "timestamp": "2026-04-01T12:34:56+08:00",
  "text": "grab 12.90 to airport"
}
```

Keep this as an intermediate JSONL or in-memory list so you can reproduce results later without re-parsing the raw export.

## Stage 2: Candidate filter

Before calling the LLM, run a simple rule-based filter to reduce volume and noise. Examples:

- Keep messages containing a number.
- Boost messages containing likely merchant/category words like `grab`, `ntuc`, `taxi`, `hotel`, `lunch`, `dinner`.
- Exclude obvious non-expense patterns like reminders or URLs-only notes.

This should be **recall-first**, not precision-first: it is okay to send extra candidates to the model, but not okay to miss real expenses. The goal is just to avoid wasting calls on clearly irrelevant messages.

## Stage 3: LLM extraction

Use micro-batches of around 10 to 25 messages per call. Do **not** merge the text into a blob; instead pass an array of independent message objects and require per-message structured results. [getathenic](https://getathenic.com/blog/structured-output-patterns-ai-agents)

Input batch example:

```json
[
  {"message_id": 1, "text": "grab 12.90 to office"},
  {"message_id": 2, "text": "ntuc 45.20 groceries"},
  {"message_id": 3, "text": "museum 25 eur"}
]
```

Ask the model to return JSON only, with one result per message. A good extraction schema is:

```json
{
  "results": [
    {
      "message_id": 1,
      "expenses": [
        {
          "name": "Grab ride",
          "tags": ["transport"],
          "cost": null,
          "cost_sgd": 12.9
        }
      ]
    }
  ]
}
```

Rules for the prompt:

- Treat each message independently.
- Return zero expenses for non-expense messages.
- `tags` must only use the allowed list. [developers.openai](https://developers.openai.com/api/docs/guides/structured-outputs)
- Fill **only one** of `cost` or `cost_sgd` per expense — `cost_sgd` if the amount is in SGD, `cost` if the amount is in a foreign/local currency. Never fill both.
- If a message signals an expense but no amount is stated, include the item with both `cost` and `cost_sgd` as `null` (treated as a 0-cost review row for manual follow-up).
- Keep `name` short and human-readable.

## Stage 4: Validation

After every batch, run deterministic checks:

- `name` is non-empty.
- `tags` is a non-empty array and every tag is in the allowed list. [getathenic](https://getathenic.com/blog/structured-output-patterns-ai-agents)
- Exactly one of `cost` or `cost_sgd` is non-null and positive — or both are null (valid 0-cost review row).
- Both `cost` and `cost_sgd` are never simultaneously non-null.
- No duplicate expenses for the same `message_id` unless the text genuinely contains multiple expenses.

Also normalize:

- Deduplicate and sort tags.
- Convert `tags` array into CSV string form like `"transport, entertainment"`.
- Standardize capitalization in `name`.

Create a review bucket for records that fail validation, for example:

- unknown tag,
- both cost columns filled,
- negative amount,
- or extremely vague names like “item”.

Those rows can be re-run with a stricter prompt or reviewed manually. [digitalapplied](https://www.digitalapplied.com/blog/openai-structured-outputs-complete-guide)

## Stage 5: CSV generation

Do not ask the LLM to emit CSV directly. Generate CSV in code from the validated JSON because CSV quoting around comma-containing fields must be handled correctly. [inventivehq](https://inventivehq.com/blog/handling-special-characters-in-csv-files)

Final CSV rows should look like:

```csv
name,tags,cost,cost(sgd)
Grab ride,"transport",,12.9
Museum tickets,"entertainment, travel",25,
NTUC groceries,"food, essentials",,45.2
Hotel check-in,"accomms",,0
```

Only one of `cost` or `cost(sgd)` is filled per row. Zero-cost rows (missing amount but known expense type) appear in the CSV for manual review.

Use Python’s `csv` module or Pandas to write UTF-8 output with proper escaping. [support.blueconic](https://support.blueconic.com/en/articles/247710-best-practices-for-exchanging-data-via-comma-separated-values-csv-files)

## Stage 6: Notion import

For v1, import manually into your existing Notion database using **Merge with CSV** from the database menu. Match CSV headers to your existing database properties and verify that the tags field maps the way you want in Notion. [simonesmerilli](https://www.simonesmerilli.com/business/csv-import-notion)

One caveat: if your target Notion property for tags is multi-select, CSV imports can be a little finicky depending on how the target database is configured, so test with a small sample first. If manual merge behaves inconsistently, the fallback is a deterministic API importer later. [reddit](https://www.reddit.com/r/Notion/comments/1150mqa/import_csv_into_existing_notion_database/)

## Files and structure

A simple project layout:

```text
tele-expense-tracking/
  data/
    result_080426.json       ← raw Telegram export
  output/
    normalized_messages.jsonl
    candidate_messages.jsonl
    extracted_expenses.json
    rejected_rows.json
    expenses.csv
  src/
    parse_export.py
    filter_candidates.py
    extract_expenses.py
    validate_and_write_csv.py
    main.py
  config/
    tags.json
    prompt.md
  .env.example
  requirements.txt
```

Keep all intermediate artifacts. That makes it easy to debug whether a problem came from parsing, filtering, model extraction, or CSV formatting. [digitalapplied](https://www.digitalapplied.com/blog/openai-structured-outputs-complete-guide)

## Suggested prompt contract

Use a strict extraction contract like this:

- Input: array of message objects with `message_id` and `text`.
- Output: `results[]`, each containing:
  - `message_id`
  - `expenses[]`
- Each expense contains only:
  - `name`
  - `tags`
  - `cost` (foreign/local currency amount, or null)
  - `cost_sgd` (SGD amount, or null — never both non-null)

Prompt rules:

- Only extract real expenses.
- Ignore reminders, refunds, reimbursements, income, transfers, and non-spending notes unless you explicitly want them counted.
- Fill only one cost field per expense.
- If an expense is implied but no amount is stated, set both cost fields to null (not zero).
- Use only approved tags.
- Prefer fewer tags over too many.
- If unsure, return no expense rather than invent fields.

That last instruction is important because your stated priority is accuracy, not maximum recall. [mbrenndoerfer](https://mbrenndoerfer.com/writing/structured-outputs-schema-validated-data-extraction-language-models)

## QA plan

Before running the full dataset, do a 50-message pilot:

1. Run the parser.
2. Inspect normalized text.
3. Run candidate filtering.
4. Send 20 to 50 messages through the LLM.
5. Review extracted JSON and CSV manually.
6. Adjust prompt and tag rules.
7. Only then process the full export.

Measure:

- precision: how many extracted rows are truly expenses,
- miss rate: how many real expenses were skipped,
- tag consistency,
- and whether `cost_sgd` behavior is acceptable.

This small test pass is the cheapest way to improve quality before you scale. [getathenic](https://getathenic.com/blog/structured-output-patterns-ai-agents)

## Practical recommendations

My concrete v1 recommendations would be:

- Python for the whole pipeline.
- **OpenRouter free tier** for LLM calls — no subscription needed, just an API key. Model configurable via `.env` (e.g. `mistralai/mistral-7b-instruct:free`). Use direct HTTP calls (`requests`), not LangChain.
- JSON intermediate outputs everywhere.
- Micro-batch size: start with 20 messages.
- Use `--pilot 50` flag to test on first 50 candidates before full run.
- Manual Notion import first via **Merge with CSV**. [notion](https://www.notion.com/help/import-data-into-notion)
- Add automated Notion sync only after the CSV is consistently good.

If you want, I can turn this into a more actionable implementation spec next: exact prompt, JSON schema, validation rules, and a folder-by-folder build order.