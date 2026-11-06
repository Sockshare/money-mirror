"""Insights from a list of categorized transactions. Pure Python, no AI.

    overview(txns)        totals, this month vs last, top categories/merchants
    monthly(txns)         per-month in/out/net + per-category
    subscriptions(txns)   recurring charges, their cadence, price changes, "forgotten" ones
    alerts(txns)          duplicates, price hikes, unusually large charges, new recurring charges
    answer(txns, q)       plain-English question -> numbers (offline parser)
"""

from __future__ import annotations

import calendar
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta

SPEND_EXCLUDE = {"Transfers", "Income", "Loan & Credit Card Payments"}  # not "spending" for totals


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def _safe_prev_month(d: date) -> date:
    try:
        return d.replace(day=1) - timedelta(days=1)
    except OverflowError:
        return d


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _money(v: float) -> float:
    return round(v, 2)


def spending(txns: list[dict]) -> list[dict]:
    return [t for t in txns if t["amount"] < 0 and t["category"] not in SPEND_EXCLUDE]


# ---------------------------------------------------------------------------
def overview(txns: list[dict], today: date | None = None) -> dict:
    if not txns:
        return {"empty": True}
    today = today or _d(txns[-1]["date"])
    first, last = _d(txns[0]["date"]), _d(txns[-1]["date"])
    sp = spending(txns)
    income = [t for t in txns if t["category"] == "Income"]
    this_m = _month(today)
    prev = _safe_prev_month(today)
    last_m = _month(prev)
    partial = today.day < 25  # current month isn't done yet
    # For month-vs-month comparisons use the two most recent COMPLETE months when the current one is partial.
    if partial:
        cmp_to, cmp_from = last_m, _month(_safe_prev_month(prev))
    else:
        cmp_to, cmp_from = this_m, last_m

    def tot(items, m=None):
        return _money(sum(-t["amount"] for t in items if m is None or t["date"][:7] == m))

    by_cat = defaultdict(float)
    for t in sp:
        by_cat[t["category"]] += -t["amount"]
    by_cat_this = defaultdict(float)
    by_cat_last = defaultdict(float)
    for t in sp:
        if t["date"][:7] == cmp_to:
            by_cat_this[t["category"]] += -t["amount"]
        elif t["date"][:7] == cmp_from:
            by_cat_last[t["category"]] += -t["amount"]
    by_merchant = defaultdict(lambda: [0.0, 0])
    for t in sp:
        by_merchant[t["merchant"]][0] += -t["amount"]
        by_merchant[t["merchant"]][1] += 1

    months = sorted({t["date"][:7] for t in sp})
    full_months = [m for m in months if not (partial and m == this_m)] or months
    avg_month = _money(sum(tot(sp, m) for m in full_months) / max(1, len(full_months)))
    # Days elapsed in the current month for a "pace" estimate (meaningless in the first days)
    days_in = calendar.monthrange(today.year, today.month)[1]
    pace = _money(tot(sp, this_m) / max(1, today.day) * days_in) if 10 <= today.day < days_in else None

    return {
        "empty": False,
        "first_date": first.isoformat(),
        "last_date": last.isoformat(),
        "months_covered": len(months),
        "full_months": len(full_months),
        "compare": {"from": cmp_from, "to": cmp_to},
        "day_of_month": today.day,
        "transactions": len(txns),
        "total_spent": tot(sp),
        "total_income": _money(sum(t["amount"] for t in income)),
        "avg_month_spend": avg_month,
        "this_month": {"label": this_m, "spent": tot(sp, this_m), "income": _money(sum(t["amount"] for t in income if t["date"][:7] == this_m)), "pace": pace},
        "last_month": {"label": last_m, "spent": tot(sp, last_m), "income": _money(sum(t["amount"] for t in income if t["date"][:7] == last_m))},
        "top_categories": [{"category": c, "amount": _money(v), "share": round(v / max(1e-9, tot(sp)) * 100, 1)} for c, v in sorted(by_cat.items(), key=lambda x: -x[1])[:8]],
        "category_change": sorted(
            [{"category": c, "this": _money(by_cat_this.get(c, 0)), "last": _money(by_cat_last.get(c, 0)), "diff": _money(by_cat_this.get(c, 0) - by_cat_last.get(c, 0))} for c in set(by_cat_this) | set(by_cat_last)],
            key=lambda x: -abs(x["diff"]),
        )[:6],
        "top_merchants": [{"merchant": m, "amount": _money(v[0]), "count": v[1]} for m, v in sorted(by_merchant.items(), key=lambda x: -x[1][0])[:10]],
        "uncategorized": sum(1 for t in txns if t["category"] == "Other"),
    }


