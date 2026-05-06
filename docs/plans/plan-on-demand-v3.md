## Architecture

Use:
- one Hermes **profile** named `expense-tracker`
- one Hermes **plugin** also named `expense-tracker`. 

The profile isolates bot token, config, sessions, memory, and gateway state, while the plugin implements `/set-tracker`, `/set-currency`, `/set-city`, `/x`, and any helper logic. 

## Milestone 1

Assuming this is already done, the `expense-tracker` profile exists and can run its own chat/gateway independently of your default profile. 

### Tasks
- Confirm profile exists.
- Confirm Telegram bot token is configured.
- Confirm the profile can start its own gateway. 

### Files
- `~/.hermes/profiles/expense-tracker/config.yaml`
- `~/.hermes/profiles/expense-tracker/.env`
- `~/.hermes/profiles/expense-tracker/SOUL.md`

### Done criteria
- `expense-tracker chat` works. 
- `expense-tracker gateway start` works. 
- The bot is isolated from other Hermes profiles. 

## Milestone 2

Create the plugin skeleton and enable it only for the `expense-tracker` profile. 

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
- Enable the plugin in the `expense-tracker` profile config under `plugins.enabled`. 

### Files
- `~/.hermes/plugins/expense-tracker/plugin.yaml`
- `~/.hermes/plugins/expense-tracker/__init__.py`
- `~/.hermes/profiles/expense-tracker/config.yaml`

### Done criteria
- Hermes discovers the plugin. 
- The plugin is enabled only in `expense-tracker`. 
- `/set-tracker`, `/set-currency`, `/set-city`, and `/x` are recognized, even if they only return placeholder responses. 

## Milestone 3

Implement persistent tracker state under the `expense-tracker` profile home so command behavior survives restarts. 

