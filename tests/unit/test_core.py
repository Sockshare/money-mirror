"""G1 — unit tests: importer, merchant cleaning, categorizer, analysis, question parser."""

from datetime import date

import pytest

from money_mirror import analysis
from money_mirror.categorize import CATEGORIES, categorize, clean_merchant
from money_mirror.importer import import_csv, parse_amount, parse_date


# ---------------- amounts & dates ----------------
@pytest.mark.parametrize("raw,expected", [
    ("$1,234.56", 1234.56), ("-12.00", -12.0), ("(45.00)", -45.0), ("12,34", 12.34), ("1.234,56", 1234.56),
    ("CR 10.00", 10.0), ("10.00 DR", -10.0), ("", None), ("abc", None), ("+5", 5.0), ("1,234", 1234.0),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("2026-05-01", date(2026, 5, 1)), ("05/01/2026", date(2026, 5, 1)), ("5/1/26", date(2026, 5, 1)),
    ("01.05.2026", date(2026, 5, 1)), ("May 1, 2026", date(2026, 5, 1)), ("1 May 2026", date(2026, 5, 1)),
    ("2026-05-01T10:00:00Z", date(2026, 5, 1)), ("nonsense", None),
])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_parse_date_prefers_dmy_when_asked():
    assert parse_date("03/04/2026", prefer_dmy=True) == date(2026, 4, 3)
    assert parse_date("03/04/2026") == date(2026, 3, 4)


# ---------------- importer ----------------
def test_import_signed_amount_csv():
    csv = b"Date,Description,Amount,Balance\n05/01/2026,RENT,-1450.00,100\n05/02/2026,PAYROLL,2000.00,2100\n"
    r = import_csv(csv)
    assert r.ok and len(r.transactions) == 2
    assert r.transactions[0].amount == -1450.0 and r.transactions[1].amount == 2000.0
    assert r.mapping["amount"] == "Amount"


def test_import_debit_credit_columns():
    csv = b"Transaction Date,Posted Date,Description,Category,Debit,Credit\n2026-05-01,2026-05-02,STARBUCKS,Dining,5.06,\n2026-05-03,2026-05-03,REFUND,Shopping,,42.17\n"
    r = import_csv(csv)
    assert r.ok and [t.amount for t in r.transactions] == [-5.06, 42.17]
    assert r.transactions[0].raw_category == "Dining"


def test_import_positive_spending_gets_flipped():
    rows = "\n".join(f"2026-05-{i:02d},SHOP {i},{10 + i}.00" for i in range(1, 12))
    r = import_csv(f"Date,Description,Amount\n{rows}\n".encode())
    assert r.ok and r.sign_flipped and all(t.amount < 0 for t in r.transactions)


def test_import_type_column_decides_sign():
    csv = b"Date,Description,Amount,Type\n2026-05-01,COFFEE,4.50,Debit\n2026-05-02,SALARY,900,Credit\n"
    r = import_csv(csv)
    assert [t.amount for t in r.transactions] == [-4.5, 900.0]


def test_import_dmy_dates_detected():
    csv = b"Date,Description,Amount\n13/05/2026,A,-1\n14/05/2026,B,-2\n03/06/2026,C,-3\n"
    r = import_csv(csv)
    assert [t.date for t in r.transactions] == [date(2026, 5, 13), date(2026, 5, 14), date(2026, 6, 3)]


def test_import_preamble_and_semicolons_and_european_decimals():
    csv = "Account: 1234\nExported: today\n\nDatum;Beschreibung;Betrag\n01.05.2026;REWE MARKT;-45,30\n02.05.2026;GEHALT;2.500,00\n".encode("cp1252")
    r = import_csv(csv)
    assert r.ok and [t.amount for t in r.transactions] == [-45.3, 2500.0]


def test_import_headerless_guess():
    csv = b"2026-05-01,SOME SHOP,-10.00\n2026-05-02,OTHER SHOP,-20.00\n2026-05-03,THIRD,-30.00\n2026-05-04,FOURTH,-1.00\n"
    r = import_csv(csv)
    # first row is consumed as a header, remaining 3 parsed via content guessing
    assert r.ok and len(r.transactions) == 3 and any("guessed" in w for w in r.warnings)


def test_import_errors_are_friendly():
    assert "empty" in import_csv(b"").error
    assert "No table" in import_csv(b"just some words\nno commas here").error
    assert "amount" in import_csv(b"Date,Description,Note\n2026-01-01,x,y\n").error.lower()


def test_import_samples(samples_dir):
    for name in ("sample_checking.csv", "sample_credit_card.csv"):
        r = import_csv((samples_dir / name).read_bytes())
        assert r.ok and len(r.transactions) > 100 and not r.warnings, name


