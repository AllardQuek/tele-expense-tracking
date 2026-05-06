## Updated milestone 5

I’d update it to:

- command: `/expense`
- input shape: `name - cost - [tags] - [city] - [cost_sgd]`
- tags are written as hashtags, e.g. `#friends #work`
- cost may include raw currency text, e.g. `30 sgd`, `10thb`, `10 baht`
- city and `cost_sgd` stay optional
- rows append through `csv_writer.append_expense_row()` into the existing tracker CSV. 

## Parsing rules

The deterministic rules I’d use are:

- First field = `name`, required. 
- Second field = `cost`, required; parse leading numeric part as `cost`, remaining text as `currency`, otherwise fallback to active tracker default currency. 
- Any field containing one or more `#tags` = tags field; store in CSV as comma-separated values without `#`. 
- A numeric-only trailing field = `cost_sgd`. 
- A remaining plain-text trailing field = `city`; if omitted, fallback to tracker default city, otherwise blank. 

## Examples

Examples that should work under this spec:

- `/expense coffee - 12`
- `/expense ramen - 1200 jpy`
- `/expense lunch - 30 sgd - #friends #work`
- `/expense museum ticket - 25 sgd - tokyo`
- `/expense taxi - 18.5 sgd - #transport #airport - singapore`
- `/expense ferry - 35 jpy - #travel - osaka - 0.32` 

These are practical because hashtags clearly distinguish tags from city names, which slash-command raw strings otherwise do not do for you automatically. 

## Next implementation step

Step 1 for this milestone should be: create `parser.py` with two pure helpers:
- `parse_cost_field(text)`,
- `parse_expense_command(raw_args, default_currency=None, default_city=None)`. 

Keep this step parser-only at first, with no CSV writes yet, so you can test the grammar independently before wiring it into `commands.py`. 

## Test focus

For the first parser test, I’d verify these cases:

- `coffee - 12`
- `ramen - 1200 jpy`
- `lunch - 30 sgd - #friends #work`
- `museum ticket - 25 sgd - tokyo`
- `taxi - 18.5 sgd - #transport #airport - singapore`
- `ferry - 35 jpy - #travel - osaka - 0.32` 

Each should resolve deterministically into `name`, `tags`, `cost`, `currency`, `cost_sgd`, and `city` before anything touches the CSV layer. 

## Ready to code

This updated milestone aligns with both your current architecture and the Hermes slash-command model. The docs only require that slash commands be registered correctly and consume raw strings, so the grammar itself is entirely yours to define. 
