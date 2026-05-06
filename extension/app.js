/**
 * app.js — Aviva Tableau Extension
 *
 * Flow:
 *   1. Tableau initializes the extension
 *   2. User types a question and hits Ask
 *   3. POST /query to the Aviva FastAPI backend
 *   4. Display the answer + source badge
 *   5. Apply any returned filters to every worksheet in the dashboard
 *   6. Clear button removes all Aviva-applied filters
 */

const API_URL = "https://aviva-api.onrender.com";

// Human-readable labels for each data source
const SOURCE_LABELS = {
  sales_data:      "Sales",
  marketing_data:  "Marketing",
  facebook_ads:    "Facebook Ads",
  vendor_central:  "Amazon Vendor Central",
};

// Track which filters Aviva has applied so Clear can remove them cleanly
let appliedFilters = [];

// Store the init promise so applyFilters can await it even if the user
// asks a question before Tableau finishes initializing
let tableauInitPromise = null;

// ── DOM refs ──────────────────────────────────────────────────────────────────
const questionInput  = document.getElementById("question");
const askBtn         = document.getElementById("askBtn");
const statusEl       = document.getElementById("status");
const answerCard     = document.getElementById("answerCard");
const answerText     = document.getElementById("answerText");
const sourceBadge    = document.getElementById("sourceBadge");
const copyBtn        = document.getElementById("copyBtn");
const refreshBtn     = document.getElementById("refreshBtn");
const filtersSection = document.getElementById("filtersSection");
const filterPills    = document.getElementById("filterPills");
const sqlDetails     = document.getElementById("sqlDetails");
const sqlText        = document.getElementById("sqlText");
const clearBtn       = document.getElementById("clearBtn");

// ── Tableau init ──────────────────────────────────────────────────────────────
try {
  if (typeof tableau !== "undefined" && tableau.extensions) {
    tableauInitPromise = tableau.extensions.initializeAsync();
    tableauInitPromise
      .then(() => setStatus("Ready. Type a question above.", ""))
      .catch(err => {
        tableauInitPromise = null;
        setStatus("Ready. Type a question above.", "");
        console.warn("Tableau init failed:", err);
      });
  } else {
    setStatus("Ready. Type a question above.", "");
  }
} catch (e) {
  setStatus("Ready. Type a question above.", "");
}

// ── Event listeners ───────────────────────────────────────────────────────────
askBtn.addEventListener("click", handleAsk);
questionInput.addEventListener("keydown", e => {
  if (e.key === "Enter") handleAsk();
});
clearBtn.addEventListener("click", handleClear);
copyBtn.addEventListener("click", handleCopy);
refreshBtn.addEventListener("click", handleRefresh);

