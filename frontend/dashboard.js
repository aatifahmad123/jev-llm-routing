const summaryEl = document.getElementById("summary");
const modelsEl = document.getElementById("models");
const timingsEl = document.getElementById("timings");
const recentEl = document.getElementById("recent-calls");
const errorEl = document.getElementById("dashboard-error");
const updatedEl = document.getElementById("updated");

const value = (number) => Number(number || 0).toLocaleString(undefined, {
  maximumFractionDigits: 2,
});

function card(label, content, className = "") {
  return `<div class="metric-card ${className}"><span>${label}</span><strong>${content}</strong></div>`;
}

function render(data) {
  const calls = data.calls;
  summaryEl.innerHTML = [
    card("Total LLM calls", value(calls.total), "primary"),
    card("Success rate", `${value(calls.success_percentage)}%`, "success"),
    card("Failure rate", `${value(calls.failure_percentage)}%`, "failure"),
    card("Chat requests", value(data.requests.total), "requests"),
  ].join("");

  modelsEl.innerHTML = Object.entries(calls.by_route).map(([route, stats]) =>
    `<div class="model-card model-${route}"><div class="model-heading"><div>` +
    `<span class="model-label">${route} route</span><strong>${data.models[route]}</strong></div>` +
    `<span class="model-count">${value(stats.total)} <small>calls</small></span></div>` +
    `<div class="model-bar"><span style="width: ${calls.total ? (stats.total / calls.total) * 100 : 0}%"></span></div>` +
    `<div class="model-meta"><span>${value(stats.successful)} successful</span><span>${value(stats.failed)} failed</span></div></div>`
  ).join("");

  timingsEl.innerHTML = [
    card("Average", `${value(data.timing_ms.average_ms)} <small>ms</small>`),
    card("Minimum", `${value(data.timing_ms.minimum_ms)} <small>ms</small>`),
    card("Maximum", `${value(data.timing_ms.maximum_ms)} <small>ms</small>`),
    card("P95", `${value(data.timing_ms.p95_ms)} <small>ms</small>`),
  ].join("");

  recentEl.innerHTML = data.recent_calls.length
    ? data.recent_calls.map((call) => `<tr><td>${new Date(call.timestamp).toLocaleTimeString()}</td>` +
      `<td><span class="tag tag-${call.route}">${call.route}</span></td><td>${call.model}</td>` +
      `<td class="${call.status === "success" ? "status-success" : "status-failure"}">${call.status}</td>` +
      `<td>${value(call.duration_ms)} ms</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">No calls recorded yet.</td></tr>`;
  updatedEl.textContent = `Updated ${new Date(data.generated_at).toLocaleTimeString()}`;
}

async function loadDashboard() {
  try {
    const response = await fetch("/dashboard/metrics");
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Unable to load metrics");
    errorEl.hidden = true;
    render(data);
  } catch (error) {
    errorEl.textContent = error.message;
    errorEl.hidden = false;
  }
}

loadDashboard();
setInterval(loadDashboard, 10000);
