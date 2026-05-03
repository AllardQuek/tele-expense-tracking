# Plan: PDF Statement Parsing Pipeline

## Context
- Existing pipeline: Telegram JSON → normalize → filter → LLM extract → validate → CSV
- Adding: PDF statement parsing for YouTrip and UOB credit card
- Output schema (same as existing): name, tags, cost, cost(sgd)

## User Decisions
- YouTrip + UOB One/Visa credit card
- UOB columns: "Completed Date (in SGT) | Description | Money Out | Money In | Balance"
- YouTrip columns: unknown — needs confirmation from sample PDF
- No LLM — fully offline rules-based pipeline
- Name normalization: rules-based cleanup only (strip codes, numbers, title-case)
- Tagging: hybrid — keyword rules first, fuzzy fallback (difflib) for unknowns
- Output: separate CSV per source (not merged with Telegram output)
- Filename convention: add date to filenames, differentiate by source
- Statement type detection: auto-detect from PDF text (preferred)

## New Files
- src/parse_pdf.py — PDF parsing + auto-detection
- src/normalize_merchant.py — name cleanup (strip codes, title-case)
- src/tag_merchant.py — keyword rules + fuzzy fallback
- src/pdf_main.py — new entry point for PDF pipeline
- config/merchant_rules.json — keyword → tags mapping (editable config)

## UOB Schema
- Money Out → cost_sgd (positive value)
- Money In → skip (refunds/payments) or flag
- Description → normalize + tag
- Completed Date → date field

## YouTrip Schema (CONFIRMED)
- Columns: Completed Date (in SGT) | Description | Money Out | Money In | Balance
- Money Out → cost_sgd; Money In → skip; Balance → skip
- Use "Completed Date (in SGT)" as date

## UOB Schema (CONFIRMED)
- Columns: Post Date | Trans Date | Description of Transaction | Transaction Amount SGD
- Use Trans Date as the transaction date
- Transaction Amount SGD → cost_sgd (all SGD, no currency column)
- Note: foreign currency amounts may appear embedded in Description text (to investigate)

## Tagging Approach
1. Strip and lowercase the cleaned merchant name
2. Check each keyword in merchant_rules.json against the name (substring match)
3. If no match: use difflib.get_close_matches() against all rule keywords
4. If still no match: leave tags empty / flag for manual review

## Output Filenames
- expenses_telegram_DDMMYY.csv (existing pipeline, rename)
- expenses_youtrip_MMYYYY.csv
- expenses_uob_MMYYYY.csv
- Date extracted from PDF content (statement period) or run date fallback

## Phases
1. parse_pdf.py — auto-detect + parse YouTrip/UOB
2. normalize_merchant.py — name cleanup
3. tag_merchant.py — hybrid tagging
4. pdf_main.py — orchestration
5. config/merchant_rules.json — seed keyword rules
6. (optional) update main.py filename to include date
