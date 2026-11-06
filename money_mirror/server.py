"""FastAPI server for Money Mirror. Binds to 127.0.0.1 only."""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__, ai, analysis, store
from .categorize import CATEGORIES, categorize, clean_merchant
from .config import SettingsError, load_settings, update_settings, validate_changes
from .importer import import_csv
from .llm import detect_ollama, get_provider

log = logging.getLogger("money_mirror")
ROOT = Path(__file__).parent
STATIC = ROOT / "static"
SAMPLES = ROOT.parent / "samples"
MAX_UPLOAD_BYTES = 30 * 1024 * 1024

app = FastAPI(title="Money Mirror", version=__version__, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])
app.mount("/static", StaticFiles(directory=STATIC), name="static")

LOCAL_ORIGINS = ("http://127.0.0.1", "http://localhost", "http://[::1]")


@app.middleware("http")
async def block_cross_site_writes(request, call_next):
    """CSRF guard: a web page in another tab must not be able to POST/DELETE into this app.
    Browsers always send Origin (or Sec-Fetch-Site) on cross-site requests; same-origin and
    non-browser clients (curl, tests) send neither or a local one."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin", "")
        sfs = request.headers.get("sec-fetch-site", "")
        if origin and not origin.startswith(LOCAL_ORIGINS):
            return JSONResponse(status_code=403, content={"detail": "Blocked a request from another website."})
        if sfs and sfs not in ("same-origin", "none"):
            return JSONResponse(status_code=403, content={"detail": "Blocked a request from another website."})
    return await call_next(request)


def _provider_status(s) -> dict:
    provider = get_provider(s)
    try:
        ok, message = provider.check()
    except Exception as exc:  # noqa: BLE001
        log.warning("provider check failed: %s", exc)
        ok, message = False, "Could not check the AI option. Open Settings and click Test."
    return {"name": provider.name, "model": provider.model, "local": provider.local, "ok": ok, "message": message}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__}


@app.get("/api/status")
def status(probe: int = 0):
    """probe=1 (Settings / first-run screens) also looks for Ollama. Otherwise, in No-AI or cloud
    modes, the app makes no local network call at all."""
    s = load_settings()
    ollama = detect_ollama(s.ollama_host) if (s.provider == "ollama" or probe) else {"running": False, "models": [], "skipped": True}
    if s.provider == "ollama":
        provider = get_provider(s)
        if ollama.get("error"):
            pstat = {"ok": False, "message": ollama["error"]}
        elif not ollama["running"]:
            pstat = {"ok": False, "message": "Ollama isn't running (or isn't installed). See Settings for the install steps, or start it with: ollama serve"}
        elif not ollama["models"]:
            pstat = {"ok": False, "message": f"Ollama is running but has no models. Run: ollama pull {provider.model}"}
        elif not any(m == provider.model or m.split(":")[0] == provider.model.split(":")[0] for m in ollama["models"]):
            pstat = {"ok": False, "message": f"Model '{provider.model}' is not downloaded. Run: ollama pull {provider.model}"}
        else:
            pstat = {"ok": True, "message": f"Ollama is ready with {provider.model}"}
        pstat.update({"name": provider.name, "model": provider.model, "local": True})
    else:
        pstat = _provider_status(s)
    from .config import data_dir

    return {"settings": s.public_dict(), "provider": pstat, "ollama": ollama, "categories": CATEGORIES, "transactions": store.count(), "imports": store.imports(), "data_dir": str(data_dir()), "env_overrides": sorted(k for k in ("MONEY_MIRROR_PROVIDER", "MONEY_MIRROR_MODEL", "OLLAMA_HOST", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENAI_BASE_URL") if __import__("os").environ.get(k))}


class SettingsIn(BaseModel):
    provider: str | None = None
    model: str | None = None
    ollama_host: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    gemini_api_key: str | None = None
    save_history: bool | None = None
    setup_complete: bool | None = None


@app.post("/api/settings")
def set_settings(body: SettingsIn):
    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        s = update_settings(changes)
    except SettingsError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"settings": s.public_dict(), "provider": _provider_status(s)}


@app.post("/api/test-connection")
def test_connection(body: SettingsIn):
    s = load_settings()
    try:
        changes = validate_changes({k: v for k, v in body.model_dump().items() if v is not None})
    except SettingsError as exc:
        return {"ok": False, "message": str(exc), "model": ""}
    for k, v in changes.items():
        if hasattr(s, k):
            if k in ("openai_api_key", "gemini_api_key") and "*" in str(v):
                continue
            setattr(s, k, v)
    st = _provider_status(s)
    return {"ok": st["ok"], "message": st["message"], "model": st["model"]}


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------
def _ingest(data: bytes, filename: str) -> dict:
    res = import_csv(data, filename)
    if not res.ok:
        raise HTTPException(400, res.error)
    learned = store.rules()
    rows = []
    for t in res.transactions:
        merchant = clean_merchant(t.description)
        rows.append(
            {
                "date": t.date, "description": t.description, "merchant": merchant, "amount": t.amount,
                "category": categorize(t.description, merchant, t.amount, t.raw_category, learned),
                "raw_category": t.raw_category, "account": t.account,
            }
        )
    added, dup = store.add_transactions(rows, filename)
    unknown = sorted({r["merchant"] for r in rows if r["category"] == "Other" and r["amount"] < 0})
    return {
        "filename": filename, "added": added, "duplicates": dup, "mapping": res.mapping, "warnings": res.warnings,
        "sign_flipped": res.sign_flipped, "first_date": rows[0]["date"].isoformat(), "last_date": rows[-1]["date"].isoformat(),
        "unknown_merchants": unknown[:200], "total": store.count(),
        "preview": [{**r, "date": r["date"].isoformat()} for r in rows[:5]],
    }


@app.post("/api/import")
async def import_file(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "That file is bigger than 30 MB. Export a shorter date range from your bank.")
    name = file.filename or "upload.csv"
    if not name.lower().endswith((".csv", ".txt", ".tsv")):
        raise HTTPException(400, "Please upload the CSV file your bank exports (it ends in .csv). PDF statements won't work.")
    return await asyncio.to_thread(_ingest, data, name)


@app.post("/api/import/sample")
async def import_sample():
    p = SAMPLES / "sample_checking.csv"
    if not p.exists():
        raise HTTPException(404, "Sample data is missing.")
    out = await asyncio.to_thread(_ingest, p.read_bytes(), "Example bank export")
    p2 = SAMPLES / "sample_credit_card.csv"
    if p2.exists():
        out2 = await asyncio.to_thread(_ingest, p2.read_bytes(), "Example credit card export")
        out["added"] += out2["added"]
        out["duplicates"] += out2["duplicates"]
        out["warnings"] = out["warnings"] + out2["warnings"]
        out["last_date"] = max(out["last_date"], out2["last_date"])
        out["first_date"] = min(out["first_date"], out2["first_date"])
        out["total"] = out2["total"]
        out["unknown_merchants"] = sorted(set(out["unknown_merchants"]) | set(out2["unknown_merchants"]))
    return out


class LearnIn(BaseModel):
    merchants: list[str]


@app.post("/api/ai/categorize")
async def ai_categorize(body: LearnIn):
    """Ask the AI (if on) to categorize merchants the rules couldn't. Only merchant NAMES are sent."""
    s = load_settings()
    mapping = await asyncio.to_thread(ai.categorize_merchants, body.merchants[:200], s)
    if mapping:
        store.add_rules(mapping, "ai")
    return {"learned": mapping, "engine": get_provider(s).name}


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------
def _today(txns: list[dict]) -> date:
    # "Today" for analysis = the newest transaction date, so old exports still make sense.
    return date.fromisoformat(txns[-1]["date"]) if txns else date.today()