// ── Core handler ──────────────────────────────────────────────────────────────
async function handleAsk() {
  const question = questionInput.value.trim();
  if (!question) {
    setStatus("Please enter a question.", "error");
    return;
  }

  setLoading(true);
  setStatus("Analyzing your question...", "");
  hideAnswer();

  try {
    const response = await fetch(`${API_URL}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    const data = await response.json();

    // Display answer + source badge
    showAnswer(data);

    // Apply filters to Tableau dashboard
    if (data.filters && data.filters.length > 0) {
      await applyFilters(data.filters);
    } else {
      setStatus("Answer ready.", "success");
    }

  } catch (err) {
    setStatus("Error: " + err.message, "error");
    console.error(err);
  } finally {
    setLoading(false);
  }
}

// ── Apply filters to all worksheets ──────────────────────────────────────────
async function applyFilters(filters) {
  // Wait for Tableau to finish initializing before accessing dashboardContent
  if (tableauInitPromise) {
    try { await tableauInitPromise; } catch (e) { /* init failed, filters skipped */ }
  }

  if (typeof tableau === "undefined" || !tableau.extensions || !tableau.extensions.dashboardContent) {
    setStatus("Answer ready.", "success");
    return;
  }

  const dashboard = tableau.extensions.dashboardContent.dashboard;
  const worksheets = dashboard.worksheets;

  appliedFilters = filters;

  let applied = 0;
  const errors = [];

  for (const worksheet of worksheets) {
    for (const filter of filters) {
      try {
        await worksheet.applyFilterAsync(filter.field, filter.values, "replace");
        applied++;
      } catch (e) {
        // Silently skip sheets that don't have this dimension
        const msg = e.message || "";
        if (!msg.includes("invalid-fields") && !msg.includes("parameterError")) {
          errors.push(`${worksheet.name}/${filter.field}: ${msg}`);
        }
      }
    }
  }

  if (errors.length > 0 && applied === 0) {
    setStatus(`Filter error: ${errors[0]}`, "error");
  } else {
    setStatus("Answer ready. Filters applied.", "success");
  }
}

// ── Clear all Aviva-applied filters ──────────────────────────────────────────
async function handleClear() {
  if (!appliedFilters.length) {
    setStatus("No filters to clear.", "");
    return;
  }

  const dashboard = tableau.extensions.dashboardContent.dashboard;
  const worksheets = dashboard.worksheets;

  for (const worksheet of worksheets) {
    for (const filter of appliedFilters) {
      try {
        await worksheet.clearFilterAsync(filter.field);
      } catch (e) {
        console.warn(`Could not clear filter "${filter.field}" from "${worksheet.name}":`, e);
      }
    }
  }

  appliedFilters = [];
  filtersSection.classList.remove("visible");
  filterPills.innerHTML = "";
  setStatus("Filters cleared.", "");
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function showAnswer(data) {
  answerText.textContent = data.answer;

  // Copy button
  copyBtn.textContent = "Copy";
  copyBtn.classList.remove("copied");
  copyBtn.classList.add("visible");

  // Source badge
  if (data.table_name && SOURCE_LABELS[data.table_name]) {
    sourceBadge.textContent = SOURCE_LABELS[data.table_name];
    sourceBadge.classList.add("visible");
  } else {
    sourceBadge.classList.remove("visible");
  }

  // SQL
  if (data.sql) {
    sqlText.textContent = data.sql;
    sqlDetails.style.display = "";
  } else {
    sqlDetails.style.display = "none";
  }

  // Filter pills
  filterPills.innerHTML = "";
  if (data.filters && data.filters.length > 0) {
    for (const f of data.filters) {
      const pill = document.createElement("span");
      pill.className = "pill";
      pill.innerHTML = `<span class="pill-field">${f.field}:</span> ${f.values.join(", ")}`;
      filterPills.appendChild(pill);
    }
    filtersSection.classList.add("visible");
  } else {
    filtersSection.classList.remove("visible");
  }

  answerCard.classList.add("visible");
}

function hideAnswer() {
  answerCard.classList.remove("visible");
  filtersSection.classList.remove("visible");
  sourceBadge.classList.remove("visible");
  copyBtn.classList.remove("visible");
}

function handleCopy() {
  const text = answerText.textContent;
  if (!text) return;

  // navigator.clipboard is blocked inside Tableau's iframe — use execCommand fallback
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.cssText = "position:fixed;top:0;left:0;opacity:0;pointer-events:none;";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);

  copyBtn.textContent = "Copied!";
  copyBtn.classList.add("copied");
  setTimeout(() => {
    copyBtn.textContent = "Copy";
    copyBtn.classList.remove("copied");
  }, 2000);
}

function setLoading(loading) {
  askBtn.disabled = loading;
  askBtn.textContent = loading ? "Thinking..." : "Ask";
  questionInput.disabled = loading;
}

function setStatus(message, type) {
  statusEl.textContent = message;
  statusEl.className = type || "";
}

async function handleRefresh() {
  refreshBtn.disabled = true;
  refreshBtn.classList.add("refreshing");
  refreshBtn.textContent = "⟳ Refreshing...";
  setStatus("Refreshing all data sources...", "");

  try {
    const response = await fetch(`${API_URL}/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });

    if (!response.ok) throw new Error(`API error: ${response.status}`);

    const data = await response.json();
    const allOk = Object.values(data.results).every(v => v === "ok");
    const notConfigured = Object.values(data.results).every(v => v === "not configured");

    if (notConfigured) {
      setStatus("Refresh: n8n webhooks not configured yet.", "error");
    } else if (allOk) {
      setStatus("All data sources refreshed.", "success");
    } else {
      const summary = Object.entries(data.results).map(([k, v]) => `${k}: ${v}`).join(" | ");
      setStatus(`Refresh complete — ${summary}`, "");
    }
  } catch (err) {
    setStatus("Refresh error: " + err.message, "error");
  } finally {
    refreshBtn.disabled = false;
    refreshBtn.classList.remove("refreshing");
    refreshBtn.textContent = "⟳ Refresh data";
  }
}
