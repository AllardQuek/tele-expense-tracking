## Step 1

Create a reusable plugin-owned data directory, not a profile-hardcoded one and not inside the plugin source folder. That fits your clarified requirement that the feature is not profile-scoped, while still keeping runtime data outside shipped plugin code. 

### What we changed
In `state.py`, we set a plugin data home like:

```python
from pathlib import Path
import os

def resolve_data_dir() -> Path:
    override = os.getenv("EXPENSE_TRACKER_DATA_DIR")
    if override:
        return Path(override).expanduser()

    return Path.home() / ".hermes" / "plugins-data" / "expense-tracker"

DATA_DIR = resolve_data_dir()
OUTPUT_DIR = DATA_DIR / "output"
TRACKERS_FILE = DATA_DIR / "trackers.json"
```

Then we added `ensure_data_dirs()` to create:
- `~/.hermes/plugins-data/expense-tracker/`
- `~/.hermes/plugins-data/expense-tracker/output/`
- `~/.hermes/plugins-data/expense-tracker/trackers.json` 

### Test 1
We ran a direct Python smoke test:

```bash
python -c "from state import ensure_data_dirs; ensure_data_dirs(); print('ok')"
```

Then verified the created path manually with `ls` and `cat`. 

### Important correction
We originally pointed data at a profile path like `~/.hermes/profiles/expense-tracker/...`, then realized that was wrong for your use case because your feature is not profile-scoped. We corrected that to `~/.hermes/plugins-data/expense-tracker/`. 

## Step 2

Add `load_state()` and `save_state()` using JSON instead of YAML. Hermes does not require YAML for your plugin’s own runtime state, and JSON avoids the extra `PyYAML` dependency that caused `ModuleNotFoundError: No module named 'yaml'`. 

### What we changed
We replaced YAML with Python’s built-in `json` module and added:

```python
def load_state() -> Dict[str, Any]:
    ensure_data_dirs()
    try:
        with TRACKERS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}

    if not isinstance(data, dict):
        data = {}

    data.setdefault("active_tracker", None)
    data.setdefault("trackers", {})

    if not isinstance(data["trackers"], dict):
        data["trackers"] = {}

    return data


def save_state(state: Dict[str, Any]) -> None:
    ensure_data_dirs()
    with TRACKERS_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
```

### Test 2
We tested a state round-trip directly:

```bash
python - <<'PY'
from state import load_state, save_state, TRACKERS_FILE

print("trackers_file =", TRACKERS_FILE)
state = load_state()
print("initial =", state)

state["active_tracker"] = "Japan-2026"
state["trackers"]["Japan-2026"] = {
    "csv_path": "/tmp/Japan-2026.csv",
    "default_currency": "JPY",
    "default_city": "Tokyo"
}

save_state(state)
print("reloaded =", load_state())
PY
```

Then we inspected `trackers.json` manually with `cat`. 

### Important correction
We hit a `RecursionError: maximum recursion depth exceeded` because `ensure_data_dirs()` called `save_state()` and `save_state()` called `ensure_data_dirs()`. We fixed that by making `ensure_data_dirs()` write the initial empty JSON file directly instead of calling `save_state()`. 

## Step 3

Implement tracker creation and active tracker switching. Hermes slash commands receive raw strings, so `/set-tracker Japan-2026` is supposed to become a thin wrapper over these state helpers later. 

### What we changed
In `state.py`, we added:

```python
def _tracker_csv_path(tracker_name: str) -> Path:
    safe_name = tracker_name.strip().replace("/", "-")
    return OUTPUT_DIR / f"{safe_name}.csv"


def create_tracker_if_missing(tracker_name: str) -> Dict[str, Any]:
    tracker_name = tracker_name.strip()
    if not tracker_name:
        raise ValueError("tracker_name cannot be empty")

    state = load_state()
    trackers = state["trackers"]

    if tracker_name not in trackers:
        csv_path = _tracker_csv_path(tracker_name)
        trackers[tracker_name] = {
            "csv_path": str(csv_path),
            "default_currency": None,
            "default_city": None,
        }

        if not csv_path.exists():
            csv_path.write_text(
                "date,amount,currency,category,city,description\n",
                encoding="utf-8",
            )

        save_state(state)

    return trackers[tracker_name]


def set_active_tracker(tracker_name: str) -> Dict[str, Any]:
    tracker_name = tracker_name.strip()
    if not tracker_name:
        raise ValueError("tracker_name cannot be empty")

    state = load_state()

    if tracker_name not in state["trackers"]:
        create_tracker_if_missing(tracker_name)
        state = load_state()

    state["active_tracker"] = tracker_name
    save_state(state)
    return state["trackers"][tracker_name]
```

### Test 3
We tested this directly with Python:

