"""G4 — UI render test (Playwright). Full click-through in No-AI mode; zero console errors; no text leaks; responsive."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SHOTS = ROOT / "docs" / "screenshots"
try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None
pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright not installed")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port = _free_port()
    env = {**os.environ, "MONEY_MIRROR_DATA_DIR": str(tmp_path_factory.mktemp("data")), "MONEY_MIRROR_PROVIDER": "offline"}
    proc = subprocess.Popen([sys.executable, "app.py", "--port", str(port), "--no-browser"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(80):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("server did not start")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _collect(page):
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    # Chrome logs a console line for every non-2xx response; the intentional bad-file 400 is covered by the response hook below.
    page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" and "Failed to load resource" not in m.text else None)
    # 4xx from /api/import is an expected, friendly rejection we trigger on purpose; anything else is a bug
    page.on("response", lambda r: errors.append(f"http {r.status}: {r.url}") if (r.status >= 500 or (r.status >= 400 and "/api/import" not in r.url)) else None)
    return errors


def _no_leaks(page):
    body = page.inner_text("body")
    for bad in ("undefined", "[object Object]", "NaN"):
        assert bad not in body, bad
    assert not re.search(r"\bnull\b", body)


def test_full_flow(server, browser):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page = browser.new_page(viewport={"width": 1366, "height": 900})
    errors = _collect(page)
    page.goto(server)
    page.wait_for_selector("#screen-setup:not([hidden])", timeout=10000)
    assert page.locator(".choice").count() == 3
    page.screenshot(path=SHOTS / "01_first_run.png", full_page=True)
    page.click('.choice[data-choice="offline"]')
    page.wait_for_selector("#screen-import:not([hidden])")
    assert page.is_visible("#dropzone") and "stay on this computer" in page.inner_text("#privacyText")
    page.screenshot(path=SHOTS / "02_import.png", full_page=True)

    # bad file -> friendly toast, stays on import screen
    page.set_input_files("#fileInput", {"name": "statement.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 fake"})
    page.wait_for_selector("#toast:not([hidden])")
    assert "CSV" in page.inner_text("#toast")

    page.click("#sampleBtn")
    page.wait_for_selector("#screen-imported:not([hidden])", timeout=30000)
    assert "Imported" in page.inner_text("#impHeadline") and page.locator("#impPreview tr").count() >= 4
    page.screenshot(path=SHOTS / "03_imported.png", full_page=True)
    page.click("#impGo")
    page.wait_for_selector("#screen-dash:not([hidden])", timeout=30000)

    # overview
    assert page.inner_text("#sThis").startswith("$") and page.inner_text("#sAvg").startswith("$")
    assert page.locator("#chartMonths svg rect").count() >= 6
    assert page.locator("#chartCats .bar-row").count() >= 5
    assert "In plain words" in page.inner_text("#plainSummary")
    page.screenshot(path=SHOTS / "04_overview.png", full_page=True)
    # click a category bar -> transactions tab filtered
    page.click('#chartCats .bar-row[data-cat="Groceries"]')
    page.wait_for_selector("#pane-txns:not([hidden])")
    assert page.input_value("#fCategory") == "Groceries"
    page.wait_for_function("document.querySelectorAll('#txnTable tr').length > 5")
    # subscriptions
    page.click('.tab[data-tab="subs"]')
    assert page.locator(".sub-row").count() >= 8
    assert page.locator(".tag.up").count() >= 1  # Netflix price hike flagged
    page.screenshot(path=SHOTS / "05_subscriptions.png", full_page=True)
    page.click(".sub-row >> nth=0")
    page.wait_for_selector("#modal-txns:not([hidden])")
    assert page.locator("#mTxnTable tr").count() >= 4
    page.keyboard.press("Escape")
    # alerts
    page.click('.tab[data-tab="alerts"]')
    assert page.locator(".alert-row.high").count() >= 1
    assert int(page.inner_text("#alertCount")) >= 2
    page.screenshot(path=SHOTS / "06_alerts.png", full_page=True)
    page.click(".alert-row.high >> nth=0")
    page.wait_for_selector("#modal-txns:not([hidden])")
    assert page.locator("#mTxnTable tr").count() == 3  # header + the two duplicate rows
    page.keyboard.press("Escape")
    # transactions: search + edit category
    page.click('.tab[data-tab="txns"]')
    page.click("#fClear")
    page.fill("#fSearch", "netflix")
    page.wait_for_function("document.querySelectorAll('#txnTable tr').length === 8")
    page.select_option("#txnTable select >> nth=0", "Entertainment")
    page.wait_for_selector("#toast:not([hidden])")
    assert "remembered" in page.inner_text("#toast")
    page.screenshot(path=SHOTS / "07_transactions.png", full_page=True)
    # ask
    page.click('.tab[data-tab="ask"]')
    page.click('.chip >> nth=0')
    page.wait_for_selector("#askThread .qa .a:not(.muted)", timeout=15000)
    assert "$" in page.inner_text("#askThread .qa .a")
    page.fill("#askInput", "how many times did I go to starbucks?")
    page.press("#askInput", "Enter")
    page.wait_for_function("document.querySelectorAll('#askThread .qa').length === 2")
    page.wait_for_function("!document.querySelector('#askThread .qa .a').classList.contains('muted')")
    assert "Starbucks" in page.inner_text("#askThread .qa >> nth=0")
    page.screenshot(path=SHOTS / "08_ask.png", full_page=True)
    _no_leaks(page)
    # settings
    page.click("#settingsBtn")
    page.wait_for_selector("#modal-settings:not([hidden])")
    assert "transactions" in page.inner_text("#setDataInfo")
    page.click('input[name=prov][value=gemini]')
    page.click("#setTest")
    page.wait_for_function("document.getElementById('setTestOut').textContent.includes('✗')")
    page.click('input[name=prov][value=offline]')
    page.click("#setSave")
    page.wait_for_selector("#modal-settings", state="hidden")
    page.screenshot(path=SHOTS / "09_settings.png")
    assert errors == [], errors
    page.close()


@pytest.mark.parametrize("width,name", [(1024, "laptop"), (420, "phone")])
def test_responsive(server, browser, width, name):
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors = _collect(page)
    page.goto(server)
    page.wait_for_selector("#screen-dash:not([hidden]), #screen-import:not([hidden]), #screen-setup:not([hidden])", timeout=10000)
    if page.is_visible("#screen-setup"):
        page.click('.choice[data-choice="offline"]')
    if page.is_visible("#screen-import"):
        page.click("#sampleBtn")
        page.wait_for_selector("#screen-imported:not([hidden])", timeout=30000)
        page.click("#impGo")
    page.wait_for_selector("#screen-dash:not([hidden])", timeout=30000)
    for tab in ("overview", "subs", "alerts", "txns"):
        page.click(f'.tab[data-tab="{tab}"]')
        overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 2, f"{tab} overflows {overflow}px at {width}px"
    page.screenshot(path=SHOTS / f"10_overview_{name}.png", full_page=True)
    assert errors == [], errors
    page.close()
