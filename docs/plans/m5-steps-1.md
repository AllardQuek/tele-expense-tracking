Perfect. Step 1 is to create `parser.py` with a deterministic parser for `/expense`, using the hashtag-based grammar you just chose. Hermes slash commands call your handler with a raw argument string, so a pure parser module is the right first implementation step before wiring it into `commands.py`. 

## Step 1

Create `parser.py` with:
- `parse_cost_field(text)` to extract numeric cost plus optional raw currency text,
- `parse_tags_field(text)` to parse `#tag` tokens,
- `parse_expense_command(raw_args, default_currency=None, default_city=None)` to produce a normalized row dict shaped for `csv_writer.append_expense_row()`. 

Use this as the initial version:

```python
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .csv_writer import normalize_decimal_string

_TAG_RE = re.compile(r"#([A-Za-z0-9_-]+)")
_COST_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(.*)\s*$")


def parse_cost_field(text: str) -> tuple[str, str]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Cost field is required")

    match = _COST_RE.match(text)
    if not match:
        raise ValueError(f"Invalid cost field: {text}")

    raw_cost, raw_currency = match.groups()
    cost = normalize_decimal_string(raw_cost)
    currency = raw_currency.strip()

    return cost, currency


def parse_tags_field(text: str) -> str:
    text = (text or "").strip()
    tags = _TAG_RE.findall(text)

    if not tags:
        raise ValueError("Invalid tags field: must contain at least one hashtag")

    leftover = _TAG_RE.sub("", text).strip()
    if leftover:
        raise ValueError(
            "Invalid tags field: only hashtags and spaces are allowed"
        )

    return ",".join(tags)


def parse_expense_command(
    raw_args: str,
    default_currency: Optional[str] = None,
    default_city: Optional[str] = None,
) -> Dict[str, str]:
    parts = [part.strip() for part in (raw_args or "").split(" - ")]
    parts = [part for part in parts if part]

    if len(parts) < 2:
        raise ValueError(
            "Usage: /expense <name> - <cost> [- <#tags...>] [- <city>] [- <cost_sgd>]"
        )

    name = parts[0]
    if not name:
        raise ValueError("Expense name is required")

    cost, parsed_currency = parse_cost_field(parts )
    currency = parsed_currency or (default_currency or "").strip()

    tags = ""
    city = ""
    cost_sgd = ""

    for field in parts[2:]:
        if "#" in field:
            if tags:
                raise ValueError("Tags provided more than once")
            tags = parse_tags_field(field)
            continue

        try:
            numeric_value = normalize_decimal_string(field)
            if cost_sgd:
                raise ValueError("cost_sgd provided more than once")
            cost_sgd = numeric_value
            continue
        except ValueError:
            pass

        if city:
            raise ValueError("City provided more than once")
        city = field.strip()

    if not city:
        city = (default_city or "").strip()

    return {
        "name": name.strip(),
        "tags": tags,
        "cost": cost,
        "currency": currency,
        "cost_sgd": cost_sgd,
        "city": city,
    }
```

## What this supports

This parser supports the grammar we agreed on:
- `name` first,
- `cost` second, with optional raw currency text,
- hashtags for tags,
- plain trailing text for city,
- numeric-only trailing field for `cost_sgd`. 

So these should parse cleanly:
- `coffee - 12`
- `ramen - 1200 jpy`
- `lunch - 30 sgd - #friends #work`
- `museum ticket - 25 sgd - tokyo`
- `taxi - 18.5 sgd - #transport #airport - singapore`
- `ferry - 35 jpy - #travel - osaka - 0.32` 

## Test 1

From the plugin package context, run a parser-only test. Since your plugin now uses relative imports, the easiest real test is through Hermes later, but for the parser code itself you can still run a package-aware import if you execute from the parent directory or adapt your local workflow accordingly. The main goal is to validate parser behavior before wiring the slash command. 

Use this test shape conceptually:

```python
parse_expense_command("coffee - 12")
parse_expense_command("ramen - 1200 jpy")
parse_expense_command("lunch - 30 sgd - #friends #work")
parse_expense_command("museum ticket - 25 sgd - tokyo")
parse_expense_command("taxi - 18.5 sgd - #transport #airport - singapore")
parse_expense_command("ferry - 35 jpy - #travel - osaka - 0.32")
```

Expected outputs:

- `"coffee - 12"` → `name=coffee`, `cost=12`, `currency=default or blank`, tags blank, city default or blank. 
- `"ramen - 1200 jpy"` → `cost=1200`, `currency=jpy`. 
- `"lunch - 30 sgd - #friends #work"` → `tags=friends,work`. 
- `"museum ticket - 25 sgd - tokyo"` → `city=tokyo`. 
- `"ferry - 35 jpy - #travel - osaka - 0.32"` → `tags=travel`, `city=osaka`, `cost_sgd=0.32`. 

## One note

At this step, don’t wire `commands.py` yet. The parser should stand on its own first, because once it works, the slash command handler becomes very thin: get active tracker/defaults from `state.py`, parse with `parser.py`, append with `csv_writer.py`, return a confirmation string. 

When this parser is done, Step 2 is wiring `/expense` into `commands.py` and `__init__.py`.

Yes — I think you should standardize on **underscore** for the folder/package too. The Hermes docs use plain identifier-style names like `calculator` for directory plugins and underscore-style Python package names for pip entry points, which aligns better with normal Python import rules than hyphenated package folders do. 

## Best convention

Use:
- folder/package: `expense_tracker`
- manifest `name`: `expense_tracker` too, if you want maximum consistency
- slash command: `/expense` 

That removes the mental split between “filesystem name,” “Python import name,” and “plugin name,” which is exactly the confusion you’re worried about. 

## Why this is cleaner

A hyphenated name is mainly attractive as a human-readable label, but in Python-heavy projects it creates friction because imports, package references, and future entry points want identifier-safe names. The Hermes pip example explicitly maps a plugin key like `my-plugin` to a Python package like `my_plugin_package`, which shows that hyphens and Python module paths naturally diverge. 

If your goal is low-confusion local development, testing, and maintenance, one canonical name is better than preserving a prettier hyphenated variant. 

## My recommendation

I’d rename everything to `expense_tracker` now and stay consistent across:
- plugin directory,
- manifest name,
- internal imports,
- future package/distribution name. 

Then expose the user-facing behavior through command names like `/expense`, not through a stylized plugin name. Hermes command registration is independent anyway, since slash commands are registered separately via `ctx.register_command(...)`. 

## Practical rule

So my advice is: **standardize to underscore everywhere except the actual slash command users type**.  That gives you one clean developer-facing identity and one short user-facing command, which is usually the least confusing setup. 

Use this shape:
```text
expense_tracker/
  plugin.yaml   # name: expense_tracker
  __init__.py
  parser.py
  commands.py
  csv_writer.py
  state.py
```

and then register:
```python
ctx.register_command("expense", handler=..., description="Log an expense")
```
That keeps implementation clean while the UX stays concise. 

So no, I would **not** keep the hyphen version unless you specifically care about a published display name.

---

## Step 2
So let’s define your project steps like this:

1. standardize folder/package naming,
2. wire parser.py into commands.py
3. register /expense in __init__.py, integration test inside Hermes,
4. refine persistence/defaults/errors.

That is a better fit for your plugin than spending time on LLM tool schemas you are not using yet.

What to do now
- commands.py: call parse_expense_command(raw_args)
- __init__.py: ctx.register_command("expense", handler=handle_expense, description="Log an expense")

---

