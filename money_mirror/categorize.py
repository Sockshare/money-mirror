"""Clean up merchant names and sort transactions into everyday categories.

Everything here is deterministic and runs offline. An AI (if the user turned one
on) is only asked about merchants these rules can't place, and its answers are
saved as new rules so it's never asked twice.
"""

from __future__ import annotations

import re

CATEGORIES = [
    "Groceries", "Restaurants & Takeout", "Coffee & Snacks", "Transport & Fuel", "Rideshare & Taxi",
    "Housing & Rent", "Utilities", "Phone & Internet", "Subscriptions & Streaming", "Shopping",
    "Health & Pharmacy", "Insurance", "Entertainment", "Travel", "Fitness", "Kids & Pets",
    "Personal Care", "Education", "Gifts & Donations", "Fees & Interest", "Taxes & Government",
    "Transfers", "Income", "Cash", "Loan & Credit Card Payments", "Other",
]

# (regex on cleaned merchant, category). First match wins. Keep specific before generic.
RULES: list[tuple[str, str]] = [
    # income / transfers / payments
    (r"payroll|direct dep|salary|paycheck|employer|wages|ach credit.*(inc|llc|corp)", "Income"),
    (r"interest paid|interest earned|dividend|cashback reward|cash back", "Income"),
    (r"zelle|venmo|cash app|paypal transfer|transfer (to|from)|online transfer|wire|e-transfer|interac", "Transfers"),
    (r"autopay|card payment|credit card pmt|payment thank you|payment - thank you|loan payment|mortgage|auto loan|student loan|sallie|navient|nelnet", "Loan & Credit Card Payments"),
    (r"\batm\b|cash withdrawal|withdrawal", "Cash"),
    (r"overdraft|late fee|annual fee|service charge|service fee|maintenance fee|monthly fee|account fee|foreign transaction|interest charge|finance charge|nsf fee|returned item|wire fee|atm fee", "Fees & Interest"),
    (r"\birs\b|tax payment|dept of revenue|dmv|parking ticket|court|city of .* (fee|permit)", "Taxes & Government"),
    # housing / utilities
    (r"rent\b|apartments|property mgmt|property management|realty|leasing|hoa\b", "Housing & Rent"),
    (r"electric|power co|energy|gas co|pg&e|con ed|duke energy|water (dept|utility|bill)|sewer|waste mgmt|trash|utility", "Utilities"),
    (r"verizon|at&t|t-mobile|tmobile|sprint|comcast|xfinity|spectrum|cox comm|centurylink|frontier|mint mobile|google fi|visible|cricket|internet", "Phone & Internet"),
    # subscriptions
    (r"netflix|hulu|disney\+|disney plus|hbo|max\.com|spotify|apple\.com/bill|apple music|youtube premium|youtubepremium|amazon prime|prime video|paramount|peacock|audible|kindle unltd|crunchyroll|icloud|google storage|google one|dropbox|microsoft 365|office 365|adobe|canva|notion|chatgpt|openai|patreon|substack|nytimes|wsj|washington post|medium\.com|xbox|playstation|nintendo|twitch|sirius", "Subscriptions & Streaming"),
    (r"planet fitness|la fitness|24 hour|anytime fitness|equinox|peloton|ymca|crossfit|gym|yoga|pilates|orangetheory|strava", "Fitness"),
    # food
    (r"whole foods|trader joe|safeway|kroger|publix|aldi|costco|sam's club|walmart grocery|wegmans|h-e-b|heb\b|food lion|giant|stop & shop|shoprite|sprouts|winco|meijer|albertsons|fred meyer|ralphs|vons|market basket|instacart|grocery|supermarket", "Groceries"),
    (r"starbucks|dunkin|peet|coffee|cafe|caf\u00e9|tim hortons|dutch bros|bakery|donut|boba|tea house|7-eleven|7 eleven|wawa|sheetz|circle k|kwik", "Coffee & Snacks"),
    (r"doordash|uber eats|ubereats|grubhub|postmates|seamless|chipotle|mcdonald|burger king|wendy|taco bell|chick-fil-a|subway|panera|pizza|domino|papa john|kfc|popeyes|five guys|shake shack|in-n-out|sushi|thai|grill|bistro|diner|restaurant|kitchen|eatery|tavern|pub\b|bar & grill|brewery|steakhouse|noodle|ramen|taqueria|cantina|wingstop|panda express|olive garden|applebee|ihop|denny", "Restaurants & Takeout"),
    # transport
    (r"uber(?! eats)|lyft|taxi|cab co|curb\b", "Rideshare & Taxi"),
    (r"shell|chevron|exxon|mobil|\bbp\b|texaco|arco|sunoco|valero|marathon|speedway|citgo|phillips 66|conoco|fuel|gas station|petrol|ez ?pass|fastrak|toll|parking|parkmobile|spothero|metro|transit|mta\b|bart\b|amtrak|greyhound|car wash|jiffy lube|autozone|o'reilly|pep boys|discount tire|dmv", "Transport & Fuel"),
    # health
    (r"cvs|walgreens|rite aid|pharmacy|rx\b|clinic|medical|hospital|dental|dentist|orthodont|optical|vision|lenscrafters|urgent care|labcorp|quest diag|physician|health|doctor|dr\.?\s", "Health & Pharmacy"),
    (r"geico|progressive|state farm|allstate|liberty mutual|usaa|farmers ins|nationwide|aetna|cigna|blue cross|bcbs|united ?health|kaiser|humana|insurance|lemonade", "Insurance"),
    # travel / entertainment
    (r"airline|airways|delta|united air|american air|southwest|jetblue|alaska air|spirit air|frontier air|expedia|booking\.com|airbnb|vrbo|hotel|marriott|hilton|hyatt|motel|hertz|avis|enterprise rent|budget rent|turo|travel", "Travel"),
    (r"amc|regal|cinemark|cinema|theat(er|re)|ticketmaster|stubhub|live nation|eventbrite|museum|zoo|aquarium|bowling|arcade|dave & buster|topgolf|steam games|steampowered|epic games|concert|festival|golf", "Entertainment"),
    # shopping
    (r"amazon|amzn|target|walmart|best buy|home depot|lowe's|lowes|ikea|wayfair|etsy|ebay|apple store|apple\.com(?!/bill)|nike|adidas|zara|h&m|old navy|gap\b|macy|nordstrom|kohl|tj ?maxx|marshalls|ross|dollar (tree|general)|five below|costco\.com|shein|temu|aliexpress|chewy|petco|petsmart|staples|office depot|michaels|hobby lobby|dick's|rei\b|bath & body|sephora|ulta", "Shopping"),
    (r"petco|petsmart|chewy|vet\b|veterinar|daycare|child care|toys r us|kids|baby|diaper", "Kids & Pets"),
    (r"salon|barber|haircut|spa\b|nails|massage|great clips|supercuts|laundromat|dry clean", "Personal Care"),
    (r"university|college|tuition|udemy|coursera|skillshare|masterclass|school|bookstore|chegg|duolingo", "Education"),
    (r"donation|red cross|unicef|gofundme|church|mosque|temple|charity|foundation|goodwill|salvation army", "Gifts & Donations"),
]