# ---------------- merchants & categories ----------------
@pytest.mark.parametrize("raw,expected", [
    ("SQ *BLUE BOTTLE COFFEE 0412 SAN FRANCISCO CA 11/02", "Blue Bottle Coffee"),
    ("TRADER JOE'S #254 SPRINGFIELD IL", "Trader Joe's"),
    ("AMZN MKTP US*9Z8Y7", "Amazon"), ("AMAZON PRIME*2K4HJ1", "Amazon Prime"),
    ("NETFLIX.COM", "Netflix.com"),
    ("ATM WITHDRAWAL 00342 MAIN ST", "ATM Withdrawal"), ("PAYMENT - THANK YOU", "Card Payment"),
])
def test_clean_merchant(raw, expected):
    assert clean_merchant(raw) == expected


@pytest.mark.parametrize("desc,cat", [
    ("NETFLIX.COM", "Subscriptions & Streaming"), ("TRADER JOE'S #254", "Groceries"), ("STARBUCKS STORE 123", "Coffee & Snacks"),
    ("UBER EATS", "Restaurants & Takeout"), ("UBER *TRIP", "Rideshare & Taxi"), ("SHELL OIL 123", "Transport & Fuel"),
    ("MAPLEWOOD PROPERTIES RENT", "Housing & Rent"), ("OVERDRAFT FEE", "Fees & Interest"), ("NORTHSTAR PAYROLL DIRECT DEP", "Income"),
    ("ONLINE TRANSFER TO SAVINGS", "Transfers"), ("AUTOPAY CREDIT CARD PMT", "Loan & Credit Card Payments"), ("PLANET FITNESS", "Fitness"),
    ("CVS/PHARMACY #0882", "Health & Pharmacy"), ("GEICO AUTO INS", "Insurance"), ("ZZZ UNKNOWN LLC", "Other"),
])
def test_categorize(desc, cat):
    assert categorize(desc, clean_merchant(desc), -10.0) == cat


def test_custom_rule_wins():
    assert categorize("ZZZ UNKNOWN LLC", "Zzz Unknown LLC", -10.0, custom_rules={"zzz unknown llc": "Kids & Pets"}) == "Kids & Pets"


def test_bank_category_used_as_fallback():
    assert categorize("MYSTERY PLACE", "Mystery Place", -10.0, raw_category="Dining") == "Restaurants & Takeout"


def test_all_rule_targets_are_real_categories():
    from money_mirror.categorize import RULES

    assert all(c in CATEGORIES for _, c in RULES)


# ---------------- analysis ----------------
def _txns():
    out, i = [], 0
    for m in range(5, 11):
        for d, desc, amt, cat in [(5, "Netflix", -15.49 if m < 9 else -17.99, "Subscriptions & Streaming"), (1, "Rent Co", -1000, "Housing & Rent"), (15, "Payroll", 2500, "Income"), (20, "Grocer", -80 - m, "Groceries")]:
            i += 1
            out.append({"id": f"t{i}", "date": f"2026-{m:02d}-{d:02d}", "description": desc, "merchant": desc, "amount": amt, "category": cat, "account": ""})
    out.append({"id": "dup1", "date": "2026-10-03", "description": "Taco", "merchant": "Taco", "amount": -27.4, "category": "Restaurants & Takeout", "account": ""})
    out.append({"id": "dup2", "date": "2026-10-03", "description": "Taco", "merchant": "Taco", "amount": -27.4, "category": "Restaurants & Takeout", "account": ""})
    out.append({"id": "fee", "date": "2026-08-18", "description": "Overdraft", "merchant": "Overdraft Fee", "amount": -35, "category": "Fees & Interest", "account": ""})
    return sorted(out, key=lambda t: t["date"])


def test_overview_numbers():
    o = analysis.overview(_txns(), today=date(2026, 10, 20))
    assert o["total_income"] == 2500 * 6
    assert o["top_categories"][0]["category"] == "Housing & Rent"
    assert o["this_month"]["label"] == "2026-10" and o["last_month"]["label"] == "2026-09"
    assert o["compare"] == {"from": "2026-08", "to": "2026-09"}  # partial month -> compare complete months


def test_subscriptions_and_price_change():
    subs = analysis.subscriptions(_txns(), today=date(2026, 10, 20))
    names = {s["merchant"]: s for s in subs}
    assert "Netflix" in names and names["Netflix"]["cadence"] == "monthly" and names["Netflix"]["status"] == "active"
    assert names["Netflix"]["price_change"]["from"] == 15.49 and names["Netflix"]["price_change"]["to"] == 17.99
    assert "Grocer" not in names  # varying everyday spend is not a subscription


