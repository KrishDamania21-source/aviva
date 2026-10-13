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

// Workbook field/calc metadata collected from Tableau on init
let workbookContext = null;

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
const connectionPicker = document.getElementById("connectionPicker");

// Per-session id for DuckDB "demo / no-creds" mode
const SESSION_ID = "tableau-" + Math.random().toString(36).slice(2, 12);
let sessionLoaded = false;

// ── Workbook context collection ───────────────────────────────────────────────
// Defensive caps so a huge workbook can't blow the prompt budget
const MAX_FIELDS_PER_SHEET = 40;
const MAX_SAMPLES_PER_FIELD = 6;
const MAX_FILTER_VALUES = 10;
const MAX_CONTEXT_BYTES = 24000;  // ~6k tokens; trimmed if exceeded

async function collectWorkbookContext() {
  if (typeof tableau === "undefined" || !tableau.extensions?.dashboardContent) return;

  const dashboard = tableau.extensions.dashboardContent.dashboard;
  const sheets = [];
  const seenDataSources = new Set();

  for (const ws of dashboard.worksheets) {
    try {
      const sheetEntry = { name: ws.name, fields: [], currentFilters: [] };

      // Collect fields from each data source, deduped by datasource name
      let dataSources = [];
      try { dataSources = await ws.getDataSourcesAsync(); } catch (e) { /* skip */ }

      for (const ds of dataSources) {
        if (seenDataSources.has(ds.name)) continue;
        seenDataSources.add(ds.name);

        let dsFields = [];
        try { dsFields = await ds.getFieldsAsync(); } catch (e) { continue; }

        for (const f of dsFields) {
          if (f.isHidden) continue;
          const entry = {
            name: f.name,
            role: f.role,
            dataType: f.dataType,
            isCalc: f.isCalculatedField,
            description: f.description || null,
          };
          // Newer Extensions API (≥1.10) exposes calc formula on calculated fields.
          // Wrapped in try because older Tableau versions throw on access.
          if (f.isCalculatedField) {
            try {
              if (typeof f.calculation === "string" && f.calculation) {
                entry.formula = f.calculation;
              }
            } catch (e) { /* not supported on this Tableau version */ }
          }
          sheetEntry.fields.push(entry);
        }
      }

      // Sample values per dimension from summary data
      try {
        const summaryData = await ws.getSummaryDataAsync({ maxRows: 200 });
        const samplesMap = {};
        summaryData.columns.forEach((col, i) => {
          const unique = new Set();
          for (const row of summaryData.data) {
            const v = row[i]?.formattedValue;
            if (v && v !== "Null" && v !== "null" && unique.size < MAX_SAMPLES_PER_FIELD) {
              unique.add(v);
            }
          }
          if (unique.size > 0) samplesMap[col.fieldName] = [...unique];
        });
        for (const field of sheetEntry.fields) {
          if (samplesMap[field.name]) field.samples = samplesMap[field.name];
        }
      } catch (e) {
        console.warn(`getSummaryDataAsync failed for "${ws.name}":`, e);
      }

      // Currently-applied filters on this worksheet
      try {
        const wsFilters = await ws.getFiltersAsync();
        for (const f of wsFilters) {
          if (f.filterType === "categorical" && f.appliedValues?.length) {
            sheetEntry.currentFilters.push({
              field: f.fieldName,
              values: f.appliedValues.slice(0, MAX_FILTER_VALUES).map(v => v.formattedValue),
            });
          } else if (f.filterType === "range" && f.minValue != null && f.maxValue != null) {
            sheetEntry.currentFilters.push({
              field: f.fieldName,
              range: [f.minValue.formattedValue, f.maxValue.formattedValue],
            });
          }
        }
      } catch (e) { /* skip */ }

      // Cap fields per sheet — keep dimensions first since they drive filters
      if (sheetEntry.fields.length > MAX_FIELDS_PER_SHEET) {
        sheetEntry.fields.sort((a, b) => (a.role === "dimension" ? -1 : 1));
        sheetEntry.fields = sheetEntry.fields.slice(0, MAX_FIELDS_PER_SHEET);
        sheetEntry._truncated = true;
      }

      sheets.push(sheetEntry);
    } catch (e) {
      console.warn(`Could not process worksheet "${ws.name}":`, e);
    }
  }

  // Dashboard-level parameters (often drive what the user sees)
  const parameters = [];
  try {
    const params = await dashboard.getParametersAsync();
    for (const p of params) {
      parameters.push({
        name: p.name,
        dataType: p.dataType,
        currentValue: p.currentValue?.formattedValue,
        allowableValues: p.allowableValues?.type,
      });
    }
  } catch (e) { /* skip */ }

  const ctx = { sheets };
  if (parameters.length) ctx.parameters = parameters;

  // Token-budget guard: if the JSON is too big, drop samples (lowest-value bits first)
  let payload = JSON.stringify(ctx);
  if (payload.length > MAX_CONTEXT_BYTES) {
    for (const s of ctx.sheets) {
      for (const f of s.fields) delete f.samples;
    }
    payload = JSON.stringify(ctx);
    console.warn(`Aviva: workbook context exceeded ${MAX_CONTEXT_BYTES} bytes — dropped sample values`);
  }

  workbookContext = sheets.length > 0 ? ctx : null;
  if (workbookContext) {
    console.log(
      `Aviva: workbook context collected — ${sheets.length} sheet(s), ` +
      `${parameters.length} parameter(s), ${payload.length} bytes`
    );
  }
}

