## Plan: Telegram `#exp` → CSV via Hermes Skill

**TL;DR:** Hermes Agent's gateway watches a Telegram channel for posts containing `#exp`. A Hermes skill extracts the expense from free-form text using the LLM, normalizes and tags it via existing pipeline modules, appends a row to a dated CSV, and DMs you a confirmation. Notion is scoped out to a later milestone.

---

### Phase 1 — Hermes Gateway & Channel Setup
1. Run `hermes gateway setup` to configure the bot token and connect to the channel. Bot must be added as **admin** to receive `channel_post` updates.
2. Verify `channel_post` updates are received — may need `allowed_updates: ["channel_post"]` in Hermes gateway config. If Hermes doesn't support this natively, fallback is a thin `python-telegram-bot` listener (~30 lines) that delegates to the same Phase 3 script.

### Phase 2 — Hermes Skill (`~/.hermes/skills/expense-extractor/SKILL.md`)
3. Create the skill file that instructs Hermes:
   - **Trigger**: any incoming channel post containing `#exp`
   - **Extract** from full message text: merchant name, amount, currency code (default `SGD` if absent)
   - **Call** `src/telegram_bot_writer.py` with extracted fields as arguments
   - **Reply via DM** to the channel owner: `✓ Logged: Grab · transport · 12.90 SGD`
   - On parse failure: stay silent, log to stderr

### Phase 3 — CSV Writer (`src/telegram_bot_writer.py`)
4. Accepts parsed fields (name, amount, currency) as JSON stdin or CLI args
5. Reuses `normalize_merchant.normalize()` from normalize_merchant.py
6. Reuses `tag_merchant.tag()` from tag_merchant.py + merchant_rules.json
7. Applies schema logic:
   - SGD entries: `amount=X, currency=SGD, cost_sgd=X`
   - Foreign entries: `amount=X, currency=USD, cost_sgd=` _(blank)_
8. Appends row to `output/expenses_telegram_DDMMYY.csv` with headers: `name, tags, amount, currency, cost_sgd`

### Phase 4 — Config
9. Create `config/expense_bot.yaml` with: CSV output directory, channel owner Telegram user ID (for DM replies)
10. Add bot token to .env as `TELEGRAM_BOT_TOKEN` if not already set by Hermes

---

**Relevant files**
- normalize_merchant.py — reuse `normalize()`, no changes
- tag_merchant.py — reuse `tag()`, no changes
- merchant_rules.json — no changes
- tags.json — no changes
- prompt.md — reference for extraction rules to mirror in the skill

**Verification**
1. Send `stopped by ntuc for groceries, spent 45.20 #exp` → expect row: `NTUC Fairprice · essentials · 45.20 · SGD · 45.20`
2. Send `paid 12.90 USD for Agoda #exp` → expect row: `Agoda · accomms · 12.90 · USD · _(blank)_`
3. Send a post without `#exp` → confirm nothing happens
4. Confirm DM confirmation arrives with correct logged entry text
5. Run `python src/telegram_bot_writer.py` in isolation with mock input to unit-test normalize + tag + write

**Decisions**
- Existing pipelines keep old `cost / cost(sgd)` schema untouched
- Notion deferred — documented, not built yet
- Confirmation via DM (not channel reply) for privacy
- FX conversion for `cost_sgd` on foreign entries: fill manually later

**Deferred (Notion milestone)**
- `src/notion_writer.py`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`
- Notion DB properties: Name, Tags, Amount, Currency, Cost SGD, Date, Source