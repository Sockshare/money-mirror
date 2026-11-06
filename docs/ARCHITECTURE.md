# Architecture (for developers)

Money Mirror is a local-first FastAPI app with a single static page. All analytics are deterministic Python; the optional LLM is confined to two narrow, data-free tasks.

```
Browser (127.0.0.1) ── static/index.html + app.js + app.css (vanilla JS, hand-drawn SVG charts, no CDN)
        │ JSON
server.py (FastAPI)
  /api/import, /api/import/sample ─► importer.py ─► categorize.py ─► store.py (SQLite)
  /api/overview                     ─► analysis.py (overview, monthly, subscriptions, alerts)
  /api/transactions (+ /category)   ─► store.py (edit + learn rule)
  /api/ask                          ─► ai.question_to_spec ─► analysis.run_query ─► phrase_answer
  /api/ai/categorize                ─► ai.categorize_merchants ─► store.add_rules
  /api/export.csv, /api/data, /api/settings, /api/status, /api/test-connection
llm/providers.py: Ollama | OpenAI-compatible | Gemini | Offline   (shared with Paperwork Pilot)
```

## Design decisions

**The LLM never sees financial data.** `ai.py` sends only (a) merchant name strings to categorize and (b) the user's question text plus the category list and merchant names, asking for a JSON `QuerySpec`. The spec is validated against known categories/merchants and executed locally by `analysis.run_query`. A smoke test asserts no amounts or dates appear in any prompt. This keeps small local models useful (no arithmetic, no long context) and makes cloud mode defensible.

**Rules first, AI second.** `categorize.py` has ~70 regex rules covering ~300 merchants; user corrections become rules in SQLite (`rules` table) and win over everything. The AI is only consulted for leftovers and its answers are stored as rules so it is never asked twice.

**Idempotent import.** `store.txn_id()` hashes (date, description, amount, account). Re-importing an overlapping export adds only new rows. Two identical rows within one file (two coffees) are kept via a per-file counter suffix.

**Bank-agnostic importer.** `importer.py` finds the header row by delimiter density (skips preambles), maps columns by multilingual header synonyms with a content-based fallback for headerless files, parses dates with DMY detection, handles signed amounts / Debit+Credit / Type columns, and infers sign convention (flips when most rows are positive and no debit/credit split exists).

**Partial-month honesty.** `analysis.overview` compares the two most recent *complete* months and excludes the current partial month from the average; "pace" only appears from day 10.

**Subscription detection.** Group by cleaned merchant → require ≥3 charges (or 2 ≈ a year apart) → median gap maps to a cadence → amount spread must be small (everyday categories like groceries are excluded unless amounts are identical) → step change in the last charge vs earlier median = price increase.

**No chart library.** Monthly bars/line are a ~30-line SVG template; category bars are CSS. Zero dependencies to break.

## Data

`~/.money_mirror/money.db` — tables `transactions`, `rules`, `imports` (chmod 600). `~/.money_mirror/config.json` — settings. Override location with `MONEY_MIRROR_DATA_DIR`.

## Testing

```
tests/unit/    importer formats, amount/date parsing, merchant cleaning, categorizer, analysis, question parser
tests/smoke/   API via TestClient, idempotent import, learned rules, export, privacy (socket guard), fake-AI prompt audit
tests/ui/      Playwright click-through of every tab/modal/edit/ask; responsive overflow; screenshots
scripts/       selfcheck.py, readability_check.py, fresh_install_test.sh, make_samples.py
```

## Extending

- New bank header names → `importer.py` `*_HEADERS` tuples.
- New merchant rule → one tuple in `categorize.RULES` (specific before generic).
- New question phrasing → `analysis.parse_question` synonyms / time patterns.
- New alert type → `analysis.alerts`; the UI renders any `{type, severity, title, detail, ids, date}`.