NOISE = [
    r"\$?\d+[.,]\d{2}\b",                   # amounts hiding in descriptions ("12.99", "$45.00")
    r"\b(pos|debit|credit|purchase|payment|card|visa|mastercard|mc|chk|check|ach|web|online|recurring|pending|authorized|auth)\b",
    r"\b\d{2}/\d{2}(/\d{2,4})?\b",          # dates inside descriptions
    r"\b\d{4,}\b",                          # long numbers (store ids, last-4s)
    r"#\s*\d+", r"\*+\w*\d\w*",             # "#1234", "*1A2B"
    r"\b[a-z]{2}\b\s*$",                    # trailing state code
    r"\s{2,}",
]


def clean_merchant(description: str) -> str:
    """'SQ *BLUE BOTTLE COFFEE 0412 SAN FRANCISCO CA 11/02' -> 'Blue Bottle Coffee'."""
    s = (description or "").strip()
    low0 = s.lower()
    # Amazon's many spellings collapse to one merchant
    if re.match(r"^(amzn|amazon)", low0):
        if "prime" in low0:
            return "Amazon Prime"
        if "refund" in low0:
            return "Amazon Refund"
        return "Amazon"
    s = re.sub(r"^(sq|tst|sp|pp|py|ppy|pypl|dd|gg)\s*\*\s*", "", s, flags=re.I)  # processor prefixes
    s = re.sub(r"^(paypal|pp)\s*\*", "", s, flags=re.I)
    if re.match(r"^payment\s*-?\s*thank you", s, re.I):
        return "Card Payment"
    # Drop a trailing "CITY ST" / "CITY NAME ST" location suffix
    s = re.sub(r"\s+[A-Za-z.'-]+(?:\s+[A-Za-z.'-]+)?\s+[A-Z]{2}\s*(?:\d{2}/\d{2}(?:/\d{2,4})?)?\s*$", "", s)
    low = s.lower()
    for pat in NOISE:
        low = re.sub(pat, " ", low)
    low = re.sub(r"[^a-z0-9&'.+\- ]", " ", low)
    low = re.sub(r"\s+", " ", low).strip(" -.")
    if not low:
        # Nothing left but numbers/noise (e.g. "CHECK 1234 $45.00"): use a generic, number-free name.
        d0 = (description or "").lower()
        low = "check" if "check" in d0 or "chk" in d0 else "transfer" if "transfer" in d0 else "unknown"
    words = low.split(" ")[:4]  # merchants are usually the first few words
    title = " ".join(w.upper() if w in ("atm", "hoa", "irs", "dmv", "bp", "rei", "cvs", "amc", "kfc", "ihop", "heb", "mta", "att", "at&t", "usaa", "bcbs") else w.capitalize() for w in words)
    return title[:60]