def test_alerts_detect_duplicate_fee_and_hike():
    types = {a["type"] for a in analysis.alerts(_txns(), today=date(2026, 10, 20))}
    assert {"duplicate", "fee", "price_increase"} <= types


def test_question_parser_and_query():
    tx = _txns()
    today = date(2026, 10, 20)
    merchants = sorted({t["merchant"] for t in tx})
    spec = analysis.parse_question("how much did I spend on groceries since August?", today, CATEGORIES, merchants)
    assert spec["category"] == "Groceries" and spec["start"] == date(2026, 8, 1)
    res = analysis.run_query(tx, spec)
    assert res["count"] == 3 and res["total"] == 88 + 89 + 90
    spec = analysis.parse_question("how many times did I pay netflix?", today, CATEGORIES, merchants)
    assert spec["agg"] == "count" and spec["merchant"] == "netflix"
    assert analysis.run_query(tx, spec)["count"] == 6
    spec = analysis.parse_question("how much did I earn last month", today, CATEGORIES, merchants)
    assert spec["income"] and spec["start"] == date(2026, 9, 1) and spec["end"] == date(2026, 9, 30)
    assert analysis.run_query(tx, spec)["total"] == 2500
    assert "couldn't find" in analysis.phrase_answer({"category": "Travel"}, analysis.run_query(tx, {"category": "Travel"}))


def test_analysis_handles_empty():
    assert analysis.overview([])["empty"] is True
    assert analysis.subscriptions([]) == [] and analysis.alerts([]) == []


# ---------------- regressions from independent code review ----------------
def test_header_matching_is_whole_word_and_skips_balance():
    csv = b"Transaction Date,Payee,Total Balance,Amount\n2026-05-01,SHOP,100.00,-5.00\n2026-05-02,SHOP2,95.00,-5.00\n"
    r = import_csv(csv)
    assert r.mapping["date"] == "Transaction Date" and r.mapping["description"] == "Payee" and r.mapping["amount"] == "Amount"
    assert [t.amount for t in r.transactions] == [-5.0, -5.0]


def test_type_column_with_pos_ach_does_not_disable_sign_logic():
    rows = "\n".join(f"2026-05-{i:02d},SHOP {i},{i}.00,{'POS' if i % 2 else 'ACH'}" for i in range(1, 9))
    r = import_csv(f"Date,Description,Amount,Type\n{rows}\n".encode())
    assert r.sign_flipped and all(t.amount < 0 for t in r.transactions)


def test_dash_dates_consistent_within_file():
    r = import_csv(b"Date,Description,Amount\n05-01-2026,A,-1\n05-13-2026,B,-2\n")
    assert [t.date for t in r.transactions] == [date(2026, 5, 1), date(2026, 5, 13)]


def test_short_all_positive_export_is_normalised():
    r = import_csv(b"Date,Description,Amount\n2026-05-01,SHOP,5.00\n2026-05-02,SHOP,6.00\n")
    assert r.sign_flipped and all(t.amount < 0 for t in r.transactions)


def test_decimal_comma_one_digit():
    assert parse_amount("12,5") == 12.5


def test_extreme_dates_skipped_with_warning():
    r = import_csv(b"Date,Description,Amount\n0001-01-05,A,-1\n9999-12-01,B,-2\n2026-05-01,C,-3\n")
    assert len(r.transactions) == 1 and any("impossible date" in w for w in r.warnings)


def test_huge_field_does_not_crash():
    big = "x" * 200_000
    r = import_csv(f"Date,Description,Amount\n2026-05-01,{big},-1.00\n2026-05-02,B,-2.00\n".encode())
    assert r.ok and len(r.transactions) == 2


def test_merchant_names_never_contain_amounts():
    for desc in ("PAYPAL *JOHNSMITH 12.99", "CHECK 1234 $45.00", "ZELLE TO JANE DOE 50.00"):
        assert not any(ch.isdigit() for ch in clean_merchant(desc)), desc


def test_alerts_scale():
    import time

    txns = [{"id": f"t{i}", "date": f"2024-{1 + i % 12:02d}-{1 + i % 28:02d}", "description": f"S{i}", "merchant": f"Shop {i % 300}", "amount": -(1 + i % 90), "category": "Shopping", "account": ""} for i in range(20000)]
    txns.sort(key=lambda t: t["date"])
    t0 = time.time()
    analysis.alerts(txns, today=date(2024, 12, 28))
    analysis.overview(txns, today=date(2024, 12, 28))
    assert time.time() - t0 < 5