def monthly(txns: list[dict]) -> list[dict]:
    out: dict[str, dict] = {}
    for t in txns:
        m = t["date"][:7]
        row = out.setdefault(m, {"month": m, "spent": 0.0, "income": 0.0, "categories": defaultdict(float)})
        if t["category"] == "Income":
            row["income"] += t["amount"]
        elif t["amount"] < 0 and t["category"] not in SPEND_EXCLUDE:
            row["spent"] += -t["amount"]
            row["categories"][t["category"]] += -t["amount"]
    result = []
    for m in sorted(out):
        r = out[m]
        result.append({"month": m, "spent": _money(r["spent"]), "income": _money(r["income"]), "net": _money(r["income"] - r["spent"]), "categories": {k: _money(v) for k, v in sorted(r["categories"].items(), key=lambda x: -x[1])}})
    return result


# ---------------------------------------------------------------------------
def _cadence(days: list[int]) -> str | None:
    if not days:
        return None
    med = statistics.median(days)
    if 26 <= med <= 35:
        return "monthly"
    if 6 <= med <= 8:
        return "weekly"
    if 12 <= med <= 16:
        return "every 2 weeks"
    if 85 <= med <= 95:
        return "every 3 months"
    if 350 <= med <= 380:
        return "yearly"
    return None


EVERYDAY_CATS = {"Groceries", "Restaurants & Takeout", "Coffee & Snacks", "Transport & Fuel", "Rideshare & Taxi", "Shopping", "Cash", "Health & Pharmacy", "Entertainment", "Travel", "Personal Care", "Kids & Pets"}


def subscriptions(txns: list[dict], today: date | None = None) -> list[dict]:
    """Recurring charges: same merchant, regular spacing, similar amount."""
    today = today or (_d(txns[-1]["date"]) if txns else date.today())
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in txns:
        if t["amount"] < 0 and t["category"] not in ("Transfers", "Loan & Credit Card Payments", "Cash", "Income"):
            groups[t["merchant"]].append(t)
    subs = []
    for merchant, items in groups.items():
        if len(items) < 3:
            # yearly: accept 2 charges ~a year apart
            if len(items) == 2:
                gap = (_d(items[1]["date"]) - _d(items[0]["date"])).days
                if 350 <= gap <= 380 and abs(items[0]["amount"] - items[1]["amount"]) / max(1, abs(items[0]["amount"])) < 0.15:
                    pass
                else:
                    continue
            else:
                continue
        items.sort(key=lambda t: t["date"])
        dates = [_d(t["date"]) for t in items]
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        cad = _cadence(gaps)
        if not cad:
            continue
        amounts = [-t["amount"] for t in items]
        med_amt = statistics.median(amounts)
        # amounts must be stable-ish (allow price changes but not wildly variable like groceries)
        spread = (max(amounts) - min(amounts)) / max(1e-9, med_amt)
        if items[-1]["category"] in EVERYDAY_CATS and spread > 0.05:
            continue  # weekly groceries/fuel are habits, not subscriptions
        if spread > 0.6 and cad != "monthly":
            continue
        if spread > 0.6:
            # monthly but variable: utilities/phone are still "recurring bills", keep but flag variable
            variable = True
        else:
            variable = False
        last_amt = amounts[-1]
        first_amt = amounts[0]
        price_change = None
        # detect a step change: compare last 2 vs earlier
        if len(amounts) >= 3 and not variable:
            earlier = statistics.median(amounts[:-1])
            if last_amt > earlier * 1.04 and last_amt - earlier >= 0.5:
                price_change = {"from": _money(earlier), "to": _money(last_amt), "pct": round((last_amt - earlier) / earlier * 100, 1)}
        per_year = {"monthly": 12, "weekly": 52, "every 2 weeks": 26, "every 3 months": 4, "yearly": 1}[cad]
        expected_gap = {"monthly": 31, "weekly": 7, "every 2 weeks": 14, "every 3 months": 92, "yearly": 366}[cad]
        days_since = (today - dates[-1]).days
        status = "active" if days_since <= expected_gap * 1.6 else "stopped"
        subs.append(
            {
                "merchant": merchant,
                "category": items[-1]["category"],
                "cadence": cad,
                "amount": _money(last_amt),
                "first_amount": _money(first_amt),
                "yearly_cost": _money(last_amt * per_year),
                "charges": len(items),
                "first_date": dates[0].isoformat(),
                "last_date": dates[-1].isoformat(),
                "next_expected": (dates[-1] + timedelta(days=expected_gap)).isoformat() if status == "active" else None,
                "status": status,
                "variable": variable,
                "price_change": price_change,
                "ids": [t["id"] for t in items],
            }
        )
    subs.sort(key=lambda s: (-(s["status"] == "active"), -s["yearly_cost"]))
    return subs


