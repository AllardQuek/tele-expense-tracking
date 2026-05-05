Yes — here’s the **clean implementation plan** with only the Hermes-specific details that matter.

## Architecture

Use **both**:
- an `expenses` Hermes **profile**
- an `expense-tracker` **plugin**

Why:
- The **profile** isolates bot token, config, sessions, memory, and state.
- The **plugin** adds your custom slash commands like `/set-tracker`, `/set-currency`, `/set-city`, and `/x` using Hermes’ plugin command registration. 

So the design is:

- `expenses` profile = the expense bot environment. 
- `expense-tracker` plugin = the expense bot behavior. 

## Core decisions

Keep these product decisions as-is:

- Separate CSV per tracker.
- Columns:
  - `date`
  - `city`
  - `name`
  - `tags`
  - `amount`
  - `currency`
  - `amount_sgd` optional
- One primary amount + currency, with optional normalized SGD value.
- Tracker-specific defaults for city and currency.

## Milestone 1

Set up the dedicated Hermes profile.

### Deliverables
- Create an `expenses` profile.
- Configure its own `.env`, `config.yaml`, and `SOUL.md`.
- Configure the Telegram bot token in that profile.
- Optionally set `terminal.cwd` to your expense project folder if you want predictable tool execution. 

### Acceptance criteria
- You can run:
  - `expenses chat`
  - `expenses gateway start`
- The Telegram bot connects through the `expenses` profile.
- It is isolated from your default Hermes setup. 

### Useful Hermes detail
Profiles are separate Hermes homes, so each one gets its own config, API keys, memory, sessions, and gateway state. 

## Milestone 2

Create the plugin skeleton.

### Deliverables
Create a plugin folder like:

```text
~/.hermes/plugins/expense-tracker/
  plugin.yaml
  __init__.py
```

`plugin.yaml`
- name
- version
- description

`__init__.py`
- `register(ctx)` function
- registers slash commands via `ctx.register_command(...)`. 

### Acceptance criteria
- Hermes discovers the plugin.
- You enable it in the `expenses` profile config.
- `/plugins` or plugin listing shows it loaded. 

### Useful Hermes detail
Plugins are **opt-in**. Discovery alone is not enough; you must enable the plugin in `plugins.enabled`. 

## Milestone 3

Implement tracker state and persistence.

### Deliverables
Store state under the `expenses` profile directory, not in some global hardcoded path.

Suggested files:

```text
<profile-home>/
  expense-data/
    trackers.yaml
    output/
      Japan-2026.csv
      Daily-2026.csv
```

`trackers.yaml` should store:
- active tracker
- each tracker’s CSV path
- default currency
- default city

Example shape:

```yaml
active_tracker: Japan-2026

trackers:
  Japan-2026:
    csv_path: expense-data/output/Japan-2026.csv
    default_currency: JPY
    default_city: Tokyo
  Daily-2026:
    csv_path: expense-data/output/Daily-2026.csv
    default_currency: SGD
    default_city: ""
```

### Commands to implement first
- `/set-tracker <name>`
- `/set-currency <code>`
- `/set-city <name>`

### Acceptance criteria
- `/set-tracker Japan-2026` creates or selects the tracker.
- `/set-currency JPY` persists.
- `/set-city Tokyo` persists.
- Restarting the gateway keeps the state.

### Useful Hermes detail
Hermes profiles scope state using `HERMES_HOME`, so your plugin should store files relative to the active profile home, not a fixed `~/.hermes` path. 

## Milestone 4

Implement CSV creation and writing.

### Deliverables
When a tracker is first created:
- create the CSV if it does not exist
- write header row

CSV header:

```csv
date,city,name,tags,amount,currency,amount_sgd
```

Implement a small CSV writer module that:
- ensures file exists
- appends one validated row
- preserves column order

### Acceptance criteria
- New tracker creates a correctly structured CSV.
- Later writes append rows cleanly.
- Empty optional fields are allowed, especially `amount_sgd`.

