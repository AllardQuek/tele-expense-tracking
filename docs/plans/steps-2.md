Yes — by “normalized string form,” I mean something like `"12.5"` instead of `"12.50"` if the numeric value is the same. Since you’re onboard with that, **Milestone 4 Step 1** should be setting up `csv_writer.py` with the final schema constants and a small normalization helper, before we touch file creation or appending. Hermes’ guide recommends keeping logic in dedicated modules and registration separate, so introducing a focused `csv_writer.py` is the right next layer. 

## Step 1

Create `csv_writer.py` with:
- the exact header order,
- a required-field definition,
- a numeric normalizer for `cost` and later `cost_sgd`,
- a row-normalization function that returns values in the exact schema shape. 

Use this as your starting file:

```python
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Dict, Any

CSV_HEADER = ["name", "tags", "cost", "currency", "cost_sgd", "city"]
REQUIRED_FIELDS = ["name", "cost"]
OPTIONAL_FIELDS = ["tags", "currency", "cost_sgd", "city"]


def normalize_decimal_string(value: Any) -> str:
    if value is None:
        raise ValueError("Numeric value cannot be None")

    text = str(value).strip()
    if not text:
        raise ValueError("Numeric value cannot be blank")

    try:
        dec = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"Invalid numeric value: {value}")

    normalized = format(dec.normalize(), "f")

    if normalized == "-0":
        normalized = "0"

    return normalized


def normalize_expense_row(row: Dict[str, Any]) -> Dict[str, str]:
    if not isinstance(row, dict):
        raise ValueError("Row must be a dict")

    name = str(row.get("name", "")).strip()
    if not name:
        raise ValueError("Field 'name' is required")

    cost = normalize_decimal_string(row.get("cost"))

    tags = str(row.get("tags", "") or "").strip()
    currency = str(row.get("currency", "") or "").strip().upper()
    city = str(row.get("city", "") or "").strip()

    cost_sgd_raw = row.get("cost_sgd", "")
    cost_sgd = ""
    if cost_sgd_raw not in (None, ""):
        cost_sgd = normalize_decimal_string(cost_sgd_raw)

    return {
        "name": name,
        "tags": tags,
        "cost": cost,
        "currency": currency,
        "cost_sgd": cost_sgd,
        "city": city,
    }
```

## Why this first

This keeps Milestone 4 focused on **schema correctness first**, before file I/O. Hermes’ plugin guide emphasizes clear separation of implementation modules, and doing normalization first means your later CSV append logic can assume rows are already valid and properly shaped. 

It also encodes the decisions you just made:
- `name` is required,
- `cost` is numeric,
- `tags`, `currency`, `cost_sgd`, and `city` may be blank,
- numeric values are stored in normalized string form. 

## Test 1

Run this direct Python test from the plugin folder:

```bash
python - <<'PY'
from csv_writer import CSV_HEADER, normalize_decimal_string, normalize_expense_row

print("header =", CSV_HEADER)

print("12.50 ->", normalize_decimal_string("12.50"))
print("12.5 ->", normalize_decimal_string("12.5"))
print("0.00 ->", normalize_decimal_string("0.00"))

row = normalize_expense_row({
    "name": "ramen",
    "tags": "food",
    "cost": "12.50",
    "currency": "jpy",
    "cost_sgd": "",
    "city": "Tokyo",
})
print("row =", row)

row2 = normalize_expense_row({
    "name": "airport train",
    "cost": 18,
})
print("row2 =", row2)
PY
```

## Expected output

You should see:
- `header` exactly as `['name', 'tags', 'cost', 'currency', 'cost_sgd', 'city']`,
- `"12.50"` normalize to `"12.5"`,
- `"0.00"` normalize to `"0"`,
- `currency` normalized to uppercase,
- missing optional fields become empty strings. 

For example, the two rows should look roughly like:

```python
{
  'name': 'ramen',
  'tags': 'food',
  'cost': '12.5',
  'currency': 'JPY',
  'cost_sgd': '',
  'city': 'Tokyo'
}
```

and

```python
{
  'name': 'airport train',
  'tags': '',
  'cost': '18',
  'currency': '',
  'cost_sgd': '',
  'city': ''
}
```

## Pass criteria

Step 1 is done if:
- the header constant matches the milestone exactly,
- numeric normalization works,
- row normalization enforces required fields,
- optional fields safely become blank strings. 

## Small note

At this step, we are **not** creating CSV files yet. We are only defining the schema and row normalization contract that the writer will use later, which makes Step 2 much simpler and less error-prone. 

When Test 1 passes, Step 2 is `ensure_csv_exists(csv_path)` so new tracker CSVs get the final header exactly once.

---

## Step 2

Add these functions to `csv_writer.py` below your normalization helpers:

```python
from pathlib import Path
import csv


def ensure_csv_exists(csv_path: str | Path) -> Path:
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADER)

    return path


def csv_has_expected_header(csv_path: str | Path) -> bool:
    path = Path(csv_path)
    if not path.exists() or path.stat().st_size == 0:
        return False

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        first_row = next(reader, None)

    return first_row == CSV_HEADER
```

