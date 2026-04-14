/**
 * app.js — Aviva Tableau Extension
 *
 * Flow:
 *   1. Tableau initializes the extension
 *   2. User types a question and hits Ask
 *   3. POST /query to the Aviva FastAPI backend
 *   4. Display the answer
 *   5. Apply any returned filters to every worksheet in the dashboard
 *   6. Clear button removes all Aviva-applied filters
 */

const API_URL = "https://REPLACE_WITH_YOUR_RENDER_URL";

// Track which filters Aviva has applied so Clear can remove them cleanly
let appliedFilters = [];

// ── DOM refs ──────────────────────────────────────────────────────────────────
const questionInput = document.getElementById("question");
const askBtn        = document.getElementById("askBtn");
const statusEl      = document.getElementById("status");
const answerCard    = document.getElementById("answerCard");
const answerText    = document.getElementById("answerText");
const filtersSection = document.getElementById("filtersSection");
const filterPills   = document.getElementById("filterPills");
const sqlDetails    = document.getElementById("sqlDetails");
const sqlText       = document.getElementById("sqlText");
const clearBtn      = document.getElementById("clearBtn");

// ── Tableau init ──────────────────────────────────────────────────────────────
tableau.extensions.initializeAsync().then(() => {
  setStatus("Ready. Type a question above.", "");
}).catch(err => {
  setStatus("Tableau connection failed: " + err.message, "error");
});

// ── Event listeners ───────────────────────────────────────────────────────────
askBtn.addEventListener("click", handleAsk);
questionInput.addEventListener("keydown", e => {
  if (e.key === "Enter") handleAsk();
});
clearBtn.addEventListener("click", handleClear);

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
    // 1. Call Aviva API
    const response = await fetch(`${API_URL}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    const data = await response.json();

    // 2. Display answer
    showAnswer(data);

    // 3. Apply filters to Tableau dashboard
    if (data.filters && data.filters.length > 0) {
      await applyFilters(data.filters);
      setStatus(`Answer ready. ${data.filters.length} filter(s) applied to dashboard.`, "success");
    } else {
      setStatus("Answer ready. No filters applied.", "success");
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
  const dashboard = tableau.extensions.dashboardContent.dashboard;
  const worksheets = dashboard.worksheets;

  appliedFilters = filters; // store for Clear

  for (const worksheet of worksheets) {
    for (const filter of filters) {
      try {
        await worksheet.applyFilterAsync(
          filter.field,
          filter.values,
          tableau.FilterUpdateType.Replace
        );
      } catch (e) {
        // Field may not exist in every worksheet — that's fine, skip it
        console.warn(`Could not apply filter "${filter.field}" to "${worksheet.name}":`, e.message);
      }
    }
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
        console.warn(`Could not clear filter "${filter.field}" from "${worksheet.name}":`, e.message);
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