@app.get("/api/overview")
def overview():
    txns = store.all_transactions()
    if not txns:
        return {"empty": True}
    today = _today(txns)
    return {
        "overview": analysis.overview(txns, today),
        "monthly": analysis.monthly(txns),
        "subscriptions": analysis.subscriptions(txns, today),
        "alerts": analysis.alerts(txns, today),
        "as_of": today.isoformat(),
    }


@app.get("/api/transactions")
def transactions(q: str = "", category: str = "", month: str = "", merchant: str = "", ids: str = "", limit: int = 500, offset: int = 0):
    txns = store.all_transactions()
    ql = q.lower().strip()
    want = set(i for i in ids.split(",") if i) if ids else None
    out = []
    for t in reversed(txns):
        if want is not None and t["id"] not in want:
            continue
        if ql and ql not in t["description"].lower() and ql not in t["merchant"].lower() and ql not in t["category"].lower():
            continue
        if category and t["category"] != category:
            continue
        if month and t["date"][:7] != month:
            continue
        if merchant and t["merchant"].lower() != merchant.lower():
            continue
        out.append(t)
    return {"total": len(out), "items": out[offset : offset + max(1, min(limit, 2000))]}


class CategoryIn(BaseModel):
    id: str
    category: str
    apply_to_merchant: bool = True


