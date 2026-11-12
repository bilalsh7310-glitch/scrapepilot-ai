/* ScrapePilot AI — single-page frontend.
   All data comes from the Flask API. Nothing is hardcoded or faked. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  let sessionId = null;
  let sessionMeta = null;
  let pages = [];
  let pollTimer = null;
  let pagePage = 1;
  const PAGE_SIZE = 15;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
  function showNotice(msg, kind) {
    const n = $("#notice");
    n.textContent = msg;
    n.className = "notice " + (kind || "error");
    n.classList.remove("hidden");
    if (kind === "ok") setTimeout(() => n.classList.add("hidden"), 6000);
  }
  function hideNotice() { $("#notice").classList.add("hidden"); }
  async function api(path, opts) {
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || ("Request failed: " + res.status));
    return data;
  }

  /* ---------- navigation ---------- */
  const TITLES = { overview: "Overview", scraper: "Website Scraper", pages: "All Discovered Pages",
    services: "Services Pages", products: "Products", contact: "Contact Information",
    purpose: "Purpose / About Pages", company: "Company Information", blogs: "Blog & Articles",
    seo: "SEO Analysis", ai: "AI Assistant", history: "Scraping History", export: "Export Data",
    settings: "Settings" };
  function showSection(name) {
    $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.section === name));
    $$(".section").forEach((s) => s.classList.toggle("active", s.id === "sec-" + name));
    $("#pageTitle").textContent = TITLES[name] || name;
    $("#sidebar").classList.remove("open");
    if (name === "history") loadHistory();
    if (name === "settings") loadSettings();
  }
  $$("#nav button").forEach((b) => b.addEventListener("click", () => showSection(b.dataset.section)));
  $("#menuBtn").addEventListener("click", () => $("#sidebar").classList.toggle("open"));

  /* ---------- theme ---------- */
  const themeBtn = $("#themeBtn");
  function setTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    localStorage.setItem("scrapepilot-theme", t);
  }
  setTheme(localStorage.getItem("scrapepilot-theme") || "dark");
  themeBtn.addEventListener("click", () => {
    setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });

  /* ---------- config / key status ---------- */
  fetch("/api/config").then((r) => r.json()).then((c) => {
    $("#keyStatus").textContent = c.api_key_configured
      ? "AI ready — OpenRouter key set (" + c.model + ")"
      : "AI off — no OpenRouter key (scraping still works)";
    $("#apiBadge") && ($("#apiBadge").textContent = c.api_key_configured ? "AI: on" : "AI: off");
  }).catch(() => { $("#keyStatus").textContent = "Could not reach the backend."; });

  /* ---------- scrape ---------- */
  $("#scrapeBtn").addEventListener("click", async () => {
    const url = $("#urlInput").value.trim();
    if (!url) { showNotice("Enter a website URL first."); return; }
    hideNotice();
    const btn = $("#scrapeBtn");
    btn.disabled = true;
    btn.textContent = "Scraping…";
    const split = (v) => v.split(",").map((x) => x.trim()).filter(Boolean);
    try {
      const data = await api("/api/scrape", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          scrape_all: $("#scrapeAll").checked,
          max_pages: parseInt($("#maxPages").value, 10) || 25,
          max_depth: parseInt($("#maxDepth").value, 10) || 2,
          timeout: parseFloat($("#timeout").value) || 15,
          delay: parseFloat($("#delay").value) || 0.5,
          include_patterns: split($("#includePat").value),
          exclude_patterns: split($("#excludePat").value),
          js_rendering: $("#jsRendering").checked,
        }),
      });
      $("#progressBox").classList.remove("hidden");
      pollStatus(data.job_id);
    } catch (e) {
      showNotice(e.message);
      btn.disabled = false;
      btn.textContent = "▶ Start Scraping";
    }
  });

  function pollStatus(jobId) {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const job = await api("/api/scrape/status/" + jobId);
        const p = job.progress || {};
        const done = p.done || 0, max = p.max_pages || 0;
        $("#progressBar").style.width = max ? Math.min(100, (done / max) * 100) + "%" : "8%";
        $("#progressText").textContent =
          (p.phase || job.status) + " — " + done + (max ? " / " + max + " pages" : " pages")
          + (p.current_url ? " — " + p.current_url : "");
        if (job.status === "completed") {
          clearInterval(pollTimer);
          $("#scrapeBtn").disabled = false;
          $("#scrapeBtn").textContent = "▶ Start Scraping";
          showNotice("Scrape complete — " + (job.stats ? job.stats.successful + " pages scraped, " + job.stats.failed + " failed." : ""), "ok");
          loadSession(job.session_id);
        } else if (job.status === "failed") {
          clearInterval(pollTimer);
          $("#scrapeBtn").disabled = false;
          $("#scrapeBtn").textContent = "▶ Start Scraping";
          showNotice("Scrape failed: " + (job.error || "unknown error"));
        }
      } catch (e) {
        clearInterval(pollTimer);
        $("#scrapeBtn").disabled = false;
        $("#scrapeBtn").textContent = "▶ Start Scraping";
        showNotice("Lost contact with the job: " + e.message);
      }
    }, 1500);
  }

  /* ---------- session loading & rendering ---------- */
  async function loadSession(id) {
    try {
      const data = await api("/api/history/" + id);
      sessionId = id;
      sessionMeta = data.session;
      pages = data.pages || [];
      $("#sessionBadge").textContent = sessionMeta.url + " — " + sessionMeta.status;
      $("#latestSession").innerHTML = "<strong>" + esc(sessionMeta.url) + "</strong><br>Status: "
        + esc(sessionMeta.status) + " · Started: " + esc(sessionMeta.started_at || "")
        + " · Pages: " + (data.summary ? data.summary.total_discovered : pages.length);
      renderStats(data.summary);
      renderPages();
      renderServices();
      renderProducts();
      renderContact();
      renderPurpose();
      renderCompany();
      renderBlogs();
      renderSeo();
      $("#results") && $("#results").classList.remove("hidden");
      showSection("overview");
    } catch (e) {
      showNotice(e.message);
    }
  }

  function statCard(value, label) {
    return '<div class="stat"><b>' + esc(value) + '</b><span>' + esc(label) + '</span></div>';
  }
  function renderStats(s) {
    if (!s) { $("#statsGrid").innerHTML = ""; return; }
    $("#statsGrid").innerHTML =
      statCard(s.total_discovered, "Pages discovered") +
      statCard(s.successful, "Successfully scraped") +
      statCard(s.failed, "Failed pages") +
      statCard(s.services_pages, "Services pages") +
      statCard(s.services_found, "Services found") +
      statCard(s.products_found, "Products found") +
      statCard(s.purpose_pages, "Purpose / About pages") +
      statCard(s.internal_links, "Internal links") +
      statCard(s.external_links, "External links") +
      statCard(s.images, "Images");
  }
  function setCount(id, n) { const el = $(id); if (el) el.textContent = n == null ? "" : "(" + n + ")"; }

  /* ---------- pages table ---------- */
  function filteredPages() {
    const q = ($("#pageSearch").value || "").toLowerCase();
    const cat = $("#pageFilter").value;
    return pages.filter((p) =>
      (!cat || (p.category || "") === cat) &&
      (!q || (p.title || "").toLowerCase().includes(q) || p.url.toLowerCase().includes(q)));
  }
  function renderPages() {
    const cats = [...new Set(pages.map((p) => p.category || "other"))].sort();
    const sel = $("#pageFilter");
    const cur = sel.value;
    sel.innerHTML = '<option value="">All categories</option>' +
      cats.map((c) => '<option value="' + esc(c) + '">' + esc(c) + '</option>').join("");
    sel.value = cur;
    const list = filteredPages();
    const totalPages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
    if (pagePage > totalPages) pagePage = totalPages;
    const slice = list.slice((pagePage - 1) * PAGE_SIZE, pagePage * PAGE_SIZE);
    setCount("#pagesCount", list.length);
    $("#pagesEmpty").classList.toggle("hidden", list.length > 0);
    $("#pagesTable tbody").innerHTML = slice.map((p) => {
      return "<tr><td>" + esc(p.title || "(no title)") + "</td>" +
        '<td><a href="' + esc(p.url) + '" target="_blank" rel="noopener">' + esc(p.url) + "</a></td>" +
        "<td>" + esc(p.category || "") + "</td>" +
        "<td>" + (p.status_code == null ? "—" : esc(p.status_code)) + "</td>" +
        "<td>" + esc(p.scrape_status || "") + (p.error ? "<br><span class='muted small'>" + esc(p.error) + "</span>" : "") + "</td>" +
        "<td><button class='ghost-btn' data-copy='" + esc(p.url) + "'>Copy URL</button> " +
        "<button class='ghost-btn' data-del='" + p.id + "'>Delete</button></td></tr>";
    }).join("");
    $("#pagesPageInfo").textContent = "Page " + pagePage + " of " + totalPages + " — " + list.length + " pages";
  }
  $("#pageSearch").addEventListener("input", () => { pagePage = 1; renderPages(); });
  $("#pageFilter").addEventListener("change", () => { pagePage = 1; renderPages(); });
  $("#pageRefresh").addEventListener("click", () => { if (sessionId) loadSession(sessionId); });
  $("#pagesPrev").addEventListener("click", () => { if (pagePage > 1) { pagePage--; renderPages(); } });
  $("#pagesNext").addEventListener("click", () => { pagePage++; renderPages(); });
  document.addEventListener("click", async (e) => {
    const copyBtn = e.target.closest("[data-copy]");
    if (copyBtn) {
      try { await navigator.clipboard.writeText(copyBtn.dataset.copy); showNotice("URL copied.", "ok"); }
      catch (_) { showNotice("Copy failed — select the URL manually."); }
      return;
    }
    const delBtn = e.target.closest("[data-del]");
    if (delBtn && sessionId) {
      if (!confirm("Delete this page record?")) return;
      try { await api("/api/pages/" + delBtn.dataset.del, { method: "DELETE" }); loadSession(sessionId); }
      catch (err) { showNotice(err.message); }
    }
  });

  async function fetchKind(kind) {
    if (!sessionId) return null;
    return api("/api/" + kind + "?session_id=" + encodeURIComponent(sessionId));
  }
  async function renderServices() {
    const box = $("#servicesList"), empty = $("#servicesEmpty");
    if (!sessionId) { box.innerHTML = ""; empty.classList.remove("hidden"); setCount("#servicesCount", 0); return; }
    const d = await fetchKind("services");
    const list = d.data || [];
    setCount("#servicesCount", list.length);
    empty.classList.toggle("hidden", list.length > 0);
    box.innerHTML = list.map((s) => '<div class="item"><h3><a href="' + esc(s.url) + '" target="_blank" rel="noopener">' +
      esc(s.service_name) + '</a></h3><dl class="kv">' +
      "<dt>URL</dt><dd>" + esc(s.url) + "</dd>" +
      "<dt>Description</dt><dd>" + esc(s.description || "Not Found") + "</dd>" +
      "<dt>Meta title</dt><dd>" + esc(s.meta_title || "Not Found") + "</dd>" +
      "<dt>Status</dt><dd>" + esc(s.status || "") + "</dd></dl></div>").join("");
  }
  async function renderProducts() {
    const box = $("#productsList"), empty = $("#productsEmpty");
    if (!sessionId) { box.innerHTML = ""; empty.classList.remove("hidden"); setCount("#productsCount", 0); return; }
    const d = await fetchKind("products");
    const list = d.data || [];
    setCount("#productsCount", list.length);
    empty.classList.toggle("hidden", list.length > 0);
    box.innerHTML = list.map((p) => '<div class="item"><h3><a href="' + esc(p.url) + '" target="_blank" rel="noopener">' +
      esc(p.product_name) + '</a></h3><dl class="kv">' +
      "<dt>Price</dt><dd>" + esc(p.price || "Not Found") + "</dd>" +
      "<dt>Description</dt><dd>" + esc(p.description || "Not Found") + "</dd></dl></div>").join("");
  }
  async function renderContact() {
    const box = $("#contactBox"), empty = $("#contactEmpty");
    if (!sessionId) { box.innerHTML = ""; empty.classList.remove("hidden"); return; }
    const d = await fetchKind("contact");
    const c = d.data || {};
    const has = (c.emails && c.emails[0] && c.emails[0].value !== "Not Found") ||
      (c.phones && c.phones[0] && c.phones[0].value !== "Not Found") ||
      (c.address && c.address[0] && c.address[0].value !== "Not Found");
    empty.classList.toggle("hidden", has);
    const rows = (arr, label) => (arr || []).map((x) =>
      "<dt>" + label + "</dt><dd>" + esc(x.value) + (x.source_url ? " <span class='muted small'>(from " + esc(x.source_url) + ")</span>" : "") + "</dd>").join("");
    box.innerHTML = '<dl class="kv">' +
      "<dt>Business name</dt><dd>" + esc(c.business_name || "Not Found") + "</dd>" +
      rows(c.emails, "Email") + rows(c.phones, "Phone") + rows(c.address, "Address") +
      "<dt>Contact page</dt><dd>" + esc(c.contact_page_url || "Not Found") + "</dd>" +
      "<dt>Opening hours</dt><dd>" + esc(c.opening_hours || "Not Found") + "</dd>" +
      (c.social || []).map((s) => "<dt>" + esc(s.platform) + "</dt><dd>" + esc(s.url || "Not Found") + "</dd>").join("") +
      "</dl>";
  }
  async function renderPurpose() {
    const box = $("#purposeList"), empty = $("#purposeEmpty");
    if (!sessionId) { box.innerHTML = ""; empty.classList.remove("hidden"); setCount("#purposeCount", 0); return; }
    const d = await fetchKind("purpose");
    const list = d.data || [];
    setCount("#purposeCount", list.length);
    empty.classList.toggle("hidden", list.length > 0);
    box.innerHTML = list.map((p) => '<div class="item"><h3><a href="' + esc(p.url) + '" target="_blank" rel="noopener">' +
      esc(p.page_title) + '</a></h3><dl class="kv">' +
      "<dt>Purpose</dt><dd>" + esc(p.purpose_statement || "Not Found") + "</dd>" +
      "<dt>Mission</dt><dd>" + esc(p.mission || "Not Found") + "</dd>" +
      "<dt>Vision</dt><dd>" + esc(p.vision || "Not Found") + "</dd></dl></div>").join("");
  }
  async function renderCompany() {
    const box = $("#companyBox");
    if (!sessionId) { box.innerHTML = "<p class='muted'>No session yet — run a scrape first.</p>"; return; }
    const d = await fetchKind("company");
    const c = d.data || {};
    box.innerHTML = '<dl class="kv">' +
      "<dt>Company name</dt><dd>" + esc(c.company_name || "Not Found") + "</dd>" +
      "<dt>Overview</dt><dd>" + esc(c.overview || "Not Found") + "</dd>" +
      "<dt>History</dt><dd>" + esc(c.history || "Not Found") + "</dd>" +
      "<dt>Source</dt><dd>" + esc(c.source_url || "") + "</dd></dl>";
  }
  async function renderBlogs() {
    const box = $("#blogsList"), empty = $("#blogsEmpty");
    if (!sessionId) { box.innerHTML = ""; empty.classList.remove("hidden"); setCount("#blogsCount", 0); return; }
    const d = await fetchKind("blogs");
    const list = d.data || [];
    setCount("#blogsCount", list.length);
    empty.classList.toggle("hidden", list.length > 0);
    box.innerHTML = list.map((b) => '<div class="item"><h3><a href="' + esc(b.url) + '" target="_blank" rel="noopener">' +
      esc(b.title) + '</a></h3><p class="muted">' + esc(b.excerpt || "") + "</p></div>").join("");
  }
  async function renderSeo() {
    const countsBox = $("#seoCounts"), listBox = $("#seoList"), empty = $("#seoEmpty");
    if (!sessionId) { countsBox.innerHTML = ""; listBox.innerHTML = ""; empty.classList.remove("hidden"); return; }
    const d = await api("/api/seo-audit?session_id=" + encodeURIComponent(sessionId));
    const a = d.audit || { findings: [], counts: {} };
    empty.classList.toggle("hidden", (a.findings || []).length > 0);
    countsBox.innerHTML = Object.entries(a.counts || {}).map(([k, v]) => statCard(v, k)).join("");
    listBox.innerHTML = '<div class="table-wrap"><table><thead><tr><th>Severity</th><th>Issue</th><th>URL</th><th>Evidence</th><th>Explanation</th></tr></thead><tbody>' +
      (a.findings || []).map((f) => "<tr><td><span class='sev sev-" + esc(f.severity) + "'>" + esc(f.severity) + "</span></td>" +
        "<td>" + esc(f.check) + "</td><td>" + esc(f.url) + "</td><td>" + esc(f.evidence || "") + "</td><td>" + esc(f.explanation || "") + "</td></tr>").join("") +
      "</tbody></table></div>";
  }

  /* ---------- AI chat ---------- */
  function addMsg(text, cls) {
    const div = document.createElement("div");
    div.className = "msg " + cls;
    div.textContent = text;
    $("#chatLog").appendChild(div);
    div.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  async function askAI(question) {
    if (!question) return;
    addMsg(question, "user");
    try {
      const d = await api("/api/ai/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, session_id: sessionId || "" }),
      });
      addMsg(d.answer || "(no answer)", "ai");
    } catch (e) {
      addMsg(e.message, "error");
    }
  }
  $("#chatSend").addEventListener("click", () => {
    const q = $("#chatInput").value.trim();
    $("#chatInput").value = "";
    askAI(q);
  });
  $("#chatInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { const q = e.target.value.trim(); e.target.value = ""; askAI(q); }
  });
  $$(".chips button").forEach((b) => b.addEventListener("click", () => askAI(b.dataset.q)));

  /* ---------- history ---------- */
  async function loadHistory() {
    try {
      const d = await api("/api/history");
      const list = d.sessions || [];
      $("#historyEmpty").classList.toggle("hidden", list.length > 0);
      $("#historyTable tbody").innerHTML = list.map((s) =>
        "<tr><td>" + esc(s.url) + "</td><td>" + esc((s.started_at || "").replace("T", " ").slice(0, 19)) + "</td>" +
        "<td>" + esc(s.status) + "</td><td>" + (s.discovered_count || 0) + "</td>" +
        "<td>" + (s.success_count || 0) + " / " + (s.failed_count || 0) + "</td>" +
        "<td><button class='ghost-btn' data-load='" + esc(s.id) + "'>Open</button></td></tr>").join("");
    } catch (e) {
      $("#historyEmpty").textContent = "Could not load history: " + e.message;
      $("#historyEmpty").classList.remove("hidden");
    }
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-load]");
    if (b) loadSession(b.dataset.load);
  });

  /* ---------- exports ---------- */
  $$(".exportBtn").forEach((b) => b.addEventListener("click", () => {
    if (!sessionId) { showNotice("Run a scrape first, or open a session from History."); return; }
    const kind = $("#exportKind").value;
    const fmt = b.dataset.fmt;
    $("#exportMsg").textContent = "Downloading " + fmt.toUpperCase() + " (" + kind + ")…";
    window.location.href = "/api/export/" + fmt + "?session_id=" + encodeURIComponent(sessionId)
      + "&kind=" + encodeURIComponent(kind);
  }));

  /* ---------- settings ---------- */
  async function loadSettings() {
    try {
      const c = await api("/api/config");
      $("#settingsBox").innerHTML =
        "<p>OpenRouter key configured: <strong>" + (c.api_key_configured ? "yes" : "no") + "</strong>" +
        "<br>Model: <code>" + esc(c.model) + "</code>" +
        "<br>Defaults — max pages: " + c.defaults.max_pages + ", depth: " + c.defaults.max_depth +
        ", timeout: " + c.defaults.timeout + "s, delay: " + c.defaults.delay + "s" +
        "<br>Caps — max pages: " + c.caps.max_pages + ", depth: " + c.caps.max_depth +
        "<br>JavaScript rendering: " + (c.js_rendering_available ? "available" : "not installed — plain HTML fetching") + "</p>";
    } catch (e) {
      $("#settingsBox").textContent = "Could not load settings: " + e.message;
    }
  }

  // Initial state: empty sections say Not Found, exactly as the spec requires.
  renderServices(); renderProducts(); renderContact(); renderPurpose();
  renderCompany(); renderBlogs(); renderSeo(); loadHistory();
})();
