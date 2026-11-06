"""G2 — API smoke, G6 — privacy (no network in No-AI mode), AI-path tests with a fake provider."""

import socket

from money_mirror.llm import providers


def test_health_and_ui(client):
    assert client.get("/api/health").json()["ok"]
    assert "Money Mirror" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200


def test_status_empty(client):
    d = client.get("/api/status").json()
    assert d["provider"]["name"] == "offline" and d["transactions"] == 0 and len(d["categories"]) > 20
    assert client.get("/api/overview").json()["empty"] is True


def test_import_sample_then_overview(client):
    d = client.post("/api/import/sample").json()
    assert d["added"] > 300 and d["duplicates"] == 0 and d["unknown_merchants"] == []
    again = client.post("/api/import/sample").json()
    assert again["added"] == 0 and again["duplicates"] > 300  # idempotent
    o = client.get("/api/overview").json()
    assert not o.get("empty")
    assert o["overview"]["top_categories"][0]["category"] == "Housing & Rent"
    assert any(s["merchant"].startswith("Netflix") and s["price_change"] for s in o["subscriptions"])
    assert any(a["type"] == "duplicate" for a in o["alerts"])
    assert len(o["monthly"]) == 7


def test_import_file_and_errors(client, samples_dir):
    r = client.post("/api/import", files={"file": ("bank.csv", (samples_dir / "sample_checking.csv").read_bytes(), "text/csv")})
    assert r.status_code == 200 and r.json()["added"] > 100 and r.json()["mapping"]["date"] == "Date"
    r = client.post("/api/import", files={"file": ("statement.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 400 and "CSV" in r.json()["detail"]
    r = client.post("/api/import", files={"file": ("x.csv", b"hello\nworld", "text/csv")})
    assert r.status_code == 400 and "No table" in r.json()["detail"]
    big = b"a" * (30 * 1024 * 1024 + 1)
    assert client.post("/api/import", files={"file": ("big.csv", big, "text/csv")}).status_code == 400


def test_transactions_filter_and_edit(client):
    client.post("/api/import/sample")
    d = client.get("/api/transactions", params={"q": "netflix"}).json()
    assert d["total"] == 7 and all("Netflix" in t["merchant"] for t in d["items"])
    tid = d["items"][0]["id"]
    r = client.post("/api/transactions/category", json={"id": tid, "category": "Entertainment", "apply_to_merchant": True}).json()
    assert r["updated"] == 7
    assert all(t["category"] == "Entertainment" for t in client.get("/api/transactions", params={"q": "netflix"}).json()["items"])
    # learned rule survives a re-import with fresh rows
    client.delete("/api/data")
    client.post("/api/import/sample")
    assert client.get("/api/transactions", params={"q": "netflix"}).json()["items"][0]["category"] == "Entertainment"
    assert client.post("/api/transactions/category", json={"id": "nope", "category": "Entertainment"}).status_code == 404
    assert client.post("/api/transactions/category", json={"id": tid, "category": "Bogus"}).status_code == 400


def test_ask_offline(client):
    assert "Import" in client.post("/api/ask", json={"question": "groceries"}).json()["answer"]
    client.post("/api/import/sample")
    d = client.post("/api/ask", json={"question": "how much did I spend on groceries since August?"}).json()
    assert d["engine"] == "offline" and d["result"]["count"] > 5 and "Groceries" in d["answer"]
    assert "Type a question" in client.post("/api/ask", json={"question": "  "}).json()["answer"]


def test_export_and_delete(client):
    client.post("/api/import/sample")
    r = client.get("/api/export.csv")
    assert r.status_code == 200 and r.text.startswith("date,merchant,description,amount,category,account")
    assert client.delete("/api/data").json()["deleted"] > 300
    assert client.get("/api/status").json()["transactions"] == 0


def test_foreign_host_rejected(client):
    from fastapi.testclient import TestClient

    from money_mirror.server import app

    assert TestClient(app, base_url="http://evil.example").get("/api/overview").status_code == 400


def test_db_file_is_private(client):
    import os
    import stat

    from money_mirror.config import data_dir

    client.post("/api/import/sample")
    mode = stat.S_IMODE(os.stat(data_dir() / "money.db").st_mode)
    assert mode == 0o600


# ---------------- G6 privacy ----------------
def test_no_network_in_offline_mode(client, monkeypatch):
    client.post("/api/import/sample")
    calls = []

    def guard(self, *a, **k):
        calls.append(a)
        raise AssertionError("network call attempted")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)
    assert client.get("/api/overview").status_code == 200
    assert client.post("/api/ask", json={"question": "coffee last month"}).status_code == 200
    assert client.post("/api/ai/categorize", json={"merchants": ["Zzz"]}).json()["learned"] == {}
    assert calls == []


# ---------------- AI path with a fake provider ----------------
class Fake(providers.BaseProvider):
    name = "ollama"
    local = True
    seen: list[str] = []

    def check(self):
        return True, "fake"

    def complete(self, system_prompt, user_prompt, want_json=False):
        Fake.seen.append(user_prompt)
        if "Merchants:" in user_prompt:
            return '{"Zzz Unknown LLC": "Kids & Pets", "Bad": "NotACategory"}'
        return '{"agg": "count", "category": "Coffee & Snacks", "merchant": null, "start": "2026-09-01", "end": null, "income": false}'


def test_ai_categorize_and_question_never_see_amounts(client, monkeypatch):
    monkeypatch.setenv("MONEY_MIRROR_PROVIDER", "ollama")
    monkeypatch.setattr("money_mirror.ai.get_provider", lambda s: Fake(s))
    Fake.seen.clear()
    client.post("/api/import/sample")
    client.post("/api/import", files={"file": ("x.csv", b"Date,Description,Amount\n2026-10-01,ZZZ UNKNOWN LLC,-9.99\n2026-10-02,ZZZ UNKNOWN LLC,-9.99\n", "text/csv")})
    r = client.post("/api/ai/categorize", json={"merchants": ["Zzz Unknown LLC", "Bad"]}).json()
    assert r["learned"] == {"zzz unknown llc": "Kids & Pets"}
    assert client.get("/api/transactions", params={"q": "zzz"}).json()["items"][0]["category"] == "Kids & Pets"
    d = client.post("/api/ask", json={"question": "coffee count since sept"}).json()
    assert d["engine"] == "ollama" and d["result"]["spec"]["agg"] == "count" and d["result"]["spec"]["start"] == "2026-09-01"
    # the AI prompts contain merchant names and the question only — no dollar amounts, no dates of transactions
    blob = "\n".join(Fake.seen)
    assert "$" not in blob and "-9.99" not in blob and "1450" not in blob


# ---------------- regressions from independent code review ----------------
def test_cross_site_write_is_blocked(client):
    r = client.post("/api/import/sample", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/import/sample", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert client.post("/api/import/sample", headers={"Origin": "http://127.0.0.1:8766"}).status_code == 200
    assert client.get("/api/status").json()["transactions"] > 0


def test_status_makes_no_network_call_in_offline_mode(client, monkeypatch):
    calls = []

    def guard(self, *a, **k):
        calls.append(a)
        raise AssertionError("network")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)
    assert client.get("/api/status").status_code == 200
    assert calls == []


def test_export_neutralises_formulas(client):
    client.post("/api/import", files={"file": ("x.csv", b"Date,Description,Amount\n2026-05-01,=HYPERLINK(\"http://x\"),-1\n2026-05-02,B,-2\n", "text/csv")})
    body = client.get("/api/export.csv").text
    assert "'=HYPERLINK" in body and "\n=HYPERLINK" not in body


def test_transactions_by_ids(client):
    client.post("/api/import/sample")
    o = client.get("/api/overview").json()
    ids = o["alerts"][0]["ids"]
    got = client.get("/api/transactions", params={"ids": ",".join(ids)}).json()["items"]
    assert {t["id"] for t in got} == set(ids)


def test_extreme_date_rows_do_not_brick_overview(client):
    client.post("/api/import", files={"file": ("x.csv", b"Date,Description,Amount\n9999-12-01,A,-1\n2026-05-01,B,-2\n2026-05-02,C,-3\n", "text/csv")})
    assert client.get("/api/overview").status_code == 200


def test_ai_never_sees_p2p_payees_or_transaction_dates(client, monkeypatch):
    monkeypatch.setenv("MONEY_MIRROR_PROVIDER", "ollama")
    monkeypatch.setattr("money_mirror.ai.get_provider", lambda s: Fake(s))
    Fake.seen.clear()
    client.post("/api/import", files={"file": ("x.csv", b"Date,Description,Amount\n2019-03-04,ZELLE TO JANE DOE,-50\n2019-03-05,ZELLE TO JANE DOE,-50\n2019-03-06,COFFEE PLACE,-4\n", "text/csv")})
    client.post("/api/ai/categorize", json={"merchants": ["Zelle To Jane Doe", "Coffee Place"]})
    client.post("/api/ask", json={"question": "coffee"})
    blob = "\n".join(Fake.seen)
    assert "Jane" not in blob and "2019-03" not in blob


def test_ai_cannot_make_a_good_rules_answer_worse(client, monkeypatch):
    """Small models sometimes return a wrong category/merchant/date window. Rules must win when they matched."""
    class WrongAI(providers.BaseProvider):
        name = "ollama"
        local = True

        def check(self):
            return True, "fake"

        def complete(self, system_prompt, user_prompt, want_json=False):
            return '{"agg":"sum","category":"Travel","merchant":null,"start":"2026-10-22","end":"2026-10-22","income":false}'

    monkeypatch.setenv("MONEY_MIRROR_PROVIDER", "ollama")
    monkeypatch.setattr("money_mirror.ai.get_provider", lambda s: WrongAI(s))
    client.post("/api/import/sample")
    d = client.post("/api/ask", json={"question": "how much did I spend on groceries in September?"}).json()
    assert d["result"]["spec"]["category"] == "Groceries" and d["result"]["count"] > 0
    d = client.post("/api/ask", json={"question": "did I pay netflix in October?"}).json()
    assert d["result"]["count"] == 1