```bash
python - <<'PY'
from state import set_active_tracker, load_state, TRACKERS_FILE, OUTPUT_DIR

print("trackers_file =", TRACKERS_FILE)
print("output_dir =", OUTPUT_DIR)

first = set_active_tracker("Japan-2026")
print("first =", first)

second = set_active_tracker("Japan-2026")
print("second =", second)

state = load_state()
print("state =", state)
PY
```

Then we checked:
- `cat ~/.hermes/plugins-data/expense-tracker/trackers.json`
- `ls -la ~/.hermes/plugins-data/expense-tracker/output`
- `cat ~/.hermes/plugins-data/expense-tracker/output/Japan-2026.csv` 

### Important correction
At first the JSON still showed `"/tmp/Japan-2026.csv"` because that record came from the earlier Step 2 test. `create_tracker_if_missing()` correctly refused to overwrite the existing tracker, so we cleared the old test state or recreated the tracker fresh. After that, you got the correct output path under `~/.hermes/plugins-data/expense-tracker/output/Japan-2026.csv`. 

## Step 4

Implement per-tracker defaults for currency and city, plus helpers for reading the active tracker. This supports your future behavior where the user can optionally specify currency in an expense command, and otherwise the plugin falls back to the active tracker’s default currency. 

### What we changed
In `state.py`, we added:

```python
def get_active_tracker_name() -> Optional[str]:
    state = load_state()
    return state.get("active_tracker")


def get_active_tracker() -> Optional[Dict[str, Any]]:
    state = load_state()
    active_name = state.get("active_tracker")
    if not active_name:
        return None
    return state.get("trackers", {}).get(active_name)


def update_tracker_defaults(
    currency: Optional[str] = None,
    city: Optional[str] = None,
) -> Dict[str, Any]:
    state = load_state()
    active_name = state.get("active_tracker")

    if not active_name:
        raise ValueError("No active tracker set. Use /set-tracker <name> first.")

    tracker = state["trackers"].get(active_name)
    if not tracker:
        raise ValueError(f"Active tracker '{active_name}' not found.")

    if currency is not None:
        tracker["default_currency"] = currency.strip().upper() or None

    if city is not None:
        tracker["default_city"] = city.strip() or None

    save_state(state)
    return tracker
```

### Test 4
We tested directly:

```bash
python - <<'PY'
from state import (
    set_active_tracker,
    update_tracker_defaults,
    get_active_tracker_name,
    get_active_tracker,
    load_state,
)

print("set_active_tracker =", set_active_tracker("Japan-2026"))
print("update currency =", update_tracker_defaults(currency="JPY"))
print("update city =", update_tracker_defaults(city="Tokyo"))
print("active name =", get_active_tracker_name())
print("active tracker =", get_active_tracker())
print("full state =", load_state())
PY
```

Then verified:

```bash
cat ~/.hermes/plugins-data/expense-tracker/trackers.json
```

### Negative test
We also checked the failure path by clearing active state and confirming `update_tracker_defaults()` raised a “No active tracker set” error rather than silently corrupting state. 

## Step 5

Wire the slash commands cleanly using a `commands.py` file plus a small `__init__.py`. Hermes documents `ctx.register_command(name, handler, description)` for in-session slash commands, and `register()` is called once at startup to wire them in. 

### What we changed
We first considered a `try/except ImportError` fallback in `__init__.py`, but decided against it because it felt messy. Instead, we refactored to a cleaner split:

- `state.py` → persistence
- `commands.py` → slash command handlers
- `__init__.py` → registration only 

### `commands.py`
We added handlers like:

```python
from .state import (
    set_active_tracker,
    update_tracker_defaults,
    get_active_tracker_name,
)

def set_tracker(raw_args: str) -> str:
    tracker_name = raw_args.strip()
    if not tracker_name:
        return "Usage: /set-tracker <name>"

    try:
        tracker = set_active_tracker(tracker_name)
        return (
            f"Active tracker set to: {tracker_name}\n"
            f"CSV: {tracker['csv_path']}"
        )
    except Exception as e:
        return f"Error: {e}"
```

and similar `set_currency()` and `set_city()` handlers. 

### `__init__.py`
We kept registration minimal:

```python
from .commands import set_tracker, set_currency, set_city

def register(ctx):
    ctx.register_command(
        "set-tracker",
        handler=set_tracker,
        description="Create or switch the active expense tracker",
    )
    ctx.register_command(
        "set-currency",
        handler=set_currency,
        description="Set default currency for the active tracker",
    )
    ctx.register_command(
        "set-city",
        handler=set_city,
        description="Set default city for the active tracker",
    )
```

### Test 5
```bash
python - <<'PY'
from commands import set_tracker, set_currency, set_city

print(set_tracker("Japan-2026"))
print(set_currency("JPY"))
print(set_city("Tokyo"))
PY
```

That worked, which confirmed the handlers were correct before doing the full Hermes integration test. 


## Step 6

Start Hermes normally, then in the session run:

```text
/plugins
/set-tracker Japan-2026
/set-currency JPY
/set-city Tokyo
```