// ── Refresh context when the dashboard state changes ─────────────────────────
let refreshTimer = null;
function scheduleContextRefresh() {
  // Debounce: filter drags fire many events; coalesce to one collection
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => { collectWorkbookContext().catch(() => {}); }, 600);
}

function wireDashboardListeners() {
  if (typeof tableau === "undefined" || !tableau.extensions?.dashboardContent) return;
  const dashboard = tableau.extensions.dashboardContent.dashboard;
  const E = tableau.TableauEventType || {};

  // Per-worksheet filter changes
  for (const ws of dashboard.worksheets) {
    try { ws.addEventListener(E.FilterChanged, scheduleContextRefresh); } catch (e) { /* skip */ }
  }
  // Dashboard-level parameter changes
  try { dashboard.addEventListener(E.ParameterChanged, scheduleContextRefresh); } catch (e) { /* skip */ }
}

// ── Tableau init ──────────────────────────────────────────────────────────────
try {
  if (typeof tableau !== "undefined" && tableau.extensions) {
    tableauInitPromise = tableau.extensions.initializeAsync();
    tableauInitPromise
      .then(async () => {
        await collectWorkbookContext();
        wireDashboardListeners();
        await loadConnectionPicker();
        await pushSessionData();   // best-effort upload of worksheet snapshots
        setStatus("Ready. Type a question above.", "");
      })
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
    const selectedConnection = connectionPicker?.value || null;
    const body = {
      question,
      workbook_context: workbookContext,
      connection: selectedConnection,
      // Only send session_id if we don't have a live connection AND data is loaded
      session_id: (!selectedConnection && sessionLoaded) ? SESSION_ID : null,
    };

    const response = await fetch(`${API_URL}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
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

// ── Connection picker ────────────────────────────────────────────────────────
async function loadConnectionPicker() {
  if (!connectionPicker) return;
  try {
    const r = await fetch(`${API_URL}/connections`);
    if (!r.ok) return;
    const data = await r.json();
    // Wipe and rebuild — first option always demo/session mode
    connectionPicker.innerHTML = '<option value="">Dashboard data</option>';
    for (const c of data.connections || []) {
      const opt = document.createElement("option");
      opt.value = c.name;
      opt.textContent = c.label || c.name;
      connectionPicker.appendChild(opt);
    }
  } catch (e) {
    console.warn("Could not load connection list:", e);
  }
}

// ── Push worksheet snapshots into the backend's DuckDB session ───────────────
async function pushSessionData() {
  if (typeof tableau === "undefined" || !tableau.extensions?.dashboardContent) return;
  const dashboard = tableau.extensions.dashboardContent.dashboard;
  const sheets = [];

  for (const ws of dashboard.worksheets) {
    try {
      const sd = await ws.getSummaryDataAsync({ maxRows: 10000 });
      if (!sd.columns?.length || !sd.data?.length) continue;
      sheets.push({
        name: ws.name,
        columns: sd.columns.map(c => c.fieldName),
        rows: sd.data.map(row => row.map(cell => cell.value ?? cell.formattedValue ?? null)),
      });
    } catch (e) {
      console.warn(`getSummaryDataAsync failed for "${ws.name}":`, e);
    }
  }

  if (!sheets.length) return;

  try {
    const r = await fetch(`${API_URL}/load-session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: SESSION_ID, sheets }),
    });
    if (r.ok) {
      sessionLoaded = true;
      const data = await r.json();
      console.log(`Aviva: session loaded with tables:`, data.tables);
    } else {
      console.warn(`load-session returned ${r.status}`);
    }
  } catch (e) {
    console.warn("Could not push session data:", e);
  }
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