def alerts(txns: list[dict], today: date | None = None) -> list[dict]:
    out: list[dict] = []
    today = today or (_d(txns[-1]["date"]) if txns else date.today())
    sp = [t for t in txns if t["amount"] < 0 and t["category"] not in ("Transfers", "Loan & Credit Card Payments")]

    # 1) Possible duplicate charges: same merchant + same amount within 3 days
    by_key = defaultdict(list)
    for t in sp:
        by_key[(t["merchant"], round(-t["amount"], 2))].append(t)
    for (merchant, amt), items in by_key.items():
        items.sort(key=lambda t: t["date"])
        for a, b in zip(items, items[1:]):
            gap = (_d(b["date"]) - _d(a["date"])).days
            if 0 <= gap <= 3 and amt >= 5:
                out.append({"type": "duplicate", "severity": "high", "title": f"Possible double charge: {merchant} ${amt:,.2f}", "detail": f"Charged on {a['date']} and again on {b['date']} ({gap} day{'s' if gap != 1 else ''} apart). If you only bought once, ask for a refund.", "amount": amt, "ids": [a["id"], b["id"]], "date": b["date"]})

    # 2) Price increases on recurring charges
    for s in subscriptions(txns, today):
        if s["price_change"]:
            pc = s["price_change"]
            out.append({"type": "price_increase", "severity": "medium", "title": f"{s['merchant']} went up {pc['pct']}%", "detail": f"Was ${pc['from']:,.2f}, now ${pc['to']:,.2f} {s['cadence']}. That's about ${(pc['to'] - pc['from']) * {'monthly': 12, 'weekly': 52, 'every 2 weeks': 26, 'every 3 months': 4, 'yearly': 1}[s['cadence']]:,.2f} more per year.", "amount": pc["to"], "ids": s["ids"][-1:], "date": s["last_date"]})
        if s["status"] == "active" and s["charges"] >= 3 and s["category"] in ("Subscriptions & Streaming", "Fitness", "Other") and not s["variable"]:
            out.append({"type": "subscription", "severity": "low", "title": f"Recurring: {s['merchant']} ${s['amount']:,.2f} {s['cadence']}", "detail": f"About ${s['yearly_cost']:,.2f} a year. Still using it?", "amount": s["amount"], "ids": s["ids"][-1:], "date": s["last_date"]})

    # 3) Unusually large charges vs that category's norm (median computed once per category)
    by_cat = defaultdict(list)
    for t in sp:
        by_cat[t["category"]].append(-t["amount"])
    cat_median = {c: statistics.median(v) for c, v in by_cat.items() if len(v) >= 8}
    for t in sp:
        if t["category"] in cat_median:
            med = cat_median[t["category"]]
            amt = -t["amount"]
            if amt >= 100 and amt > med * 4 and t["category"] not in ("Housing & Rent", "Travel", "Taxes & Government", "Insurance"):
                out.append({"type": "large", "severity": "low", "title": f"Big one: {t['merchant']} ${amt:,.2f}", "detail": f"Most {t['category']} charges are around ${med:,.2f}.", "amount": amt, "ids": [t["id"]], "date": t["date"]})

    # 4) Fees
    for t in sp:
        if t["category"] == "Fees & Interest":
            out.append({"type": "fee", "severity": "medium", "title": f"Fee: {t['merchant']} ${-t['amount']:,.2f}", "detail": "Banks often reverse a fee if you call and ask, especially the first time.", "amount": -t["amount"], "ids": [t["id"]], "date": t["date"]})

    sev = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda a: (sev[a["severity"]], a["date"]), reverse=False)
    # newest first within severity
    out.sort(key=lambda a: (sev[a["severity"]], -int(a["date"].replace("-", ""))))
    return out[:60]


