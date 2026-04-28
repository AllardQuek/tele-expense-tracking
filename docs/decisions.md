# Design Decisions & Notes

Personal reference — reasoning behind key architectural choices and open questions.

---

## 1. Why the Telegram pipeline needs an LLM

### The case for rules-based extraction

The idea was: skip the LLM and just use regex to extract amounts. The message data does
contain consistent patterns:

- `$X` / `$X.XX` with an optional currency suffix — e.g. `$34.74 sgd`, `$3.5`
- bare amount + currency — e.g. `22 sgd`, `4100 riel`
- parenthesised amount — e.g. `(8.2k riel)`, `(1.8k riel)`, `(15.17k riel)`
- `Xk CURRENCY` — e.g. `30k VND`, `200k VND`

These are all parseable. The `k` multiplier (×1000) is trivially handled. Merchant names
could be inferred from the first line of a post or emoji-prefixed headers like `🏡`, `🍽️`.

A rules-based approach would probably extract ~70–75% of expenses correctly with minimal
engineering effort.

### Why rules-based is insufficient

There are two failure modes that rules cannot address:

**Silent false positives — unfixable without semantics**

The rules have no way to distinguish a purchase from a non-purchase when an amount appears
in the same sentence. Real examples from the data:

- `"beers ($1) were very tempting too"` — hedged, not bought
- `"she returned me 10k"` — money received, not spent

A regex sees `$1` and extracts it. There is no pattern to detect that the surrounding
sentence negates the purchase. The LLM reads the sentence and correctly skips it.

**False positives from reference/planning content — partially detectable, unreliable**

A pasted Hanoi travel itinerary in the data contains ~15 amounts like `"Ngoc Son Temple
(30k VND)"`, `"Water Puppet Show (200k VND)"`. Rules would generate 15 false expense rows
with no warning. Heuristics like "flag messages with >5 amounts" are brittle — a real
multi-item expense round-up also has 5+ line items.

**The hybrid approach doesn't close the gap**

The obvious response is: run rules first, only use the LLM for "ambiguous" cases. But this
only works for *incomplete* extractions (amount found, no merchant name → flag for LLM).
For false positives, the rules produce a complete-looking, confident extraction. There is
no self-detection signal. The "hybrid" approach is just rules-based with known silent
failure modes.

### Conclusion

The LLM is not used because rules are impossible — it's used because the failure modes of
rules are silent and hard to audit. A small number of wrong rows in the output CSV
(attributed to something that wasn't actually bought) are worse than the marginal cost of
an API call. Given that the export covers a ~4-month trip with a few hundred candidate
messages, the LLM cost is negligible.

---

## 2. Hosting as a service — privacy and feasibility

### What was considered

The question was whether the project could be hosted (e.g. on Vercel) so other travellers
could use it without running it locally.

### The PDF pipeline

The PDF pipeline is entirely deterministic — no external API calls. It parses the
statement, normalises merchant strings, and tags them via keyword rules. There is no
technical barrier to running this server-side with a no-storage policy.

A hosted version would still mean the bank/wallet statement passes through Vercel's
infrastructure in transit. This is manageable with transparency (disclose Vercel as
infra, configure minimal log retention). An even cleaner option would be a full client-
side JS rewrite using pdf.js, in which case the file never leaves the browser. This is
the gold standard for privacy but requires a full rewrite.

### The Telegram pipeline

This pipeline sends Telegram message text — which contains merchant names, amounts, and
personal narrative — to OpenRouter, which routes it to a third-party LLM. This is an
unavoidable privacy implication of using an LLM at all.

The approach taken: users are informed upfront that their message text is sent to
OpenRouter for processing, and they accept that risk explicitly before uploading. This is
standard practice (Notion AI, Grammarly, etc. all do this). It shifts responsibility
appropriately and is honest.

### The SSL verification bug

`extract_expenses.py` currently has `verify=False` in the OpenRouter request, with a
comment saying it was added to work around a local certificate issue:

```python
# SSL verification is disabled for this device due to a local certificate issue.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
...
response = requests.post(..., verify=False)
```

This **must be removed before any deployment**. With `verify=False`, the TLS connection
to OpenRouter provides no authentication — a MITM attacker on the network path could
intercept users' API keys and message content. This is a genuine security vulnerability,
not a cosmetic issue.

### What would be needed to ship this properly

**Minimum viable hosted version:**
1. Fix `verify=False` — remove both the `disable_warnings` call and the `verify=False`
   kwarg. The local cert issue that prompted it does not exist in a server environment.
2. Build a simple web UI (file upload → display CSV download).
3. Users supply their own OpenRouter API key — entered in the UI, used client-side or
   proxied server-side without logging.
4. Add a clear disclosure before upload: message text is sent to OpenRouter / [model name]
   for processing.
5. Configure Vercel log retention to minimal (or disable request body logging).

**If client-side processing is required (no data leaves the browser):**
- PDF pipeline: rewrite in JavaScript using pdf.js + JS port of normalize/tag logic.
  Feasible — all logic is simple and deterministic.
- Telegram pipeline: not feasible client-side without the user supplying their own API
  key and making the OpenRouter call directly from the browser (which exposes the key in
  network traffic, but it's the user's own key so acceptable).

### Conclusion

Both pipelines can be hosted with a reasonable privacy posture. The PDF pipeline is the
simpler case — stateless and third-party-free. The Telegram pipeline requires an
OpenRouter disclosure and a user-owned API key model. Neither requires a privacy policy
that makes promises that can't be kept, as long as the SSL bug is fixed and Vercel is
disclosed as infra.