### Tasks
- Create a profile-local data directory:
```text
~/.hermes/profiles/expense-tracker/expense-data/
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
  - default city.
- Write helper functions:
  - load state
  - save state
  - create tracker if missing
  - set active tracker
  - update tracker defaults

### Behavior decisions
- Only **one** tracker is active at a time.
- `/set-tracker <name>`:
  - creates the tracker if missing,
  - activates it immediately,
  - is idempotent if the tracker already exists.

### Files
- `~/.hermes/plugins/expense-tracker/state.py`
- `~/.hermes/profiles/expense-tracker/expense-data/trackers.yaml`

### Done criteria
- `/set-tracker Japan-2026` creates or selects a tracker.
- `/set-currency JPY` persists.
- `/set-city Tokyo` persists.
- Restarting the gateway keeps the same state. 

## Milestone 4

Implement CSV creation and append logic using the final schema.

### Schema
Use this exact header:

```csv
name,tags,cost,currency,cost_sgd,city
```

### Tasks
- Write a CSV writer module that:
  - creates the file if missing,
  - writes headers once,
  - appends rows in the same order,
  - allows blank optional fields.
- Create one CSV file per tracker under:
```text
~/.hermes/profiles/expense-tracker/expense-data/output/
```

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

Implement `/x` v1 as a deterministic expense logger using **dashes for fields** and **commas inside tags**.

### CSV mapping
Rows map to:

- `name`
- `tags`
- `cost`
- `currency`
- `cost_sgd`
- `city`.

### Input rules
Canonical forms:

- `/x cost - name`
- `/x cost - currency - name`
- `/x cost - currency - name - tags`
- `/x cost - currency - name - tags - city`
- `/x cost - currency - name - city` (no tags, explicit city)

Rules:
- `cost` is required.
- `currency` is optional; if omitted, use active tracker default.
- `name` is required.
- `tags` are optional.
- `city` is optional; if omitted, use tracker default city, and if no default exists, leave blank.
- Tags are a comma-separated list inside one field, e.g. `food,friends,work`.
- `cost_sgd` stays blank in v1 unless you explicitly add conversion later.

### Disambiguation rule
When there is one trailing field after `name`:
- if it contains a comma, treat it as `tags`
- otherwise treat it as `city`

Examples:
- `/x 12 - coffee`
- `/x 1200 - JPY - ramen`
- `/x 30 - SGD - lunch - food,friends,work`
- `/x 25 - SGD - museum ticket - Tokyo`
- `/x 18.5 - SGD - taxi - transport,airport - Singapore`.

### Tasks
- Write a deterministic parser for this format.
- Use tracker defaults for missing currency/city.
- Validate cost parsing.
- Append parsed row to the active tracker CSV.

### Files
- `~/.hermes/plugins/expense-tracker/parser.py`
- `~/.hermes/plugins/expense-tracker/commands.py`

### Done criteria
- `/x 12 - coffee` writes a valid row.
- `/x 1200 - JPY - ramen` overrides default currency.
- `/x 30 - SGD - lunch - food,friends,work` stores tags.
- `/x 25 - SGD - museum ticket - Tokyo` stores city without requiring tags.
- If no active tracker exists, `/x` returns a clear error and writes nothing.

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
- You can see exactly where `/x` will write.
- You can confirm default currency/city before logging.

## Milestone 8

Add `cost_sgd` support without blocking logging.

### Decisions
For v1:
- keep `cost_sgd` in the schema,
- leave it blank by default,
- do not add FX API dependency yet.

Later options:
- exchange-rate lookup on write,
- backfill script for historical rows,
- manual normalization workflow.

### Files
- `~/.hermes/plugins/expense-tracker/parser.py`
- `~/.hermes/plugins/expense-tracker/commands.py`
- optional future conversion module

### Done criteria
- Logging works even when SGD conversion is unavailable.
- Original `cost` and `currency` are always preserved.

## Milestone 9

Add guardrails and cleanup.

### Tasks
- Add input validation for bad costs/currencies.
- Improve error messages.
- Add basic duplicate protection.
- Decide whether to track source message metadata.

Suggested v1 error behavior:
- No active tracker:
  - return: `No active tracker. Run /set-tracker <name> first.`
- Invalid cost:
  - return a clear format hint
- Existing tracker on `/set-tracker`:
  - do not error; just activate it

Possible duplicate strategy:
- save Telegram message ID in sidecar state, or
- hash tracker + message text + timestamp

### Files
- `~/.hermes/plugins/expense-tracker/state.py`
- `~/.hermes/plugins/expense-tracker/commands.py`

### Done criteria
- Repeated messages do not silently duplicate.
- Bad input fails with a useful correction message.
- The system is stable enough for daily use.

## File layout

```text
~/.hermes/plugins/expense-tracker/
  plugin.yaml
  __init__.py
  commands.py
  state.py
  parser.py
  csv_writer.py

~/.hermes/profiles/expense-tracker/
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

1. Milestone 2: plugin skeleton  
2. Milestone 3: persistent tracker state  
3. Milestone 4: CSV writer  
4. Milestone 5: tracker-setting commands  
5. Milestone 6: `/x` logger  
6. Milestone 7: context commands  
7. Milestone 8: `cost_sgd`  
8. Milestone 9: guardrails  

## v1 success definition

You have a solid v1 once this works end to end:

1. `/set-tracker Japan-2026`
2. `/set-currency JPY`
3. `/set-city Tokyo`
4. `/x 1200 - ramen`
5. A row appears in `Japan-2026.csv` like:

```csv
ramen,,1200,JPY,,Tokyo
```

and this works too:

```text
/x 18.5 - SGD - taxi - transport,airport - Singapore
```

which should yield:

```csv
taxi,"transport,airport",18.5,SGD,,Singapore
```

## Hermes-specific implementation notes

- Use a [**profile**](https://hermes-agent.nousresearch.com/docs/user-guide/profiles) for isolation.
- Use a [**plugin**](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins#what-plugins-can-do) for custom slash commands.
- Register commands with `ctx.register_command(name, handler, description)`.
- Enable the plugin explicitly in `plugins.enabled`.
- Store profile-scoped state relative to the active Hermes home, not a global fixed path.