_COMPILED = [(re.compile(p, re.I), c) for p, c in RULES]
_RULE_CACHE: dict[str, str | None] = {}


def _rule_match(blob: str) -> str | None:
    hit = _RULE_CACHE.get(blob)
    if hit is None and blob not in _RULE_CACHE:
        hit = next((cat for rx, cat in _COMPILED if rx.search(blob)), None)
        if len(_RULE_CACHE) < 50_000:
            _RULE_CACHE[blob] = hit
    return hit


def categorize(description: str, merchant: str, amount: float, raw_category: str = "", custom_rules: dict[str, str] | None = None) -> str:
    """custom_rules: {merchant_lower: category} learned from the user or the AI."""
    key = merchant.lower()
    if custom_rules and key in custom_rules:
        return custom_rules[key]
    blob = f"{description} {merchant}"
    hit = _rule_match(blob)
    if hit:
        return hit
    # Trust the bank's own category if it maps onto ours
    rc = (raw_category or "").lower()
    if rc:
        for cat in CATEGORIES:
            if cat.lower().split(" ")[0] in rc:
                return cat
        if "food" in rc or "dining" in rc:
            return "Restaurants & Takeout"
        if "grocer" in rc:
            return "Groceries"
        if "gas" in rc or "auto" in rc:
            return "Transport & Fuel"
        if "bill" in rc or "util" in rc:
            return "Utilities"
        if "income" in rc or "deposit" in rc or "payroll" in rc:
            return "Income"
        if "transfer" in rc:
            return "Transfers"
    if amount > 0:
        return "Income" if amount > 200 else "Other"
    return "Other"
