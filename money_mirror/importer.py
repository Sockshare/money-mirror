"""Read a bank or credit-card CSV export, whatever the bank's column names are.

Banks disagree on everything: column names, date formats, whether spending is
negative or positive, one amount column vs. separate Debit/Credit columns.
This module sniffs all of that and returns clean transactions:

    Transaction(date, description, amount, raw_category, account)

Sign convention after import:  spending is NEGATIVE, money in is POSITIVE.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

MAX_ROWS = 50_000
MIN_DATE = date(1990, 1, 1)
csv.field_size_limit(1_000_000)

DATE_HEADERS = ("date", "transaction date", "posted date", "posting date", "trans date", "booking date", "value date", "time", "datum", "buchungstag", "fecha", "data")
DESC_HEADERS = ("description", "merchant", "payee", "name", "memo", "details", "narrative", "transaction", "transaction description", "original description", "beschreibung", "verwendungszweck", "concepto", "descripcion", "libelle")
AMOUNT_HEADERS = ("amount", "transaction amount", "value", "sum", "total", "betrag", "montant", "importe", "valor")
DEBIT_HEADERS = ("debit", "withdrawal", "withdrawals", "money out", "paid out", "outflow", "spent", "charge")
CREDIT_HEADERS = ("credit", "deposit", "deposits", "money in", "paid in", "inflow", "received", "payment")
CATEGORY_HEADERS = ("category", "type", "transaction type", "classification")
ACCOUNT_HEADERS = ("account", "account name", "card", "account number")
TYPE_HEADERS = ("type", "transaction type", "debit/credit", "dr/cr", "cr/dr")

DATE_FORMATS = (
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d",
    "%d-%m-%Y", "%m-%d-%Y", "%d.%m.%Y", "%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%d %B %Y",
    "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y%m%d",
)


@dataclass
class Transaction:
    date: date
    description: str
    amount: float          # negative = spending
    raw_category: str = ""
    account: str = ""


@dataclass
class ImportResult:
    transactions: list[Transaction] = field(default_factory=list)
    mapping: dict = field(default_factory=dict)   # which columns were used
    warnings: list[str] = field(default_factory=list)
    skipped: int = 0
    error: str = ""
    sign_flipped: bool = False

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.transactions)


# ---------------------------------------------------------------------------
def _norm(h: str) -> str:
    h = (h or "").strip().lower().replace("\u00e9", "e")
    return re.sub(r"[^a-z/ ]", "", h).strip()


BALANCE_WORDS = ("balance", "running", "available")


def _find(headers: list[str], candidates: tuple[str, ...], exclude: tuple[str, ...] = ()) -> int | None:
    normed = [_norm(h) for h in headers]
    for cand in candidates:            # exact first
        if cand in normed:
            return normed.index(cand)
    for cand in candidates:            # then whole-word match ("posting date" ~ "date"), never a balance column
        for i, h in enumerate(normed):
            if any(x in h for x in exclude):
                continue
            if re.search(rf"\b{re.escape(cand)}\b", h):
                return i
    return None


def parse_amount(raw: str) -> float | None:
    """'$1,234.56' '-12.00' '(45.00)' '12,34' '1.234,56' 'CR 10.00' -> float."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none", "-", "--"):
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if re.search(r"\bCR\b", s, re.I):
        s = re.sub(r"\bCR\b", "", s, flags=re.I)
    if re.search(r"\bDR\b", s, re.I):
        neg, s = True, re.sub(r"\bDR\b", "", s, flags=re.I)
    s = re.sub(r"[^\d,.\-+]", "", s)
    if not s or s in ("-", "+", ".", ","):
        return None
    if s.startswith("-"):
        neg, s = True, s[1:]
    s = s.lstrip("+")
    # European "1.234,56" vs US "1,234.56"
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # "12,34" (decimal comma) vs "1,234" (thousands)
        parts = s.split(",")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            s = parts[0] + "." + parts[1]
        else:
            s = s.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def parse_date(raw: str, prefer_dmy: bool = False, force_style: str | None = None) -> date | None:
    """force_style: 'dmy' or 'mdy' makes numeric slash/dash dates unambiguous within one file."""
    s = (raw or "").strip().strip('"')
    if not s:
        return None
    if force_style:
        m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$", s)
        if m:
            a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            y = y + 2000 if y < 100 else y
            dd, mm = (a, b) if force_style == "dmy" else (b, a)
            try:
                return date(y, mm, dd)
            except ValueError:
                return None
    fmts = list(DATE_FORMATS)
    if prefer_dmy:
        fmts.sort(key=lambda f: 0 if f.startswith("%d") else 1)
    for fmt in fmts:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # ISO with timezone or fractional seconds
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _detect_style(values: list[str]) -> str | None:
    """'dmy' / 'mdy' if any numeric date in the file disambiguates it, else None."""
    for v in values:
        m = re.match(r"\s*(\d{1,2})[/\-.](\d{1,2})[/\-.]\d{2,4}", v or "")
        if m and int(m.group(1)) > 12:
            return "dmy"
        if m and int(m.group(2)) > 12:
            return "mdy"
    return None


