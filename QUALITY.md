# Quality Report

Every release of Money Mirror must pass the nine gates below before it is pushed.

**Release:** 1.0.0  ·  **Platform tested:** Debian/Ubuntu-family Linux, Python 3.13, 8-core CPU, no GPU

## The nine gates

| # | Gate | What it proves | How to run it | Result |
|---|------|----------------|---------------|--------|
| G1 | Unit tests | Importer handles 10+ bank layouts (signed amounts, Debit/Credit, Type columns, DMY/MDY, semicolons, European decimals, preambles, headerless); merchant cleaning; 70+ category rules; subscription/alert math; question parser | `pytest tests/unit` | ✅ pass |
| G2 | API smoke tests | Every endpoint; idempotent re-import; learned categories survive re-import; export; delete; friendly 400s for bad files | `pytest tests/smoke` | ✅ pass |
| G3 | Fresh install | README's 3 commands work in a brand-new venv in a temp folder; app starts; example data imports | `bash scripts/fresh_install_test.sh` | ✅ pass |
| G4 | UI in a real browser | Playwright: first-run → import → every tab → drill-down modals → inline category edit → Ask → Settings, at desktop/laptop/phone. Zero console errors, no `undefined`/`null` leaks, no horizontal overflow | `pytest tests/ui` | ✅ pass |
| G5 | Readability | README, User Guide, Troubleshooting, FAQ, Privacy all at grade ≤ 7 | `python scripts/readability_check.py` | ✅ pass (worst 6.9) |
| G6 | Privacy | Socket-blocked test: dashboard + Ask + status work with zero network in No-AI mode. Fake-AI test audits every prompt: no amounts, no transaction dates, no P2P payee names. Cross-site write guard. DB and config created `600` | `pytest tests/smoke -k "network or ai_never or cross_site or private"` | ✅ pass |
| G7 | Independent novice-user review | Separate reviewer agent installed from the README, imported 4 differently-shaped bank CSVs, asked 16 everyday questions | report in review process | ✅ 1 P0 · 8 P1 (all fixed) · 16 P2 (13 fixed, 3 accepted) |
| G8 | Independent code & security review | Separate reviewer agent, 18 repro tests | report in review process | ✅ 1 P0 · 11 P1 (all fixed) · 16 P2 (12 fixed, 4 accepted) |
| G9 | Real local-AI run | Ask tab with real `llama3.2:3b` via Ollama on CPU; merchant naming with the AI | manual, recorded below | ✅ pass |

## What the reviews found and what changed

**Performance (G8 P0):** `alerts()` computed a median inside a per-transaction loop (O(n²)) — 70 s for 20k rows, never returning at 100k. Median is now computed once per category; 20k rows analyze in < 1 s. `MAX_ROWS` lowered to 50k and a scale test added.

**Ask reliability (G7 P0):** With the real 3B local model, "groceries in September" returned "couldn't find" while No-AI mode answered correctly — the model's wrong category/one-day date window was overriding the rules. Now: rules win wherever they matched; the AI only fills blanks; nonsense windows (< 6 days, end before start, future) are rejected; and if the AI-assisted query finds nothing but the rules find something, the rules answer is used. Unrecognised questions get "I didn't understand" instead of a confident grand total. Verified against the real model.

**Importer correctness (G8):** header matching is now whole-word and never picks a Balance column as the amount ("Total Balance", "Value Date" were being used as amounts); a `Type` column only drives the sign when its values look like Debit/Credit words (POS/ACH no longer disables sign inference); sign flip is decided by format, not file length, so a short export and a long one agree (idempotency restored); numeric dates use one style per file (no more mixed D/M and M/D); `12,5` parses as 12.5; impossible dates (before 1990, > 1 year ahead) are skipped with a warning instead of crashing the dashboard; CSV field-size and NUL errors are handled.

**Privacy (G8):** `/api/status` no longer probes Ollama in No-AI/cloud modes (only when Settings/first-run asks); merchant names are scrubbed of numbers/amounts before storage; P2P payees (Zelle/Venmo/PayPal names) and anything numeric are never sent to the AI; the question prompt uses the wall-clock date, not the newest transaction date; a CSRF guard rejects cross-site POST/DELETE (Origin / Sec-Fetch-Site); config and DB files are created with `600` from the start; CSV export neutralises spreadsheet formulas.

**Usability (G7):** phone tab bar no longer collapses; currency symbol setting; "flipped the signs" notice now reaches the UI; Settings explains when environment variables override saved settings; "on pace" hidden when data is stale; Ask shows a note when the AI option is down; "Show the transactions behind this answer" now lists up to 500; fee rules cover "Monthly Service Fee"; export's account column falls back to the source file; docs corrected (no "hover", missing error messages added).

**Accepted (documented, not changed):**
- No currency conversion; the symbol is display-only.
- Transactions tab filters in Python per keystroke (debounced 250 ms); fine up to tens of thousands of rows.
- Chrome logs a console line for any 4xx; the UI test filters that specific line and checks the HTTP status directly.
- `uvicorn[standard]` is heavier than needed; kept for consistency with the sister projects.

## G9 record — real local model

- Model: `llama3.2:3b` via Ollama on an 8-core CPU, machine under test load.
- "How much did I spend on groceries in September?" → correct ($332.08, 4 transactions). "Did I pay netflix in October?" → correct. "how much on takeout since summer started" → correct after the safety net.
- "Let the AI name them" on a German bank export: `REWE MARKT` → Groceries (correct).
- Per-question latency 8–17 s on this CPU; No-AI mode is instant.

## Re-running everything

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt && python -m playwright install chromium
pytest                                   # G1, G2, G4, G6
bash scripts/fresh_install_test.sh       # G3
python scripts/readability_check.py      # G5
python scripts/make_samples.py           # regenerate example data (deterministic)
```