## Why this step

This gives you the core “create missing CSV automatically” behavior, but only when the plugin already knows **which tracker file** it is working with. That matches your earlier clarification that the plugin should not invent a tracker or CSV when no tracker is set; instead, tracker creation or append logic should call `ensure_csv_exists()` with a known path. 

The helper also guards against duplicate headers by only writing the header when the file is missing or empty. 

## Test 2

Run this direct test from the plugin folder:

```bash
python - <<'PY'
from pathlib import Path
from csv_writer import ensure_csv_exists, csv_has_expected_header

test_path = Path.home() / ".hermes" / "plugins-data" / "expense-tracker" / "output" / "csv-writer-test.csv"

if test_path.exists():
    test_path.unlink()

created = ensure_csv_exists(test_path)
print("created =", created)
print("exists =", test_path.exists())
print("header_ok =", csv_has_expected_header(test_path))

with test_path.open("r", encoding="utf-8") as f:
    print("contents:")
    print(f.read())

# Run again to confirm it does not duplicate the header
ensure_csv_exists(test_path)

with test_path.open("r", encoding="utf-8") as f:
    print("contents_after_second_call:")
    print(f.read())
PY
```

## Expected result

You should see:
- the file created under your plugin-owned output directory,
- `exists = True`,
- `header_ok = True`,
- file contents exactly:

```text
name,tags,cost,currency,cost_sgd,city
```

with no duplicate header after the second `ensure_csv_exists()` call. 

## Pass criteria

Step 2 is done if:
- a missing CSV file gets created,
- the header is exactly `name,tags,cost,currency,cost_sgd,city`,
- calling `ensure_csv_exists()` twice does not add a second header row. 

## One implementation note

Right now `csv_has_expected_header()` is mainly a test/debug helper, but it will also be useful later if you want to validate legacy CSVs or fail fast when the schema is wrong.  We are still not appending any data rows yet; that comes in Step 3. 

---

Next step is to wire `state.py` to use the new CSV module, so `/set-tracker` creates tracker files through `csv_writer.ensure_csv_exists()` instead of hardcoding the old header inline. That keeps one canonical owner for CSV schema and creation logic, which matches the Hermes guide’s separation between implementation modules and registration. 

## Step 3

Update `state.py` so tracker creation delegates CSV bootstrap to `csv_writer.py`. The key change is to remove the old inline `write_text("date,amount,...")` logic and replace it with a call to `ensure_csv_exists(csv_path)`. 

At the top of `state.py`, add:

```python
from .csv_writer import ensure_csv_exists
```

Then update `create_tracker_if_missing()` to this shape:

```python
def create_tracker_if_missing(tracker_name: str) -> Dict[str, Any]:
    tracker_name = tracker_name.strip()
    if not tracker_name:
        raise ValueError("tracker_name cannot be empty")

    state = load_state()
    trackers = state["trackers"]

    if tracker_name not in trackers:
        csv_path = _tracker_csv_path(tracker_name)

        ensure_csv_exists(csv_path)

        trackers[tracker_name] = {
            "csv_path": str(csv_path),
            "default_currency": None,
            "default_city": None,
        }

        save_state(state)

    return trackers[tracker_name]
```

This makes tracker creation the trigger point, while `csv_writer.py` owns the actual file/header behavior. 

## Why this matters

Before this change, your tracker creation code still knew too much about the CSV file format and was writing the old header directly.  After this change, `state.py` only decides that a tracker should have a CSV and what its path is, while `csv_writer.py` decides how that CSV is initialized correctly with the new schema. 


## Test 3

text
/set-tracker Milestone4-Test
Then inspect:

bash
cat ~/.hermes/plugins-data/expense-tracker/output/Milestone4-Test.csv
cat ~/.hermes/plugins-data/expense-tracker/trackers.json
What you should expect
The new CSV file should exist and contain exactly:

text
name,tags,cost,currency,cost_sgd,city
with no old header like date,amount,currency,category,city,description. If that is true, then Step 3 passed, because /set-tracker is now triggering CSV creation through csv_writer.ensure_csv_exists().

## After this

Once this passes, Step 4 should be implementing `append_expense_row(csv_path, row)` in `csv_writer.py`, using `normalize_expense_row()` and `ensure_csv_exists()` so rows are always appended in the exact header order without duplicate header rows. 

---

Great — Step 4 is to implement the actual row append logic in `csv_writer.py`. The Hermes guide emphasizes keeping implementation logic in dedicated modules, so appending rows belongs in `csv_writer.py`, while `state.py` continues to own tracker metadata and `__init__.py` stays just registration. 

## Step 4

Add `append_expense_row()` to `csv_writer.py`, using the normalization and bootstrap helpers you already built. It should:
- ensure the CSV exists,
- normalize the input row,
- write values in the exact header order,
- never write the header twice. 

Add this function:

```python
def append_expense_row(csv_path: str | Path, row: Dict[str, Any]) -> Path:
    path = ensure_csv_exists(csv_path)
    normalized = normalize_expense_row(row)

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([normalized[column] for column in CSV_HEADER])

    return path
```

