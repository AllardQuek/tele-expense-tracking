Great — here’s the **task-board version** of the plan, stripped down and practical.

## Milestone 1

Set up the `expenses` Hermes profile so it has its own config, bot token, sessions, memory, and gateway state. 

### Tasks
- Create profile: `hermes profile create expenses`. 
- Run profile setup or manually edit:
  - `~/.hermes/profiles/expenses/config.yaml`
  - `~/.hermes/profiles/expenses/.env`
  - `~/.hermes/profiles/expenses/SOUL.md`. 
- Put the Telegram bot token in the profile’s `.env`. 
- Optionally set `terminal.cwd` to your expense project directory if you want predictable tool execution. 

### Files
- `~/.hermes/profiles/expenses/config.yaml`
- `~/.hermes/profiles/expenses/.env`
- `~/.hermes/profiles/expenses/SOUL.md`

### Done criteria
- `expenses chat` works. 
- `expenses gateway start` works. 
- The bot runs independently from your default Hermes profile. 

## Milestone 2

Create the plugin skeleton and enable it only for the `expenses` profile. 

### Tasks
- Create plugin folder:
```text
~/.hermes/plugins/expense-tracker/
```
- Add:
```text
plugin.yaml
__init__.py
```
- In `plugin.yaml`, define:
  - plugin name
  - version
  - description. 
- In `__init__.py`, add `register(ctx)`.
- Register placeholder slash commands with `ctx.register_command(...)`:
  - `set-tracker`
  - `set-currency`
  - `set-city`
  - `x`. 
- Enable the plugin in the `expenses` profile `config.yaml` under `plugins.enabled`. 

### Files
- `~/.hermes/plugins/expense-tracker/plugin.yaml`
- `~/.hermes/plugins/expense-tracker/__init__.py`
- `~/.hermes/profiles/expenses/config.yaml`

### Done criteria
- Hermes discovers the plugin. 
- The plugin is enabled in `expenses` only. 
- `/set-tracker` and `/x` are recognized, even if they only return placeholder responses at first. 

## Milestone 3

Implement persistent tracker state under the `expenses` profile home so command behavior survives restarts. 

### Tasks
- Create a profile-local data directory, for example:
```text
~/.hermes/profiles/expenses/expense-data/
```
- Add:
```text
trackers.yaml
output/
```
- Store:
  - active tracker
  - tracker CSV path
  - default currency
  - default city
- Write helper functions:
  - load state
  - save state
  - create tracker if missing
  - set active tracker
  - update tracker defaults

### Files
- `~/.hermes/plugins/expense-tracker/state.py`
- `~/.hermes/profiles/expenses/expense-data/trackers.yaml`

### Done criteria
- `/set-tracker Japan-2026` creates/selects a tracker.
- `/set-currency JPY` persists.
- `/set-city Tokyo` persists.
- Restarting the gateway keeps these values. 

## Milestone 4

Implement CSV creation and append logic.

### Tasks
- Define the canonical CSV header:
```csv
date,city,name,tags,amount,currency,amount_sgd
```
- Write a CSV writer module that:
  - creates the file if missing
  - writes headers once
  - appends rows in the same order
- Make sure optional fields can be blank.

### Files
- `~/.hermes/plugins/expense-tracker/csv_writer.py`

### Done criteria
- New tracker creation also creates a valid CSV file.
- Appending a row works reliably.
- No duplicate header rows appear.

## Milestone 5

Implement `/set-tracker`, `/set-currency`, and `/set-city` properly.

### Tasks
- Replace placeholder handlers with real ones.
- Validate arguments:
  - tracker name not empty
  - currency normalized to uppercase
  - city stored as free text
- Return short confirmation messages:
  - active tracker set
  - default currency set
  - default city set

### Files
- `~/.hermes/plugins/expense-tracker/commands.py`
- `~/.hermes/plugins/expense-tracker/__init__.py`

### Done criteria
- All three commands update saved state.
- Replies are clear and deterministic.
- State changes are visible immediately.

## Milestone 6

Implement `/x` v1 as a deterministic expense logger.