@app.post("/api/transactions/category")
def set_category(body: CategoryIn):
    if body.category not in CATEGORIES:
        raise HTTPException(400, "Unknown category.")
    n = store.set_category(body.id, body.category, body.apply_to_merchant)
    if n == 0:
        raise HTTPException(404, "That transaction wasn't found.")
    return {"updated": n}


class AskIn(BaseModel):
    question: str


@app.post("/api/ask")
async def ask(body: AskIn):
    q = body.question.strip()[:300]
    if not q:
        return {"answer": "Type a question first — for example: how much did I spend on groceries last month?", "result": None}
    txns = store.all_transactions()
    if not txns:
        return {"answer": "Import a bank CSV first, then ask away.", "result": None}
    today = _today(txns)
    merchants = sorted({t["merchant"] for t in txns})
    s = load_settings()
    spec, engine = await asyncio.to_thread(ai.question_to_spec, q, today, CATEGORIES, merchants, s)
    res = analysis.run_query(txns, spec)
    if engine != "offline" and res["count"] == 0:
        # Safety net: if the AI's reading finds nothing but the plain rules find something, trust the rules.
        base = analysis.parse_question(q, today, CATEGORIES, merchants)
        if base.get("understood"):
            base_res = analysis.run_query(txns, base)
            if base_res["count"] > 0:
                spec, res, engine = base, base_res, "offline"
    note = ""
    if s.provider != "offline" and engine == "offline" and spec.get("understood") is False:
        ok, msg = get_provider(s).check()
        if not ok:
            note = f"The AI option isn't working right now ({msg}), so built-in rules were used."
    return {"answer": analysis.phrase_answer(spec, res), "result": res, "engine": engine, "note": note}


@app.get("/api/export.csv")
def export_csv():
    txns = store.all_transactions()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "merchant", "description", "amount", "category", "account"])
    def safe(v: str) -> str:
        # Spreadsheets treat leading = + - @ as formulas; prefix with ' so a crafted description can't run.
        return ("'" + v) if v and v[0] in "=+-@\t\r" else v

    for t in txns:
        w.writerow([t["date"], safe(t["merchant"]), safe(t["description"]), f"{t['amount']:.2f}", t["category"], safe(t["account"] or t["source_file"] or "")])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=money-mirror-categorized.csv"})


@app.delete("/api/data")
def delete_data(everything: bool = False):
    if everything:
        store.delete_everything_including_rules()
        return {"deleted": True}
    return {"deleted": store.delete_all()}


@app.exception_handler(Exception)
async def unhandled(_, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": f"Something went wrong inside the app ({type(exc).__name__}). Try again. If it keeps happening, run: python scripts/selfcheck.py"})