That gives you one canonical path for appending rows, and because it calls `ensure_csv_exists()` first, it also works safely if the file was deleted or never created yet. 

## Why this design

This keeps the CSV writer layer self-contained:
- `normalize_expense_row()` validates and shapes the data,
- `ensure_csv_exists()` guarantees the file and header,
- `append_expense_row()` appends exactly one data row in stable column order. 

That separation follows the same “schemas / handlers / registration” mindset Hermes documents for plugins: one module owns one responsibility cleanly. 

## Test 4

Because your package now uses relative imports, the easiest test at this stage is a direct test of `csv_writer.py`, which should still be importable from the plugin folder. Run:

```bash
python - <<'PY'
from pathlib import Path
from csv_writer import ensure_csv_exists, append_expense_row

test_path = Path.home() / ".hermes" / "plugins-data" / "expense-tracker" / "output" / "append-test.csv"

if test_path.exists():
    test_path.unlink()

ensure_csv_exists(test_path)

append_expense_row(test_path, {
    "name": "ramen",
    "tags": "food",
    "cost": "12.50",
    "currency": "jpy",
    "city": "Tokyo",
})

append_expense_row(test_path, {
    "name": "airport train",
    "cost": 18,
})

with test_path.open("r", encoding="utf-8") as f:
    print(f.read())
PY
```

## Expected output

The file should contain exactly this structure:

```text
name,tags,cost,currency,cost_sgd,city
ramen,food,12.5,JPY,,Tokyo
airport train,,18,,,
```

Important checks:
- only one header row,
- `"12.50"` becomes `"12.5"`,
- `"jpy"` becomes `"JPY"`,
- blank optional fields stay blank,
- columns stay in exact schema order. 

## Pass criteria

Step 4 is done if:
- appending one row works,
- appending multiple rows works,
- the header appears only once,
- rows are written in the exact order `name,tags,cost,currency,cost_sgd,city`. 

---

Next step should be the **Milestone 4 integration pass**: connect `csv_writer.py` to real tracker usage and confirm the done criteria end-to-end. You already built the schema normalization, CSV bootstrap, and append logic, and the Hermes guide’s overall pattern is to finish by wiring the implementation into the actual plugin flow and testing it through the registered interface. 

## Step 5

For this milestone, Step 5 is not adding a new user-facing command yet; it is verifying that the tracker flow and CSV writer work together consistently. Since you already updated `state.py` so tracker creation uses `ensure_csv_exists()`, the remaining task is to confirm:
- new tracker creation creates a valid CSV with the final header,
- appending rows works on that tracker CSV,
- repeated appends never create duplicate header rows. 

I would treat this as a focused integration/acceptance step for `state.py` plus `csv_writer.py`, before moving on to a future `/add-expense` command. 

## Test 5

Use a fresh tracker in Hermes first:

```text
/set-tracker Milestone4-Integration
```

Then inspect the CSV file:

```bash
cat ~/.hermes/plugins-data/expense-tracker/output/Milestone4-Integration.csv
```

It should contain exactly:

```text
name,tags,cost,currency,cost_sgd,city
```

and nothing else. 

Now append rows directly with the writer layer using that tracker’s CSV path:

```bash
python - <<'PY'
from csv_writer import append_expense_row
from pathlib import Path

csv_path = Path.home() / ".hermes" / "plugins-data" / "expense-tracker" / "output" / "Milestone4-Integration.csv"

append_expense_row(csv_path, {
    "name": "ramen",
    "tags": "food",
    "cost": "12.50",
    "currency": "jpy",
    "city": "Tokyo",
})

append_expense_row(csv_path, {
    "name": "ferry",
    "tags": "travel",
    "cost": "35.00",
    "currency": "jpy",
})

with csv_path.open("r", encoding="utf-8") as f:
    print(f.read())
PY
```

## Expected output

You should see exactly one header row and then two appended rows:

```text
name,tags,cost,currency,cost_sgd,city
ramen,food,12.5,JPY,,Tokyo
ferry,travel,35,JPY,,
```

Checks that matter:
- no duplicate header row,
- normalized numeric strings,
- uppercase currency,
- blank optional fields allowed,
- row order matches schema exactly. 

## Done criteria

Milestone 4 is done if all of these pass:
- `/set-tracker <name>` creates a tracker whose CSV uses the final schema header,
- `append_expense_row()` reliably appends rows,
- the header appears only once even after repeated calls,
- optional fields can remain blank without errors. 

## One cleanup note

The Hermes docs’ tool-handler section stresses predictable interfaces and catching errors, and that same principle is useful here too: before leaving this milestone, make sure `csv_writer.py` raises clear `ValueError`s for bad numeric input rather than silently writing malformed rows.  You already laid most of that groundwork with `normalize_decimal_string()` and `normalize_expense_row()`. 

## What comes after

After this, the natural next milestone is implementing real `/add-expense` behavior using:
- active tracker from `state.py`,
- tracker defaults for currency and city,
- optional tag inference rules,
- `csv_writer.append_expense_row()` as the final persistence call. 