According to the docs, `ctx.register_command()` makes these slash commands available in-session, and `/plugins` should show whether the plugin is loaded or disabled. 

## Test 6A

First, check plugin load status:

```text
/plugins
```

What you want:
- your plugin appears in the list,
- it is shown as loaded rather than disabled. 

If it does **not** appear or shows as disabled, the docs say a crash in `register()` disables the plugin while Hermes itself keeps running, so that means you likely still have an import error or registration error in `__init__.py` or `commands.py`. 

## Test 6B

Now test the commands in-session:

```text
/set-tracker Japan-2026
/set-currency JPY
/set-city Tokyo
```

Expected results:
- `/set-tracker Japan-2026` should create or select the tracker and show its CSV path,
- `/set-currency JPY` should set the default currency on the active tracker,
- `/set-city Tokyo` should set the default city on the active tracker. 

Because Hermes slash-command handlers receive a raw argument string after the command name, these three calls are exactly the intended interface for the handlers you wired. 

## Test 6C

After the chat commands succeed, verify persistence on disk:

```bash
cat ~/.hermes/plugins-data/expense-tracker/trackers.json
ls -la ~/.hermes/plugins-data/expense-tracker/output
cat ~/.hermes/plugins-data/expense-tracker/output/Japan-2026.csv
```

Expected state:

```json
{
  "active_tracker": "Japan-2026",
  "trackers": {
    "Japan-2026": {
      "csv_path": "/Users/allard/.hermes/plugins-data/expense-tracker/output/Japan-2026.csv",
      "default_currency": "JPY",
      "default_city": "Tokyo"
    }
  }
}
```

And the CSV file should exist with the header row. 

## Test 6D

Do a quick negative-path check inside Hermes too:

```text
/set-tracker
/set-currency
/set-city
```

Expected:
- usage messages for missing args,
- no plugin crash,
- no broken state write. 

This is worth doing because the docs emphasize that plugin handlers should fail safely instead of crashing the plugin or agent loop. 

## Pass criteria

Step 6 is done if all of these are true:
- `/plugins` shows the plugin as loaded,
- the slash commands run in Hermes chat,
- `trackers.json` updates correctly,
- the CSV file exists in `output/`,
- bad input gives a friendly response instead of disabling the plugin. 

## After Step 6

The next and final step for this milestone is restart persistence:
1. stop Hermes,
2. start Hermes again,
3. verify `trackers.json` still has the same state,
4. run `/set-tracker Japan-2026` and confirm it reuses the saved tracker state rather than recreating it. 

Run Step 6 and paste:
- `/plugins` output,
- the output of the three slash commands,
- and the final `trackers.json`.

Yes — here is **Step 7** rewritten cleanly as “list and delete trackers,” with the exact file changes and **Test 7** included. Hermes supports in-session slash commands through `ctx.register_command(name, handler, description)`, with handlers receiving the raw argument string, so `/list-trackers` and `/delete-tracker <name>` fit directly into the plugin structure you already have. 

## Step 7

Add tracker management helpers in `state.py`, then add slash-command handlers in `commands.py`, then register them in `__init__.py`. The Hermes docs recommend keeping registration separate from implementation, which is exactly what this structure does. 


## Test 7

Do this in two parts: direct helper validation, then Hermes chat validation. The docs’ Step 6 pattern uses `/plugins` and in-session commands, so the final confirmation should happen inside Hermes. 

### Test 7A

First, direct state-level test:

```bash
python - <<'PY'
from state import (
    set_active_tracker,
    update_tracker_defaults,
    list_trackers,
    delete_tracker,
)

set_active_tracker("Japan-2026")
update_tracker_defaults(currency="JPY", city="Tokyo")

set_active_tracker("Singapore-2026")
update_tracker_defaults(currency="SGD", city="Singapore")

print("before =", list_trackers())
print("delete =", delete_tracker("Japan-2026"))
print("after =", list_trackers())
PY
```

Expected:
- `before` shows both trackers,
- `delete` reports `Japan-2026` removed,
- `after` no longer contains `Japan-2026`. 

Then verify files:

```bash
cat ~/.hermes/plugins-data/expense-tracker/trackers.json
ls -la ~/.hermes/plugins-data/expense-tracker/output
```

If `Japan-2026.csv` existed, it should be gone after deletion. 

### Test 7B

Now test the actual Hermes commands:

```text
/plugins
/list-trackers
/delete-tracker Japan-2026
/list-trackers
```

Expected:
- `/plugins` shows the plugin loaded,
- first `/list-trackers` shows current trackers and marks the active one with `*`,
- `/delete-tracker Japan-2026` returns a deletion message,
- second `/list-trackers` no longer shows that tracker. 

### Test 7C

Do quick failure checks too:

```text
/delete-tracker
/delete-tracker does-not-exist
```

Expected:
- missing arg → `Usage: /delete-tracker <name>`
- missing tracker → friendly error like `Error: Tracker 'does-not-exist' not found.` 