# ---------------------------------------------------------------------------
# Plain-English questions (offline). The AI, when enabled, translates harder
# questions into the same QuerySpec and this code runs it — the AI never sees
# the transactions themselves.
# ---------------------------------------------------------------------------
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})


def parse_question(q: str, today: date, categories: list[str], merchants: list[str]) -> dict:
    """Best-effort: {'category':..., 'merchant':..., 'start':..., 'end':..., 'agg': 'sum|count|avg|list|max'}"""
    low = q.lower()
    spec: dict = {"agg": "sum", "start": None, "end": None, "category": None, "merchant": None, "income": False, "matched": []}
    if re.search(r"\b(how many|count|times)\b", low):
        spec["agg"] = "count"
        spec["matched"].append("agg")
    elif re.search(r"\b(average|avg|typical|per month|a month|each month)\b", low):
        spec["agg"] = "avg"
    elif re.search(r"\b(biggest|largest|most expensive|highest)\b", low):
        spec["agg"] = "max"
    elif re.search(r"\b(show|list|which|what did i buy)\b", low):
        spec["agg"] = "list"
    if re.search(r"\b(earn|income|paid me|deposit|salary|made|received)\b", low):
        spec["income"] = True
        spec["matched"].append("income")
    if re.search(r"\b(total|overall|altogether|everything|all my spending|in total)\b", low) or re.fullmatch(r"\s*(how much (did|have) i spen[dt]\??|spending\??)\s*", low):
        spec["matched"].append("total")

    # time range
    y = today.year
    m = re.search(r"\b(since|from|after)\s+([a-z]+)(?:\s+(\d{4}))?", low)
    if m and m.group(2) in MONTHS:
        yy = int(m.group(3)) if m.group(3) else (y if MONTHS[m.group(2)] <= today.month else y - 1)
        spec["start"] = date(yy, MONTHS[m.group(2)], 1)
    if re.search(r"\blast week\b", low):
        spec["start"], spec["end"] = today - timedelta(days=today.weekday() + 7), today - timedelta(days=today.weekday() + 1)
    elif re.search(r"\bthis week\b", low):
        spec["start"] = today - timedelta(days=today.weekday())
    elif re.search(r"\b(yesterday)\b", low):
        spec["start"] = spec["end"] = today - timedelta(days=1)
    elif re.search(r"\btoday\b", low):
        spec["start"] = spec["end"] = today
    elif re.search(r"\bthis month\b", low):
        spec["start"] = today.replace(day=1)
    elif re.search(r"\blast month\b", low):
        last = today.replace(day=1) - timedelta(days=1)
        spec["start"], spec["end"] = last.replace(day=1), last
    elif re.search(r"\bthis year\b", low):
        spec["start"] = date(y, 1, 1)
    elif re.search(r"\blast year\b", low):
        spec["start"], spec["end"] = date(y - 1, 1, 1), date(y - 1, 12, 31)
    elif re.search(r"\blast (\d+|three|six|twelve) months?\b", low):
        n = re.search(r"\blast (\d+|three|six|twelve) months?\b", low).group(1)
        n = {"three": 3, "six": 6, "twelve": 12}.get(n, int(n) if n.isdigit() else 3)
        spec["start"] = (today.replace(day=1) - timedelta(days=30 * (n - 1))).replace(day=1)
    elif re.search(r"\blast (\d+) days?\b", low):
        spec["start"] = today - timedelta(days=int(re.search(r"\blast (\d+) days?\b", low).group(1)))
    elif spec["start"] is None:
        for name, idx in MONTHS.items():
            if re.search(rf"\b(in|during|for)\s+{name}\b", low) or re.search(rf"\b{name}\b", low) and len(name) > 3:
                yy = y if idx <= today.month else y - 1
                ym = re.search(rf"{name}\s+(\d{{4}})", low)
                if ym:
                    yy = int(ym.group(1))
                last_day = calendar.monthrange(yy, idx)[1]
                spec["start"], spec["end"] = date(yy, idx, 1), date(yy, idx, last_day)
                break

    # category / merchant
    synonyms = {
        "eating out": "Restaurants & Takeout", "restaurants": "Restaurants & Takeout", "takeout": "Restaurants & Takeout", "food delivery": "Restaurants & Takeout", "dining": "Restaurants & Takeout",
        "coffee": "Coffee & Snacks", "groceries": "Groceries", "grocery": "Groceries", "gas": "Transport & Fuel", "fuel": "Transport & Fuel", "transport": "Transport & Fuel",
        "uber": None, "rideshare": "Rideshare & Taxi", "rent": "Housing & Rent", "housing": "Housing & Rent", "utilities": "Utilities", "phone": "Phone & Internet", "internet": "Phone & Internet",
        "subscriptions": "Subscriptions & Streaming", "streaming": "Subscriptions & Streaming", "shopping": "Shopping", "amazon": None, "health": "Health & Pharmacy", "pharmacy": "Health & Pharmacy", "medical": "Health & Pharmacy",
        "insurance": "Insurance", "entertainment": "Entertainment", "travel": "Travel", "gym": "Fitness", "fitness": "Fitness", "pets": "Kids & Pets", "kids": "Kids & Pets", "fees": "Fees & Interest", "cash": "Cash",
    }
    for word, cat in synonyms.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            if cat:
                spec["category"] = cat
                break
    if not spec["category"]:
        for cat in categories:
            if cat.lower() in low or cat.lower().split(" & ")[0] in low:
                spec["category"] = cat
                break
    # merchant: longest merchant name that appears in the question
    hit = ""
    for mname in merchants:
        ml = mname.lower()
        if len(ml) >= 3 and re.search(rf"\b{re.escape(ml)}\b", low) and len(ml) > len(hit):
            hit = ml
    if not hit:
        # single-word brand like "amazon", "uber", "netflix" -> matches every merchant starting with it
        for mname in merchants:
            first = mname.lower().split(" ")[0]
            if len(first) >= 4 and re.search(rf"\b{re.escape(first)}\b", low) and len(first) > len(hit):
                hit = first
    if hit:
        spec["merchant"] = hit
    if spec["start"] or spec["end"]:
        spec["matched"].append("time")
    if spec["category"]:
        spec["matched"].append("category")
    if spec["merchant"]:
        spec["matched"].append("merchant")
    # Keyword fallback: a word in the question that appears in some merchant/description (e.g. "netflix" when the
    # merchant is "Netflix.com") -> search descriptions for it.
    if not spec["merchant"] and not spec["category"] and not spec["income"]:
        stop = {"how", "much", "did", "i", "spend", "spent", "spending", "on", "at", "in", "the", "a", "my", "what", "was", "for", "pay", "paid", "to", "last", "this", "month", "year", "week", "since", "and", "of", "do", "have", "money", "total", "all", "per", "each", "every", "from", "with", "about", "average", "biggest", "show", "list", "count", "many", "times", "went", "buy", "bought", "cost", "costs"}
        words = [w for w in re.findall(r"[a-z][a-z'&.-]{3,}", low) if w not in stop and w not in MONTHS]
        for w in words:
            # whole-word match against merchant names only (not substrings like "per" in "Properties")
            if any(re.search(rf"\b{re.escape(w)}", m.lower()) for m in merchants):
                spec["merchant"] = w
                spec["matched"].append("keyword")
                break
    spec["understood"] = bool(spec["matched"])
    return spec


