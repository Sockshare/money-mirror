/* Money Mirror front-end. Plain JavaScript, no frameworks, no build step, no external libraries. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const show = (el) => el.removeAttribute("hidden");
  const hide = (el) => el.setAttribute("hidden", "");
  const CUR = () => localStorage.getItem("mm_currency") || "$";
  const fmt = (n) => (n < 0 ? "-" : "") + CUR() + Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmt0 = (n) => (n < 0 ? "-" : "") + CUR() + Math.round(Math.abs(n)).toLocaleString();
  const monthName = (ym) => { const [y, m] = ym.split("-"); return new Date(+y, +m - 1, 1).toLocaleString(undefined, { month: "short", year: "numeric" }); };
  const monthShort = (ym) => { const [y, m] = ym.split("-"); return new Date(+y, +m - 1, 1).toLocaleString(undefined, { month: "short" }); };

  let toastTimer = null;
  function toast(msg, kind) { const t = $("toast"); t.textContent = msg; t.className = "toast" + (kind ? " " + kind : ""); show(t); clearTimeout(toastTimer); toastTimer = setTimeout(() => hide(t), kind === "bad" ? 7000 : 3500); }

  const SERVER_DOWN = "The app's server isn't answering. Go back to the terminal window and start it again with: python app.py";
  async function api(path, opts = {}) {
    let res;
    try { res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts }); }
    catch (e) { if (e.name === "AbortError") throw e; throw new Error(SERVER_DOWN); }
    let data = null;
    try { data = await res.json(); } catch (_) { /* no body */ }
    if (!res.ok) { const msg = (data && (data.detail || data.message)) || `Something went wrong (${res.status}).`; throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg)); }
    return data;
  }

  const state = { status: null, data: null, txnOffset: 0, txnQuery: {} };
  const screens = ["setup", "import", "imported", "dash"];
  function go(name) { hide($("toast")); screens.forEach((s) => hide($("screen-" + s))); show($("screen-" + name)); name === "dash" ? show($("tabs")) : hide($("tabs")); window.scrollTo({ top: 0, behavior: "smooth" }); }

  // ---------- status ----------
  async function refreshStatus(probe) {
    try { state.status = await api("/api/status" + (probe ? "?probe=1" : "")); }
    catch (e) { $("engineText").textContent = "Can't reach the app"; $("engineDot").className = "dot bad"; toast(e.message, "bad"); return; }
    const p = state.status.provider;
    const names = { ollama: "AI on my computer", openai: "Cloud AI (OpenAI)", gemini: "Cloud AI (Gemini)", offline: "No AI" };
    $("engineText").textContent = names[p.name] + (p.ok ? "" : " — problem");
    $("engineDot").className = "dot " + (p.ok ? (p.name === "offline" ? "warn" : "ok") : "bad");
    $("enginePill").title = p.message;
    $("privacyText").textContent = p.local ? "Your transactions stay on this computer." : "Cloud AI is on: only merchant names and your typed questions are sent — never amounts, dates, or your file.";
    $("askPrivacy").textContent = p.name === "offline" ? "No AI: questions are understood with built-in rules. Try the examples above for the phrasing that works best." : p.local ? "Your question goes to the AI on this computer, which turns it into a search. The numbers are computed locally." : "Only your question text is sent to the cloud AI, which turns it into a search. Your transactions never leave this computer.";
    const cats = state.status.categories;
    $("fCategory").innerHTML = '<option value="">All categories</option>' + cats.map((c) => `<option>${esc(c)}</option>`).join("");
  }

  // ---------- first run ----------
  async function initSetup() {
    const o = state.status.ollama, el = $("ollamaStatus");
    if (o.running && o.models.length) { el.textContent = "✓ Found Ollama with " + o.models[0]; el.className = "choice-status ok"; }
    else if (o.running) { el.textContent = "Ollama is running but has no model yet (we'll show you how)"; el.className = "choice-status"; }
    else { el.textContent = "Not found — we'll show you how to install it (free)"; el.className = "choice-status bad"; }
    document.querySelectorAll(".choice").forEach((btn) => {
      btn.onclick = async () => {
        try {
          const c = btn.dataset.choice;
          if (c === "ollama") {
            await api("/api/settings", { method: "POST", body: JSON.stringify({ provider: "ollama", model: o.models[0] || "llama3.2:3b", setup_complete: true }) });
            await refreshStatus(); go("import");
            if (!(o.running && o.models.length)) { openSettings(); toast("Follow the steps in the box to install Ollama, then click Test.", ""); }
          } else if (c === "cloud") {
            await api("/api/settings", { method: "POST", body: JSON.stringify({ provider: "openai", setup_complete: true }) });
            await refreshStatus(); go("import"); openSettings(); toast("Paste your API key, click Test, then Save.", "");
          } else {
            await api("/api/settings", { method: "POST", body: JSON.stringify({ provider: "offline", setup_complete: true }) });
            await refreshStatus(); go("import");
          }
        } catch (e) { toast("Couldn't save that choice: " + e.message, "bad"); }
      };
    });
  }

  // ---------- import ----------
  const dz = $("dropzone"), fileInput = $("fileInput");
  dz.onclick = () => fileInput.click();
  dz.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } };
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", (e) => importFiles([...e.dataTransfer.files]));
  fileInput.onchange = () => { importFiles([...fileInput.files]); fileInput.value = ""; };
  $("sampleBtn").onclick = async () => {
    $("sampleBtn").disabled = true; $("sampleBtn").textContent = "Loading example…";
    try { showImported(await api("/api/import/sample", { method: "POST" })); }
    catch (e) { toast(e.message, "bad"); }
    finally { $("sampleBtn").disabled = false; $("sampleBtn").textContent = "👀 Try it with example data"; }
  };
  async function importFiles(files) {
    if (!files.length) return;
    let last = null, added = 0, errors = [];
    for (const f of files) {
      const fd = new FormData(); fd.append("file", f);
      try {
        const res = await fetch("/api/import", { method: "POST", body: fd }).catch(() => { throw new Error(SERVER_DOWN); });
        const data = await res.json().catch(() => null);
        if (!res.ok) throw new Error((data && data.detail) || "Could not read that file.");
        last = data; added += data.added;
      } catch (e) { errors.push(`${f.name}: ${e.message}`); }
    }
    if (last) { last.added = added; if (errors.length) last.warnings = [...last.warnings, ...errors]; showImported(last); }
    else toast(errors.join("\n") || "Nothing was imported.", "bad");
  }
  function showImported(d) {
    $("impHeadline").textContent = d.added ? `Imported ${d.added.toLocaleString()} transaction${d.added !== 1 ? "s" : ""}` : "Nothing new to add";
    $("impSub").textContent = (d.added ? `From ${d.first_date} to ${d.last_date}. ` : "") + (d.duplicates ? `${d.duplicates.toLocaleString()} were already in your data, so they were skipped. ` : "") + `You now have ${d.total.toLocaleString()} transactions.`;
    const w = d.warnings || [];
    if (w.length) { $("impWarnings").innerHTML = w.map((x) => `<div>ℹ️ ${esc(x)}</div>`).join(""); show($("impWarnings")); } else hide($("impWarnings"));
    $("impPreview").innerHTML = d.preview && d.preview.length ? `<p class="muted small">First few rows, as the app read them (check they look right):</p><table><tr><th>Date</th><th>Place</th><th>Category</th><th class="amt">Amount</th></tr>${d.preview.map((r) => `<tr><td>${esc(r.date)}</td><td>${esc(r.merchant)}<div class="desc">${esc(r.description)}</div></td><td>${esc(r.category)}</td><td class="amt ${r.amount > 0 ? "pos" : ""}">${fmt(r.amount)}</td></tr>`).join("")}</table>` : "";
    const u = d.unknown_merchants || [];
    if (u.length) {
      $("impUnknownTitle").textContent = `${u.length} place${u.length !== 1 ? "s" : ""} the app couldn't categorize: ${u.slice(0, 6).join(", ")}${u.length > 6 ? "…" : ""}`;
      const p = state.status.provider;
      if (p.name !== "offline" && p.ok) { show($("impAiBtn")); $("impAiOffer").textContent = "Or let the AI suggest categories (only the names are sent)."; }
      else { hide($("impAiBtn")); $("impAiOffer").textContent = ""; }
      $("impAiOut").textContent = "";
      $("impAiBtn").onclick = async () => {
        $("impAiBtn").disabled = true; $("impAiOut").textContent = "Asking the AI…";
        try { const r = await api("/api/ai/categorize", { method: "POST", body: JSON.stringify({ merchants: u }) }); const n = Object.keys(r.learned).length; $("impAiOut").textContent = n ? `✓ Named ${n} of ${u.length}.` : "The AI couldn't place them. You can set them by hand in Transactions."; }
        catch (e) { $("impAiOut").textContent = "✗ " + e.message; }
        finally { $("impAiBtn").disabled = false; }
      };
      show($("impUnknown"));
    } else hide($("impUnknown"));
    go("imported");
  }
  $("impGo").onclick = () => loadDash();
  $("impMore").onclick = () => { $("importTitle").textContent = "Add another bank file"; show($("importBackRow")); go("import"); };
  $("importBtn").onclick = () => { $("importTitle").textContent = "Add another bank file"; state.status.transactions ? show($("importBackRow")) : hide($("importBackRow")); go("import"); };
  $("importBack").onclick = () => loadDash();
  $("brandLink").onclick = (e) => { e.preventDefault(); if (state.status && state.status.transactions) loadDash(); };

  // ---------- dashboard ----------
  async function loadDash() {
    try {
      const d = await api("/api/overview");
      if (d.empty) { hide($("importBackRow")); go("import"); return; }
      state.data = d;
      await refreshStatus();
      renderOverview(d); renderSubs(d); renderAlerts(d);
      state.txnQuery = {}; $("fSearch").value = ""; $("fCategory").value = ""; $("fMonth").value = "";
      $("fMonth").innerHTML = '<option value="">All months</option>' + d.monthly.slice().reverse().map((m) => `<option value="${m.month}">${monthName(m.month)}</option>`).join("");
      await loadTxns(true);
      $("asOf").textContent = `Data from ${d.overview.first_date} to ${d.overview.last_date} · ${d.overview.transactions.toLocaleString()} transactions · "this month" = ${monthName(d.as_of.slice(0, 7))}`;
      go("dash"); setTab("overview");
    } catch (e) { toast(e.message, "bad"); }
  }

  function setTab(name) {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    ["overview", "subs", "alerts", "txns", "ask"].forEach((p) => (p === name ? show($("pane-" + p)) : hide($("pane-" + p))));
    if (name === "ask") $("askInput").focus();
  }
  document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => setTab(t.dataset.tab)));

  function renderOverview(d) {
    const o = d.overview, tm = o.this_month, lm = o.last_month;
    $("sThis").textContent = fmt0(tm.spent);
    const dataIsCurrent = (Date.now() - new Date(o.last_date).getTime()) < 40 * 86400000;
    $("sThisSub").textContent = tm.pace && dataIsCurrent ? `On pace for about ${fmt0(tm.pace)}` : `${monthName(tm.label)} · data through ${o.last_date}`;
    $("sLast").textContent = fmt0(lm.spent);
    const diff = tm.spent && lm.spent ? ((tm.pace || tm.spent) - lm.spent) : 0;
    $("sLastSub").textContent = monthName(lm.label) + (lm.income ? ` · earned ${fmt0(lm.income)}` : "");
    $("sAvg").textContent = fmt0(o.avg_month_spend);
    $("sAvgSub").textContent = `Average over ${o.full_months} full month${o.full_months !== 1 ? "s" : ""}`;
    const active = d.subscriptions.filter((s) => s.status === "active");
    const monthlyTotal = active.reduce((a, s) => a + s.amount * ({ monthly: 1, weekly: 4.33, "every 2 weeks": 2.17, "every 3 months": 1 / 3, yearly: 1 / 12 }[s.cadence] || 1), 0);
    $("sSubs").textContent = fmt0(monthlyTotal) + "/mo";
    $("sSubsSub").textContent = `${active.length} recurring charge${active.length !== 1 ? "s" : ""} · ${fmt0(monthlyTotal * 12)} a year`;

    // monthly chart (SVG)
    const months = d.monthly, W = 640, H = 240, padL = 56, padB = 28, padT = 14;
    const maxV = Math.max(1, ...months.map((m) => Math.max(m.spent, m.income)));
    const bw = (W - padL - 10) / Math.max(1, months.length);
    const y = (v) => padT + (H - padT - padB) * (1 - v / maxV);
    let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Spending by month">`;
    [0, 0.5, 1].forEach((f) => { const v = maxV * f; svg += `<line x1="${padL}" x2="${W - 10}" y1="${y(v)}" y2="${y(v)}" stroke="#e3e6ee"/><text x="${padL - 6}" y="${y(v) + 4}" font-size="11" text-anchor="end" fill="#5d6475">${fmt0(v)}</text>`; });
    months.forEach((m, i) => {
      const x = padL + i * bw + bw * 0.15, w = bw * 0.7;
      svg += `<rect x="${x}" y="${y(m.spent)}" width="${w}" height="${H - padB - y(m.spent)}" rx="4" fill="#0f8b6e" opacity=".9"><title>${monthName(m.month)}: spent ${fmt(m.spent)}</title></rect>`;
      svg += `<text x="${x + w / 2}" y="${H - 8}" font-size="11" text-anchor="middle" fill="#5d6475">${monthShort(m.month)}</text>`;
    });
    const pts = months.map((m, i) => `${padL + i * bw + bw / 2},${y(m.income)}`).join(" ");
    if (months.some((m) => m.income > 0)) svg += `<polyline points="${pts}" fill="none" stroke="#2f6fed" stroke-width="2.5" stroke-linejoin="round"/>` + months.map((m, i) => `<circle cx="${padL + i * bw + bw / 2}" cy="${y(m.income)}" r="3.5" fill="#2f6fed"><title>${monthName(m.month)}: income ${fmt(m.income)}</title></circle>`).join("");
    svg += "</svg>";
    $("chartMonths").innerHTML = svg;

    // categories (horizontal bars, clickable)
    const cats = o.top_categories, maxC = Math.max(1, ...cats.map((c) => c.amount));
    $("chartCats").innerHTML = cats.map((c) => `<div class="bar-row clickable" data-cat="${esc(c.category)}"><div>${esc(c.category)}</div><div class="track"><div class="fill" style="width:${(c.amount / maxC) * 100}%"></div></div><div class="v">${fmt0(c.amount)} <span class="muted small">${c.share}%</span></div></div>`).join("") || '<p class="empty">No spending found yet.</p>';
    $("chartCats").querySelectorAll("[data-cat]").forEach((el) => (el.onclick = () => { setTab("txns"); $("fCategory").value = el.dataset.cat; loadTxns(true); }));

    $("catChange").previousElementSibling.textContent = `📈 Biggest changes: ${monthName(o.compare.from)} → ${monthName(o.compare.to)}`;
    $("catChange").innerHTML = o.category_change.filter((c) => Math.abs(c.diff) >= 1).slice(0, 6).map((c) => `<div class="bar-row"><div>${esc(c.category)}</div><div class="muted small">${fmt0(c.last)} → ${fmt0(c.this)}</div><div class="v delta ${c.diff > 0 ? "up" : "down"}">${c.diff > 0 ? "+" : "−"}${fmt0(Math.abs(c.diff))}</div></div>`).join("") || '<p class="empty">Not enough data for two full months yet.</p>';
    $("topMerchants").innerHTML = o.top_merchants.slice(0, 8).map((m) => `<div class="bar-row clickable" data-m="${esc(m.merchant)}"><div>${esc(m.merchant)}</div><div class="muted small">${m.count} time${m.count !== 1 ? "s" : ""}</div><div class="v">${fmt0(m.amount)}</div></div>`).join("");
    $("topMerchants").querySelectorAll("[data-m]").forEach((el) => (el.onclick = () => openTxnModal({ merchant: el.dataset.m }, el.dataset.m)));

    // plain-language summary
    const top = cats[0], hikes = d.alerts.filter((a) => a.type === "price_increase"), dups = d.alerts.filter((a) => a.type === "duplicate"), fees = d.alerts.filter((a) => a.type === "fee");
    const parts = [`<b>In plain words:</b> over the last ${o.full_months} full month${o.full_months !== 1 ? "s" : ""} you spent about <b>${fmt0(o.avg_month_spend)}</b> a month.`];
    if (top) parts.push(`The biggest piece is <b>${esc(top.category)}</b> (${top.share}%).`);
    if (active.length) parts.push(`<b>${active.length}</b> things charge you regularly, adding up to about <b>${fmt0(monthlyTotal * 12)}</b> a year.`);
    if (hikes.length) parts.push(`<b>${hikes.length}</b> of them went up in price.`);
    if (dups.length) parts.push(`There ${dups.length === 1 ? "is" : "are"} <b>${dups.length}</b> possible double charge${dups.length !== 1 ? "s" : ""} worth checking.`);
    if (fees.length) parts.push(`You paid <b>${fmt0(fees.reduce((a, f) => a + f.amount, 0))}</b> in bank fees — often refundable if you ask.`);
    if (o.uncategorized) parts.push(`${o.uncategorized} transaction${o.uncategorized !== 1 ? "s" : ""} still need a category (Transactions tab).`);
    $("plainSummary").innerHTML = parts.join(" ");
  }

  function renderSubs(d) {
    const subs = d.subscriptions, active = subs.filter((s) => s.status === "active");
    const perMonth = active.reduce((a, s) => a + s.amount * ({ monthly: 1, weekly: 4.33, "every 2 weeks": 2.17, "every 3 months": 1 / 3, yearly: 1 / 12 }[s.cadence] || 1), 0);
    $("subMonthly").textContent = fmt0(perMonth); $("subYearly").textContent = fmt0(perMonth * 12); $("subCount").textContent = active.length;
    $("subList").innerHTML = subs.length ? subs.map((s) => `<div class="sub-row" data-m="${esc(s.merchant)}"><div><div class="name">${esc(s.merchant)}${s.status === "stopped" ? '<span class="tag stopped">stopped</span>' : ""}${s.price_change ? `<span class="tag up">up ${s.price_change.pct}%</span>` : ""}${s.variable ? '<span class="tag var">varies</span>' : ""}</div><div class="meta">${esc(s.category)} · ${s.cadence} · ${s.charges} charges since ${s.first_date}${s.next_expected ? ` · next around ${s.next_expected}` : ""}${s.price_change ? ` · was ${fmt(s.price_change.from)}` : ""}</div></div><div class="amt">${fmt(s.amount)}</div><div class="yr">${fmt0(s.yearly_cost)}/yr</div></div>`).join("") : '<p class="empty">No regular charges found yet. They show up once the same place has charged you 3 times on a rhythm.</p>';
    $("subList").querySelectorAll("[data-m]").forEach((el) => (el.onclick = () => openTxnModal({ merchant: el.dataset.m }, el.dataset.m)));
  }

  function renderAlerts(d) {
    const a = d.alerts, important = a.filter((x) => x.severity !== "low").length;
    if (important) { $("alertCount").textContent = important; show($("alertCount")); } else hide($("alertCount"));
    $("alertList").innerHTML = a.length ? a.map((x, i) => `<div class="alert-row ${x.severity}" data-i="${i}"><div class="t">${esc(x.title)}</div><div class="d">${esc(x.detail)} <span class="muted">· ${esc(x.date)}</span></div></div>`).join("") : '<p class="empty">Nothing unusual found. Nice.</p>';
    $("alertList").querySelectorAll("[data-i]").forEach((el) => (el.onclick = () => { const x = a[+el.dataset.i]; openTxnModal({ ids: x.ids }, x.title); }));
  }

  // ---------- transactions ----------
  function txnRows(items, editable) {
    const cats = state.status.categories;
    return `<table><tr><th>Date</th><th>Place</th><th>Category</th><th class="amt">Amount</th></tr>${items.map((t) => `<tr><td>${esc(t.date)}</td><td>${esc(t.merchant)}<div class="desc hide-m">${esc(t.description)}${t.account ? " · " + esc(t.account) : ""}</div></td><td>${editable ? `<select data-id="${t.id}">${cats.map((c) => `<option ${c === t.category ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>` : esc(t.category)}</td><td class="amt ${t.amount > 0 ? "pos" : ""}">${fmt(t.amount)}</td></tr>`).join("")}</table>`;
  }
  function bindCategoryEdits(root) {
    root.querySelectorAll("select[data-id]").forEach((sel) => (sel.onchange = async () => {
      try {
        const r = await api("/api/transactions/category", { method: "POST", body: JSON.stringify({ id: sel.dataset.id, category: sel.value, apply_to_merchant: true }) });
        toast(r.updated > 1 ? `Updated ${r.updated} transactions from that place — and remembered it.` : "Updated and remembered.", "ok");
        const d = await api("/api/overview"); state.data = d; renderOverview(d); renderSubs(d); renderAlerts(d);
      } catch (e) { toast(e.message, "bad"); }
    }));
  }
  async function loadTxns(reset) {
    if (reset) state.txnOffset = 0;
    const q = new URLSearchParams({ q: $("fSearch").value.trim(), category: $("fCategory").value, month: $("fMonth").value, limit: 100, offset: state.txnOffset });
    const d = await api("/api/transactions?" + q.toString());
    if (reset) $("txnTable").innerHTML = d.items.length ? txnRows(d.items, true) : '<p class="empty">No transactions match.</p>';
    else { const tmp = document.createElement("div"); tmp.innerHTML = txnRows(d.items, true); $("txnTable").querySelector("table").append(...tmp.querySelectorAll("tr:not(:first-child)")); }
    bindCategoryEdits($("txnTable"));
    state.txnOffset += d.items.length;
    state.txnOffset < d.total ? show($("txnMore")) : hide($("txnMore"));
    $("txnMore").textContent = `Show more (${(d.total - state.txnOffset).toLocaleString()} left)`;
  }
  let searchTimer = null;
  $("fSearch").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadTxns(true), 250); };
  $("fCategory").onchange = () => loadTxns(true);
  $("fMonth").onchange = () => loadTxns(true);
  $("fClear").onclick = () => { $("fSearch").value = ""; $("fCategory").value = ""; $("fMonth").value = ""; loadTxns(true); };
  $("txnMore").onclick = () => loadTxns(false);

  async function openTxnModal(filter, title) {
    let items = [];
    if (filter.ids) { items = (await api("/api/transactions?" + new URLSearchParams({ ids: filter.ids.join(","), limit: 500 }))).items; }
    else { items = (await api("/api/transactions?" + new URLSearchParams({ merchant: filter.merchant || "", limit: 300 }))).items; }
    $("mTxnTitle").textContent = title;
    const total = items.reduce((a, t) => a + (t.amount < 0 ? -t.amount : 0), 0);
    $("mTxnSub").textContent = `${items.length} transaction${items.length !== 1 ? "s" : ""} · ${fmt(total)} spent`;
    $("mTxnTable").innerHTML = txnRows(items, true); bindCategoryEdits($("mTxnTable"));
    openModal("modal-txns");
  }

  // ---------- ask ----------
  async function ask(q) {
    q = (q || $("askInput").value).trim();
    if (!q) { toast("Type a question first — for example: how much did I spend on groceries last month?", "bad"); return; }
    $("askBtn").disabled = true; $("askBtn").textContent = "Thinking…";
    const block = document.createElement("div"); block.className = "qa"; block.innerHTML = `<div class="q">${esc(q)}</div><div class="a muted">…</div>`; $("askThread").prepend(block);
    try {
      const d = await api("/api/ask", { method: "POST", body: JSON.stringify({ question: q }) });
      block.querySelector(".a").textContent = d.answer; block.querySelector(".a").classList.remove("muted");
      if (d.note) { const n = document.createElement("div"); n.className = "muted small"; n.textContent = "ℹ️ " + d.note; block.append(n); }
      if (d.result && d.result.items && d.result.items.length) {
        const det = document.createElement("details"); det.innerHTML = `<summary>Show the ${d.result.items.length} transaction${d.result.items.length !== 1 ? "s" : ""} behind this answer</summary>`;
        const tbl = document.createElement("div"); tbl.className = "txn-table"; tbl.innerHTML = txnRows(d.result.items, false); det.append(tbl); block.append(det);
      }
      $("askInput").value = "";
    } catch (e) { block.querySelector(".a").textContent = "Sorry — " + e.message; }
    finally { $("askBtn").disabled = false; $("askBtn").textContent = "Ask"; }
  }
  $("askBtn").onclick = () => ask();
  $("askInput").onkeydown = (e) => { if (e.key === "Enter") ask(); };
  document.querySelectorAll(".chip").forEach((c) => (c.onclick = () => { $("askInput").value = c.dataset.q; ask(c.dataset.q); }));

  // ---------- modals & settings ----------
  function openModal(id) { show($("modalBack")); show($(id)); }
  function closeModals() { hide($("modalBack")); document.querySelectorAll(".modal").forEach(hide); }
  $("modalBack").onclick = closeModals;
  document.querySelectorAll("[data-close]").forEach((b) => (b.onclick = closeModals));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModals(); });
  $("helpBtn").onclick = () => openModal("modal-help");

  async function openSettings() {
    if (!state.status) { toast("Settings aren't available until the app's server answers. Run: python scripts/selfcheck.py", "bad"); return; }
    await refreshStatus(true); // look for Ollama only when the user opens Settings
    const s = state.status.settings, o = state.status.ollama;
    document.querySelector(`input[name=prov][value=${s.provider}]`).checked = true; showProvPanel(s.provider);
    const models = o.models.length ? o.models : [s.provider === "ollama" ? s.model : "llama3.2:3b"];
    $("setOllamaModel").innerHTML = models.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("");
    if (s.provider === "ollama" && models.includes(s.model)) $("setOllamaModel").value = s.model;
    $("setOllamaHost").value = s.ollama_host;
    $("setOllamaInfo").textContent = o.running ? (o.models.length ? `Found ${o.models.length} model${o.models.length > 1 ? "s" : ""}.` : "Running, but no model downloaded.") : "Ollama is not running.";
    o.running && o.models.length ? hide($("ollamaHelp")) : show($("ollamaHelp"));
    $("setOpenaiKey").value = s.openai_api_key || ""; $("setOpenaiModel").value = s.provider === "openai" ? s.model : ""; $("setOpenaiUrl").value = s.openai_base_url;
    $("setGeminiKey").value = s.gemini_api_key || ""; $("setGeminiModel").value = s.provider === "gemini" ? s.model : "";
    $("setTestOut").textContent = "";
    $("setDataInfo").textContent = `${(state.status.transactions || 0).toLocaleString()} transactions from ${state.status.imports.length} file${state.status.imports.length !== 1 ? "s" : ""}, stored only on this computer in ${state.status.data_dir}`;
    $("setCurrency").value = CUR();
    const env = state.status.env_overrides || [];
    env.length ? (show($("setEnvNote")), $("setEnvNote").textContent = `Note: these settings are currently overridden by environment variables (${env.join(", ")}). Changes you save here won't take effect until you unset them.`) : hide($("setEnvNote"));
    openModal("modal-settings");
  }
  function showProvPanel(p) { document.querySelectorAll(".prov-panel").forEach((el) => el.classList.toggle("show", el.dataset.prov === p)); }
  document.querySelectorAll("input[name=prov]").forEach((r) => (r.onchange = () => { showProvPanel(r.value); $("setTestOut").textContent = ""; }));
  $("settingsBtn").onclick = openSettings; $("enginePill").onclick = openSettings;
  function collectSettings() {
    const provider = document.querySelector("input[name=prov]:checked").value;
    const body = { provider, ollama_host: $("setOllamaHost").value.trim() || "http://127.0.0.1:11434", openai_base_url: $("setOpenaiUrl").value.trim() || "https://api.openai.com/v1" };
    if (provider === "ollama") body.model = $("setOllamaModel").value;
    if (provider === "openai") body.model = $("setOpenaiModel").value.trim();
    if (provider === "gemini") body.model = $("setGeminiModel").value.trim();
    if (provider === "offline") body.model = "";
    const ok = $("setOpenaiKey").value.trim(); if (ok) body.openai_api_key = ok;
    const gk = $("setGeminiKey").value.trim(); if (gk) body.gemini_api_key = gk;
    return body;
  }
  $("setTest").onclick = async () => {
    $("setTestOut").textContent = "Testing…"; $("setTestOut").className = "small";
    try { const d = await api("/api/test-connection", { method: "POST", body: JSON.stringify(collectSettings()) }); $("setTestOut").textContent = (d.ok ? "✓ " : "✗ ") + d.message; $("setTestOut").className = "small " + (d.ok ? "status-ok" : "status-bad"); }
    catch (e) { $("setTestOut").textContent = "✗ " + e.message; $("setTestOut").className = "small status-bad"; }
  };
  $("setSave").onclick = async () => {
    localStorage.setItem("mm_currency", $("setCurrency").value || "$");
    try { const d = await api("/api/settings", { method: "POST", body: JSON.stringify({ ...collectSettings(), setup_complete: true }) }); await refreshStatus(); closeModals(); toast(d.provider.ok ? "Saved. " + d.provider.message : "Saved, but: " + d.provider.message, d.provider.ok ? "ok" : "bad"); }
    catch (e) { toast(e.message, "bad"); }
  };
  document.querySelectorAll("[data-clear-key]").forEach((b) => (b.onclick = async () => {
    const field = b.dataset.clearKey;
    try { await api("/api/settings", { method: "POST", body: JSON.stringify({ [field]: "" }) }); await refreshStatus(); $(field === "openai_api_key" ? "setOpenaiKey" : "setGeminiKey").value = ""; toast("Key removed from this computer.", "ok"); }
    catch (e) { toast(e.message, "bad"); }
  }));
  $("setClearData").onclick = async () => { if (!confirm("Delete all imported transactions from this computer? Learned categories are kept. This cannot be undone.")) return; await api("/api/data", { method: "DELETE" }); closeModals(); toast("All transactions deleted.", "ok"); await refreshStatus(); hide($("importBackRow")); go("import"); };
  $("setClearAll").onclick = async () => { if (!confirm("Delete everything — transactions AND learned categories? This cannot be undone.")) return; await api("/api/data?everything=true", { method: "DELETE" }); closeModals(); toast("Everything deleted.", "ok"); await refreshStatus(); hide($("importBackRow")); go("import"); };

  // ---------- boot ----------
  (async function boot() {
    await refreshStatus();
    if (!state.status) { go("import"); toast("The app couldn't load its settings. Try again in a moment, or run: python scripts/selfcheck.py", "bad"); return; }
    if (!state.status.settings.setup_complete) { await refreshStatus(true); await initSetup(); go("setup"); return; }
    if (state.status.transactions > 0) loadDash(); else { hide($("importBackRow")); go("import"); }
  })();
})();