### Tasks
- Write a parser for simple command text.
- Parse:
  - amount
  - optional explicit currency
  - description/name
  - optional tags
- Use tracker defaults for:
  - currency if omitted
  - city if omitted
- Use current date automatically.
- Append parsed row to active tracker CSV.

### Suggested v1 supported forms
- `/x 12 coffee`
- `/x 1200 jpy ramen`
- `/x 18.5 taxi`
- `/x 30 lunch #food #friends`

### Files
- `~/.hermes/plugins/expense-tracker/parser.py`
- `~/.hermes/plugins/expense-tracker/commands.py`

### Done criteria
- `/x 12 coffee` writes a valid row.
- `/x 1200 jpy ramen` overrides default currency.
- `/x 30 lunch #food` stores tags.
- If no active tracker exists, command fails safely.

## Milestone 7

Add context inspection commands for easier daily use.

### Tasks
- Add `/show-context`
- Optionally add `/list-trackers`

`/show-context` should return:
- active tracker
- CSV path
- default currency
- default city

### Files
- `~/.hermes/plugins/expense-tracker/commands.py`

### Done criteria
- You can see exactly where `/x` will write before logging.
- This reduces accidental writes to the wrong tracker.

## Milestone 8

Add `amount_sgd` support without blocking logging.

### Tasks
Choose v1 behavior:
- keep `amount_sgd` blank by default, or
- fill it only when explicit conversion logic exists

Recommended first version:
- keep column present
- leave blank unless conversion is available

Later options:
- exchange-rate lookup on write
- backfill script for historical rows

### Files
- `~/.hermes/plugins/expense-tracker/parser.py`
- `~/.hermes/plugins/expense-tracker/commands.py`
- optional future conversion module

### Done criteria
- Logging still works even when SGD conversion is unavailable.
- Original `amount` and `currency` are always preserved.

## Milestone 9

Add guardrails and cleanup.

### Tasks
- Add input validation for bad amounts/currencies.
- Add duplicate protection.
- Improve error messages.
- Decide whether to track source message metadata.

Possible duplicate strategy:
- save Telegram message ID in sidecar state
- or hash tracker + message text + timestamp

### Files
- `~/.hermes/plugins/expense-tracker/state.py`
- `~/.hermes/plugins/expense-tracker/commands.py`

### Done criteria
- Repeated messages do not silently duplicate.
- Bad input fails with a useful correction message.
- The system is safe enough for daily use.

## Recommended file layout

```text
~/.hermes/plugins/expense-tracker/
  plugin.yaml
  __init__.py
  commands.py
  state.py
  parser.py
  csv_writer.py

~/.hermes/profiles/expenses/
  config.yaml
  .env
  SOUL.md
  expense-data/
    trackers.yaml
    output/
      Japan-2026.csv
      Daily-2026.csv
```

## Build order

Follow this order:

1. Milestone 1: profile
2. Milestone 2: plugin skeleton
3. Milestone 3: persistent tracker state
4. Milestone 4: CSV writer
5. Milestone 5: tracker-setting commands
6. Milestone 6: `/x` logger
7. Milestone 7: context commands
8. Milestone 8: `amount_sgd`
9. Milestone 9: guardrails

## v1 success definition

You have a solid v1 once this sequence works end to end:

1. `/set-tracker Japan-2026`
2. `/set-currency JPY`
3. `/set-city Tokyo`
4. `/x 1200 ramen`
5. Row appears in `Japan-2026.csv` as:
   - current date
   - city = Tokyo
   - name = ramen
   - amount = 1200
   - currency = JPY
   - amount_sgd = blank or filled, depending on implementation

## Hermes-specific implementation notes

- Use a [**profile**](https://hermes-agent.nousresearch.com/docs/user-guide/profiles) for isolation.
- Use a [**plugin**](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins#what-plugins-can-do) for custom slash commands.
- Register commands with `ctx.register_command(name, handler, description)`.
- Enable the plugin explicitly in `plugins.enabled`.
- Store profile-scoped state relative to the active Hermes home, not a global fixed path.