def run_query(txns: list[dict], spec: dict) -> dict:
    start, end = spec.get("start"), spec.get("end")
    if isinstance(start, str):
        start = _d(start)
    if isinstance(end, str):
        end = _d(end)
    items = []
    for t in txns:
        d = _d(t["date"])
        if start and d < start:
            continue
        if end and d > end:
            continue
        if spec.get("income"):
            if t["amount"] <= 0 or t["category"] in ("Transfers", "Loan & Credit Card Payments"):
                continue
        else:
            if t["amount"] >= 0 or t["category"] in SPEND_EXCLUDE:
                continue
        if spec.get("category") and t["category"] != spec["category"]:
            continue
        if spec.get("merchant") and not (t["merchant"].lower() == spec["merchant"] or t["merchant"].lower().startswith(spec["merchant"]) or spec["merchant"] in t["merchant"].lower() or spec["merchant"] in t["description"].lower()):
            continue
        items.append(t)
    total = _money(sum(abs(t["amount"]) for t in items))
    months = len({t["date"][:7] for t in items}) or 1
    agg = spec.get("agg", "sum")
    res = {"spec": {**spec, "start": start.isoformat() if start else None, "end": end.isoformat() if end else None}, "count": len(items), "total": total, "avg_per_month": _money(total / months), "months": months, "items": sorted(items, key=lambda t: t["date"], reverse=True)[:500]}
    if agg == "max" and items:
        big = max(items, key=lambda t: abs(t["amount"]))
        res["max"] = {"merchant": big["merchant"], "amount": _money(abs(big["amount"])), "date": big["date"], "category": big["category"]}
    return res


