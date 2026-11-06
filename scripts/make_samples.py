#!/usr/bin/env python3
"""Generate the two sample CSVs in samples/. Deterministic (seeded) so tests are stable.

    python scripts/make_samples.py

Checking account: "Date,Description,Amount,Balance"  (spending negative)
Credit card:      "Transaction Date,Posted Date,Description,Category,Debit,Credit"  (separate columns)
Includes on purpose: a streaming price increase, a double charge, a gym nobody uses,
an overdraft fee, a big one-off purchase, and payroll.
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(7)
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"
START = date(2026, 5, 1)
END = date(2026, 11, 5)


def days():
    d = START
    while d <= END:
        yield d
        d += timedelta(days=1)


def money(lo, hi):
    return round(random.uniform(lo, hi), 2)


checking: list[tuple[date, str, float]] = []
card: list[tuple[date, str, str, float]] = []

# --- recurring on checking ---
for d in days():
    if d.day == 1:
        checking.append((d, "MAPLEWOOD PROPERTIES RENT", -1450.00))
    if d.day in (15, 30) or (d.month == 2 and d.day == 28):
        checking.append((d, "NORTHSTAR ANALYTICS PAYROLL DIRECT DEP", 2612.44))
    if d.day == 3:
        checking.append((d, "CITY POWER & LIGHT ELECTRIC", -money(68, 142)))
    if d.day == 9:
        checking.append((d, "T-MOBILE *RECURRING", -85.00))
    if d.day == 12:
        checking.append((d, "XFINITY INTERNET 8004 AUTOPAY", -79.99))
    if d.day == 20:
        checking.append((d, "GEICO AUTO INS PREMIUM", -138.50))
    if d.day == 24:
        checking.append((d, "PLANET FITNESS CLUB FEES", -24.99))        # never used...
    if d.day == 26:
        checking.append((d, "ONLINE TRANSFER TO SAVINGS XXXX4471", -300.00))
    if d.day == 27:
        checking.append((d, "AUTOPAY CREDIT CARD PMT VISA", -round(random.uniform(900, 1400), 2)))
    if d.weekday() == 5 and random.random() < 0.8:
        checking.append((d, "ATM WITHDRAWAL 00342 MAIN ST", -float(random.choice([40, 60, 80, 100]))))
    if d.weekday() in (1, 4) and random.random() < 0.6:
        checking.append((d, f"TRADER JOE'S #{random.randint(100, 999)} SPRINGFIELD IL", -money(28, 96)))
    if d.weekday() == 6 and random.random() < 0.5:
        checking.append((d, "COSTCO WHSE #0412", -money(110, 240)))
checking.append((date(2026, 8, 18), "OVERDRAFT FEE", -35.00))
checking.append((date(2026, 7, 2), "ZELLE PAYMENT FROM SAM OKAFOR", 120.00))
checking.append((date(2026, 9, 14), "IRS TREAS 310 TAX REF", 412.00))

# --- card ---
streaming_price = 15.49
for d in days():
    if d.day == 5:
        if d >= date(2026, 9, 1):
            streaming_price = 17.99                                        # price hike
        card.append((d, "NETFLIX.COM", "Entertainment", -streaming_price))
    if d.day == 7:
        card.append((d, "SPOTIFY USA", "Entertainment", -11.99))
    if d.day == 11:
        card.append((d, "APPLE.COM/BILL", "Shopping", -2.99))
    if d.day == 16:
        card.append((d, "AMAZON PRIME*2K4HJ1", "Shopping", -14.99))
    if d.day == 19:
        card.append((d, "CHATGPT SUBSCRIPTION OPENAI", "Services", -20.00))
    if d.day == 22:
        card.append((d, "NYTIMES*DIGITAL", "Entertainment", -17.00))
    if d.weekday() < 5 and random.random() < 0.55:
        card.append((d, f"STARBUCKS STORE {random.randint(10000, 99999)}", "Dining", -money(4.25, 9.8)))
    if random.random() < 0.33:
        card.append((d, random.choice(["DOORDASH*CHIPOTLE", "UBER EATS", "SQ *TAQUERIA LUNA", "PANERA BREAD #4421", "TST* RAMEN HOUSE", "GRUBHUB*THAIKITCHEN"]), "Dining", -money(13, 48)))
    if random.random() < 0.18:
        card.append((d, random.choice(["AMAZON.COM*1A2B3C", "AMZN MKTP US*9Z8Y7", "TARGET 00021144", "WALMART.COM"]), "Shopping", -money(12, 140)))
    if random.random() < 0.12:
        card.append((d, "SHELL OIL 57442114", "Gas", -money(38, 72)))
    if random.random() < 0.08:
        card.append((d, "UBER *TRIP", "Travel", -money(9, 34)))
    if random.random() < 0.05:
        card.append((d, "CVS/PHARMACY #08821", "Health", -money(8, 60)))
    if random.random() < 0.03:
        card.append((d, "AMC THEATRES 2217", "Entertainment", -money(14, 42)))
card.append((date(2026, 10, 3), "SQ *TAQUERIA LUNA", "Dining", -27.40))
card.append((date(2026, 10, 3), "SQ *TAQUERIA LUNA", "Dining", -27.40))              # double charge
card.append((date(2026, 7, 21), "BEST BUY 00012283", "Shopping", -899.99))              # big one-off
card.append((date(2026, 6, 14), "DELTA AIR 0062211445", "Travel", -486.20))
card.append((date(2026, 8, 2), "AMAZON.COM REFUND", "Shopping", 42.17))
for m in range(5, 12):
    if date(2026, m, 27) <= END:
        card.append((date(2026, m, 27), "PAYMENT - THANK YOU", "Payment", 0.0))

OUT.mkdir(exist_ok=True)
with (OUT / "sample_checking.csv").open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Date", "Description", "Amount", "Balance"])
    bal = 3120.55
    for d, desc, amt in sorted(checking, key=lambda r: r[0]):
        bal = round(bal + amt, 2)
        w.writerow([d.strftime("%m/%d/%Y"), desc, f"{amt:.2f}", f"{bal:.2f}"])

with (OUT / "sample_credit_card.csv").open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Transaction Date", "Posted Date", "Description", "Category", "Debit", "Credit"])
    for d, desc, cat, amt in sorted(card, key=lambda r: r[0]):
        if amt == 0.0:
            w.writerow([d.isoformat(), d.isoformat(), desc, cat, "", f"{1100.00:.2f}"])
        elif amt < 0:
            w.writerow([d.isoformat(), (d + timedelta(days=1)).isoformat(), desc, cat, f"{-amt:.2f}", ""])
        else:
            w.writerow([d.isoformat(), d.isoformat(), desc, cat, "", f"{amt:.2f}"])

print(f"wrote {len(checking)} checking rows and {len(card)} card rows to {OUT}")
