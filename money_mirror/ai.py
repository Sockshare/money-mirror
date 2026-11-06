"""Where the AI (optional) is used in Money Mirror — and where it is NOT.

The AI only ever sees:
  1. a short list of merchant NAMES it is asked to categorize, and
  2. your plain-English question, so it can turn it into a structured query.

It never sees amounts, dates, or your transaction list. All math is done locally.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date

from .analysis import parse_question
from .categorize import CATEGORIES
from .config import Settings
from .llm import ProviderError, extract_json, get_provider

log = logging.getLogger("money_mirror.ai")

CATEGORIZE_SYSTEM = "You sort merchant names into spending categories. Answer with one JSON object only."
CATEGORIZE_USER = """Categories (use these exact names):
{cats}

Merchants:
{merchants}

Return JSON like {{"Merchant Name": "Category", ...}} using the category "Other" only if truly unknown."""

QUESTION_SYSTEM = "You turn a question about personal spending into a small JSON query. JSON only."
QUESTION_USER = """Today is {today}. Categories: {cats}.
Known merchants (partial list): {merchants}

Question: "{q}"

Return JSON:
{{"agg": "sum|count|avg|max|list", "category": "<exact category or null>", "merchant": "<merchant name in lowercase or null>",
  "start": "YYYY-MM-DD or null", "end": "YYYY-MM-DD or null", "income": true_or_false}}"""


P2P = re.compile(r"\b(zelle|venmo|cash app|paypal|interac|e-transfer|wire|transfer)\b", re.I)


def _safe_names(merchants: list[str]) -> list[str]:
    """Drop person-to-person payees and anything that still looks like a number."""
    out = []
    for m in merchants:
        if P2P.search(m) or re.search(r"\d{3,}|\d+[.,]\d", m):
            continue
        out.append(m)
    return out


def categorize_merchants(merchants: list[str], settings: Settings) -> dict[str, str]:
    provider = get_provider(settings)
    merchants = _safe_names(merchants)
    if provider.name == "offline" or not merchants:
        return {}
    out: dict[str, str] = {}
    for i in range(0, len(merchants), 25):
        batch = merchants[i : i + 25]
        try:
            raw = provider.complete(CATEGORIZE_SYSTEM, CATEGORIZE_USER.format(cats=", ".join(CATEGORIES), merchants="\n".join(batch)), want_json=True)
        except ProviderError as exc:
            log.warning("AI categorize failed: %s", exc)
            break
        parsed = extract_json(raw) or {}
        for k, v in parsed.items():
            if isinstance(v, str) and v in CATEGORIES and v != "Other":
                out[str(k).lower()] = v
    return out


def question_to_spec(q: str, today: date, categories: list[str], merchants: list[str], settings: Settings) -> tuple[dict, str]:
    """Returns (spec, engine). Falls back to the offline parser.

    `today` (the newest transaction date) is used for the LOCAL parser only. The prompt gets the
    wall-clock date so the model learns nothing about the user's transactions; merchant names
    exclude P2P payees and anything numeric.
    """
    base = parse_question(q, today, categories, merchants)
    provider = get_provider(settings)
    if provider.name == "offline":
        return base, "offline"
    safe = _safe_names(merchants)
    try:
        raw = provider.complete(
            QUESTION_SYSTEM,
            QUESTION_USER.format(today=date.today().isoformat(), cats=", ".join(categories), merchants=", ".join(safe[:80]), q=q.replace('"', "'")[:300]),
            want_json=True,
        )
    except ProviderError as exc:
        log.warning("AI question failed: %s", exc)
        return base, "offline"
    parsed = extract_json(raw)
    if not parsed:
        return base, "offline"
    # Small local models are often WORSE than the rules at this. So: rules win wherever they
    # matched something; the AI only fills in the blanks, and its suggestions are sanity-checked.
    spec = dict(base)
    used_ai = False
    matched = set(base.get("matched", []))
    agg = str(parsed.get("agg", "")).lower()
    if "agg" not in matched and agg in ("count", "avg", "max", "list"):
        spec["agg"] = agg
        used_ai = True
    cat = parsed.get("category")
    if not (matched & {"category", "merchant", "keyword"}) and isinstance(cat, str) and cat in categories:
        spec["category"] = cat
        used_ai = True
    merch = parsed.get("merchant")
    if not (matched & {"category", "merchant", "keyword"}) and isinstance(merch, str) and merch.strip():
        ml = merch.strip().lower()
        if any(ml == m.lower() or m.lower().startswith(ml) or ml in m.lower() for m in merchants):
            spec["merchant"] = ml
            used_ai = True
    if "time" not in matched:
        ai_start = ai_end = None
        for k, v in (("start", parsed.get("start")), ("end", parsed.get("end"))):
            if isinstance(v, str) and len(v) >= 10:
                try:
                    d = date.fromisoformat(v[:10])
                    if k == "start":
                        ai_start = d
                    else:
                        ai_end = d
                except ValueError:
                    pass
        # Reject nonsense windows (a single day, end before start, far future).
        if ai_start and ai_end and (ai_end < ai_start or (ai_end - ai_start).days < 6):
            ai_start = ai_end = None
        if ai_start and ai_start <= date.today():
            spec["start"], used_ai = ai_start, True
        if ai_end and ai_end <= date.today():
            spec["end"], used_ai = ai_end, True
    if "income" not in matched and isinstance(parsed.get("income"), bool) and parsed["income"]:
        spec["income"], used_ai = True, True
    if used_ai:
        spec["understood"] = True
    return spec, (provider.name if used_ai else "offline")