def _decode(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _sniff_rows(text: str) -> tuple[list[str], list[list[str]]]:
    # Some banks put a preamble ("Account: 1234", blank lines) before the header.
    # The header is the first line that actually looks like a table row (2+ delimiters).
    lines = re.split(r"\r\n|\r|\n", text)
    start = 0
    for i, ln in enumerate(lines[:40]):
        if max(ln.count(","), ln.count(";"), ln.count("\t"), ln.count("|")) >= 2:
            start = i
            break
    else:
        return [], []
    body = "\n".join(lines[start:])
    try:
        dialect = csv.Sniffer().sniff(body[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(body), dialect)
    try:
        rows = [r for r in reader if any(c.strip() for c in r)]
    except csv.Error as exc:
        raise ValueError("A cell in this file is too large or a quote mark is unbalanced. Open it in a spreadsheet, check for a stray quote, and save it as CSV again.") from exc
    if not rows or len(rows[0]) < 3:
        return [], []
    return rows[0], rows[1:]


# ---------------------------------------------------------------------------
def import_csv(data: bytes, filename: str = "", account_hint: str = "") -> ImportResult:
    res = ImportResult()
    if not data or not data.strip():
        res.error = "The file is empty."
        return res
    text = _decode(data).replace("\x00", "")
    try:
        headers, rows = _sniff_rows(text)
    except ValueError as exc:
        res.error = str(exc)
        return res
    if not headers or not rows:
        res.error = "No table of transactions was found in this file. Make sure it's the CSV your bank exported, not a PDF statement."
        return res
    if len(rows) > MAX_ROWS:
        rows = rows[:MAX_ROWS]
        res.warnings.append(f"Only the first {MAX_ROWS:,} rows were read.")

    i_date = _find(headers, DATE_HEADERS)
    i_desc = _find(headers, DESC_HEADERS, exclude=("date",))
    i_amt = _find(headers, AMOUNT_HEADERS, exclude=BALANCE_WORDS + ("date",))
    i_deb = _find(headers, DEBIT_HEADERS, exclude=BALANCE_WORDS)
    i_cred = _find(headers, CREDIT_HEADERS, exclude=BALANCE_WORDS)
    i_cat = _find(headers, CATEGORY_HEADERS)
    i_acct = _find(headers, ACCOUNT_HEADERS)
    i_type = _find(headers, TYPE_HEADERS)
    if i_desc == i_date:
        i_desc = None

    # If an "Amount" column is actually the debit column name (e.g. "Debit Amount") the finder already got it.
    if i_amt is not None and i_amt in (i_deb, i_cred):
        i_amt = None

    # Headerless or unrecognised: try to infer by content (first date-like col, first numeric col, longest text col)
    if i_date is None or (i_amt is None and i_deb is None and i_cred is None) or i_desc is None:
        sample = rows[:50]
        ncols = max(len(r) for r in sample)
        if i_date is None:
            for c in range(ncols):
                vals = [r[c] for r in sample if c < len(r)]
                if sum(parse_date(v) is not None for v in vals) >= max(3, len(vals) * 0.7):
                    i_date = c
                    break
        if i_amt is None and i_deb is None and i_cred is None:
            for c in range(ncols):
                if c == i_date:
                    continue
                vals = [r[c] for r in sample if c < len(r)]
                if sum(parse_amount(v) is not None for v in vals) >= max(3, len(vals) * 0.7) and any(re.search(r"\d", v or "") for v in vals):
                    i_amt = c
                    break
        if i_desc is None:
            best, best_len = None, 0
            for c in range(ncols):
                if c in (i_date, i_amt, i_deb, i_cred):
                    continue
                vals = [r[c] for r in sample if c < len(r)]
                avg = sum(len(v or "") for v in vals) / max(1, len(vals))
                if avg > best_len and any(re.search(r"[A-Za-z]{3}", v or "") for v in vals):
                    best, best_len = c, avg
            i_desc = best
        res.warnings.append("The column names weren't standard, so the app guessed which column is which. Check the first few transactions look right.")

    if i_date is None:
        res.error = f"Couldn't find a date column. Columns found: {', '.join(h for h in headers if h)}"
        return res
    if i_amt is None and i_deb is None and i_cred is None:
        res.error = f"Couldn't find an amount column. Columns found: {', '.join(h for h in headers if h)}"
        return res
    if i_desc is None:
        res.error = f"Couldn't find a description/merchant column. Columns found: {', '.join(h for h in headers if h)}"
        return res

    res.mapping = {
        "date": headers[i_date], "description": headers[i_desc],
        "amount": headers[i_amt] if i_amt is not None else None,
        "debit": headers[i_deb] if i_deb is not None else None,
        "credit": headers[i_cred] if i_cred is not None else None,
        "category": headers[i_cat] if i_cat is not None else None,
        "account": headers[i_acct] if i_acct is not None else None,
        "type": headers[i_type] if i_type is not None else None,
    }

    style = _detect_style([r[i_date] for r in rows if i_date < len(r)])
    if style is None and any(re.match(r"\s*\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}", r[i_date] or "") for r in rows[:50] if i_date < len(r)):
        style = "mdy"  # ambiguous file: assume US order and say so
        res.warnings.append("Dates like 05/01/2026 were read as month/day/year. If your bank writes day/month/year, the dates will be off — tell us and we'll add your bank.")
    SIGN_WORDS = {"debit", "dr", "d", "withdrawal", "purchase", "payment", "charge", "sale", "credit", "cr", "c", "deposit", "refund", "return"}
    type_vals = {r[i_type].strip().lower() for r in rows[:200] if i_type is not None and i_type < len(r) and r[i_type].strip()}
    type_is_sign = bool(type_vals) and len(type_vals & SIGN_WORDS) >= max(1, len(type_vals) // 2)
    max_date = date.today() + timedelta(days=366)
    bad_dates = 0
    txns: list[Transaction] = []
    for r in rows:
        if i_date >= len(r):
            res.skipped += 1
            continue
        d = parse_date(r[i_date], prefer_dmy=(style == "dmy"), force_style=style)
        if d is None:
            res.skipped += 1
            continue
        if d < MIN_DATE or d > max_date:
            bad_dates += 1
            continue
        desc = (r[i_desc] if i_desc < len(r) else "").strip()
        amt: float | None = None
        if i_amt is not None and i_amt < len(r):
            amt = parse_amount(r[i_amt])
        if amt is None and (i_deb is not None or i_cred is not None):
            deb = parse_amount(r[i_deb]) if i_deb is not None and i_deb < len(r) else None
            cred = parse_amount(r[i_cred]) if i_cred is not None and i_cred < len(r) else None
            if deb not in (None, 0.0):
                amt = -abs(deb)
            elif cred not in (None, 0.0):
                amt = abs(cred)
            elif deb == 0.0 or cred == 0.0:
                amt = 0.0
        if amt is None:
            res.skipped += 1
            continue
        # A separate "Type" column (Debit/Credit, DR/CR) decides the sign when present
        if type_is_sign and i_type is not None and i_type < len(r) and i_amt is not None:
            t = r[i_type].strip().lower()
            if t in ("debit", "dr", "d", "withdrawal", "purchase", "payment", "charge", "sale"):
                amt = -abs(amt)
            elif t in ("credit", "cr", "c", "deposit", "refund", "return"):
                amt = abs(amt)
        txns.append(
            Transaction(
                date=d,
                description=re.sub(r"\s+", " ", desc)[:200],
                amount=round(amt, 2),
                raw_category=(r[i_cat].strip() if i_cat is not None and i_cat < len(r) else "")[:60],
                account=(r[i_acct].strip() if i_acct is not None and i_acct < len(r) else account_hint)[:60],
            )
        )

    if bad_dates:
        res.warnings.append(f"{bad_dates} row{'s' if bad_dates != 1 else ''} with an impossible date (before 1990 or far in the future) were skipped.")
    if not txns:
        res.error = "The file had a table, but no rows with a readable date and amount."
        return res

    # Sign convention: most rows in a bank export are spending. If most are positive
    # and there's no debit/credit split, the bank writes spending as positive -> flip.
    if i_deb is None and i_cred is None and not type_is_sign:
        neg = sum(1 for t in txns if t.amount < 0)
        pos = sum(1 for t in txns if t.amount > 0)
        # Decide by FORMAT, not by file length: an export with no negative numbers at all
        # (or overwhelmingly positive) writes spending as positive.
        if neg == 0 and pos >= 1 or pos > neg * 2 and pos >= 5:
            for t in txns:
                t.amount = -t.amount
            res.sign_flipped = True
            res.warnings.append("This export lists spending as positive numbers, so the app flipped the signs (spending = negative).")

    txns.sort(key=lambda t: t.date)
    res.transactions = txns
    if res.skipped:
        res.warnings.append(f"{res.skipped} row{'s' if res.skipped != 1 else ''} without a readable date or amount were skipped.")
    return res