def phrase_answer(spec: dict, res: dict) -> str:
    if spec.get("understood") is False:
        return ("I didn't understand that one. Try something like: \"how much did I spend on groceries last month\", "
                "\"how many times did I go to Starbucks\", or \"biggest shopping purchase\". I can only answer about spending and income in your imported transactions.")
    what = spec.get("category") or (spec.get("merchant") or "").title() or ("income" if spec.get("income") else "spending")
    when = ""
    if spec.get("start") and spec.get("end"):
        when = f" between {res['spec']['start']} and {res['spec']['end']}"
    elif spec.get("start"):
        when = f" since {res['spec']['start']}"
    verb = "received" if spec.get("income") else "spent"
    if res["count"] == 0:
        return f"I couldn't find any {what} transactions{when}."
    agg = spec.get("agg", "sum")
    if agg == "count":
        return f"{res['count']} {what} transaction{'s' if res['count'] != 1 else ''}{when}, totaling ${res['total']:,.2f}."
    if agg == "avg":
        return f"About ${res['avg_per_month']:,.2f} a month on {what}{when} (${res['total']:,.2f} total over {res['months']} month{'s' if res['months'] != 1 else ''})."
    if agg == "max" and res.get("max"):
        m = res["max"]
        return f"The biggest {what} charge{when} was ${m['amount']:,.2f} at {m['merchant']} on {m['date']}."
    if agg == "list":
        return f"Here are the {min(res['count'], 50)} most recent {what} transactions{when} (${res['total']:,.2f} total)."
    span_days = None
    if res["spec"].get("start") and res["spec"].get("end"):
        span_days = (_d(res["spec"]["end"]) - _d(res["spec"]["start"])).days + 1
    show_avg = res["months"] > 1 and (span_days is None or span_days >= 45)
    return f"You {verb} ${res['total']:,.2f} on {what}{when} across {res['count']} transaction{'s' if res['count'] != 1 else ''}" + (f" — about ${res['avg_per_month']:,.2f} a month." if show_avg else ".")