## Milestone 5

Implement `/x` v1 logging.

### Scope
Make `/x` a simple deterministic logger first.

Examples:
- `/x 12 coffee`
- `/x 1200 jpy ramen`
- `/x 18.5 taxi`
- `/x 30 lunch #food #friends`

### v1 parsing rules
Extract:
- `amount`
- optional explicit `currency`
- `name`
- optional tags
- city from active tracker default unless explicitly overridden later

Suggested behavior:
- If currency omitted, use tracker default.
- If city omitted, use tracker default.
- If no tracker is active, return an error.
- If parsing fails, return a clear correction message.

### Acceptance criteria
- `/x 12 coffee` writes one row using active defaults.
- `/x 1200 jpy ramen` overrides currency correctly.
- `/x` with no active tracker does not write anything.
- Rows are valid and consistent.

## Milestone 6

Add usability commands.

### Deliverables
Add:
- `/show-context`
- maybe `/list-trackers`

`/show-context` should display:
- active tracker
- CSV file
- default currency
- default city

### Acceptance criteria
- You can inspect current state quickly before logging.
- It is easy to tell where `/x` will write.

## Milestone 7

Add `amount_sgd` support.

### Options
You have 3 reasonable choices:

1. Leave `amount_sgd` blank in v1.
2. Allow manual entry later.
3. Add exchange-rate lookup in a later phase.

### Recommendation
For v1:
- keep the column
- allow it to be blank
- do not block logging if SGD conversion is unavailable

Later, add:
- a backfill script
- or on-write conversion

### Acceptance criteria
- Rows can be summed later by `amount_sgd` when populated.
- Original amount and currency are always preserved.

## Milestone 8

Add safety and quality controls.

### Deliverables
- duplicate protection
- validation
- better error messages

Possible duplicate keys:
- Telegram message ID
- or a hash of message text + timestamp + tracker

If you want this later, add a hidden metadata column or sidecar state file.

### Acceptance criteria
- Replaying the same message does not silently create duplicates.
- Invalid currency or malformed amount gives a useful error.
- Bad input fails safely.

## Milestone 9

Optional smarter parsing

Only after v1 is stable.

### Possible upgrades
- infer tags automatically
- city override in free text
- vendor normalization
- smarter splitting of compound entries
- LLM-assisted parsing for messy messages

### Recommendation
Do **not** start here. Get deterministic `/x` working first.

## Suggested file structure

A practical layout:

```text
~/.hermes/plugins/expense-tracker/
  plugin.yaml
  __init__.py
  state.py
  csv_writer.py
  parser.py
  commands.py

<expenses-profile-home>/
  config.yaml
  .env
  SOUL.md
  expense-data/
    trackers.yaml
    output/
      Japan-2026.csv
      Daily-2026.csv
```

## Recommended build order

Build in this order:

1. Create `expenses` profile.
2. Create and enable `expense-tracker` plugin.
3. Implement tracker state.
4. Implement CSV creation/writer.
5. Implement `/set-tracker`, `/set-currency`, `/set-city`.
6. Implement `/x` v1.
7. Add `/show-context`.
8. Add `amount_sgd` handling.
9. Add duplicate protection and smarter parsing.

## Minimal success definition

You have a good v1 when all of these work:

- Telegram bot runs inside `expenses`.
- Plugin loads in that profile.
- `/set-tracker Japan-2026`
- `/set-currency JPY`
- `/set-city Tokyo`
- `/x 1200 ramen`
- one correct row gets appended to `Japan-2026.csv`

## Hermes-specific implementation notes

- Use a [**profile**](https://hermes-agent.nousresearch.com/docs/user-guide/profiles) for isolation.
- Use a [**plugin**](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins#what-plugins-can-do) for custom slash commands.
- Register commands with `ctx.register_command(name, handler, description)`.
- Enable the plugin explicitly in `plugins.enabled`.
- Store profile-scoped state relative to the active Hermes home, not a global fixed path.
