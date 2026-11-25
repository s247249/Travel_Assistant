"use strict";
/* Travel RAG Assistant — vanilla JS frontend (D27). No build step.
   All data comes from the API. The itinerary card renders the STRUCTURED
   proposal (authoritative); the LLM text is commentary (narrative-drift fix).
   All interpolated text is escaped (esc) — LLM/user content is untrusted. */

const state = {
  user: null, conversations: [], threadId: null,
  messages: [], slots: {}, proposal: null, busy: false, flash: null,
  cardCollapsed: false, shownProposalId: null,
};

const $ = (sel) => document.querySelector(sel);
const route = () => location.hash || "#/login";
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, method = "GET", body = null) {
  const opts = { method, credentials: "same-origin", headers: {} };
  if (body !== null) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* no body */ }
  if (!res.ok) {
    const err = new Error(detailMsg(data) || `HTTP ${res.status}`);
    err.status = res.status; err.data = data;
    throw err;
  }
  return data;
}

function detailMsg(data) {
  if (!data) return null;
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join("; ");
  if (data.detail && data.detail.reasons) return data.detail.reasons.join("; ");
  return null;
}

/* ---------------- routing ---------------- */

async function render() {
  if (!state.user) {
    try { state.user = await api("/api/sessions/current"); } catch { state.user = null; }
  }
  const r = route();
  if (!state.user) {
    if (r !== "#/login") { location.hash = "#/login"; return; }
    renderLogin(); return;
  }
  if (r === "#/login") { location.hash = "#/chat"; return; }
  if (r === "#/bookings") { await renderBookings(); return; }
  await renderChat();
}

function navbar() {
  return `<nav class="navbar navbar-expand navbar-dark bg-dark mb-3"><div class="container-fluid">
    <span class="navbar-brand">Travel RAG Assistant</span>
    <div class="navbar-nav me-auto">
      <a class="nav-link ${route() === "#/chat" ? "active" : ""}" href="#/chat">Chat</a>
      <a class="nav-link ${route() === "#/bookings" ? "active" : ""}" href="#/bookings">Bookings</a>
    </div>
    <span class="navbar-text me-3 small">${esc(state.user.email)}</span>
    <button class="btn btn-outline-light btn-sm" id="logout">Logout</button>
  </div></nav>`;
}

function attachNavbar() {
  $("#logout")?.addEventListener("click", async () => {
    await api("/api/sessions/current", "DELETE");
    state.user = null; state.threadId = null; state.messages = []; state.proposal = null;
    location.hash = "#/login";
  });
}

function flashHtml() {
  if (!state.flash) return "";
  const f = state.flash; state.flash = null;
  return `<div class="alert alert-${esc(f.type)} py-2 my-2">${esc(f.text)}</div>`;
}

/* ---------------- login / register ---------------- */

function renderLogin() {
  $("#app").innerHTML = `<div class="container" style="max-width: 860px">
    <h3 class="my-4 text-center">Travel RAG Assistant</h3>
    <div id="auth-error"></div>
    <div class="row g-4">
      <div class="col-md-6"><div class="card"><div class="card-body">
        <h5 class="card-title">Login</h5>
        <form id="login-form">
          <div class="mb-2"><input type="email" class="form-control" id="login-email" placeholder="email" required></div>
          <div class="mb-2"><input type="password" class="form-control" id="login-password" placeholder="password" required></div>
          <button class="btn btn-primary w-100">Login</button>
        </form>
      </div></div></div>
      <div class="col-md-6"><div class="card"><div class="card-body">
        <h5 class="card-title">Register</h5>
        <form id="register-form">
          <div class="mb-2"><input type="email" class="form-control" id="reg-email" placeholder="email" required></div>
          <div class="mb-2"><input type="password" class="form-control" id="reg-password" placeholder="password (min 8 chars)" minlength="8" required></div>
          <div class="mb-2"><input type="text" class="form-control" id="reg-name" placeholder="name (optional)"></div>
          <div class="mb-2"><select class="form-select" id="reg-airport">
            <option value="TRN">Turin (TRN)</option><option value="MXP">Milan (MXP)</option><option value="FCO">Rome (FCO)</option>
          </select></div>
          <button class="btn btn-success w-100">Register</button>
        </form>
      </div></div></div>
    </div></div>`;

  const showErr = (e) => { $("#auth-error").innerHTML = `<div class="alert alert-danger">${esc(e.message)}</div>`; };
  $("#login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      state.user = await api("/api/sessions", "POST",
        { email: $("#login-email").value, password: $("#login-password").value });
      location.hash = "#/chat";
    } catch (e) { showErr(e); }
  });
  $("#register-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      state.user = await api("/api/users", "POST", {
        email: $("#reg-email").value, password: $("#reg-password").value,
        name: $("#reg-name").value || null, home_airport: $("#reg-airport").value,
      });
      location.hash = "#/chat";
    } catch (e) { showErr(e); }
  });
}

/* ---------------- chat ---------------- */

async function loadThread(tid) {
  const h = await api(`/api/conversations/${tid}/messages`);
  state.threadId = tid;
  state.messages = h.messages || [];
  state.slots = h.slots || {};
  state.proposal = h.proposal || null;
}

async function renderChat() {
  try { state.conversations = await api("/api/conversations"); } catch { state.conversations = []; }
  if (!state.threadId && state.conversations.length) await loadThread(state.conversations[0].id);
  if (state.proposal && state.proposal.proposal_id !== state.shownProposalId) {
    state.cardCollapsed = false;            // auto-expand a newly built proposal
    state.shownProposalId = state.proposal.proposal_id;
  }

  $("#app").innerHTML = navbar() + `<div class="container-fluid"><div class="row g-3">
    <div class="col-md-3">
      <div class="card"><div class="card-body py-2">
        <button class="btn btn-primary btn-sm w-100 mb-2" id="new-chat">+ New conversation</button>
        <div class="list-group list-group-flush small" id="conv-list">${state.conversations.map((c) => `
          <button class="list-group-item list-group-item-action conv-item ${c.id === state.threadId ? "active" : ""}"
                  data-id="${esc(c.id)}">${esc(c.title || "Conversation")}<br>
            <span class="opacity-75">${esc((c.updated_at || "").slice(0, 16))}</span></button>`).join("")}
        </div>
      </div></div>
    </div>
    <div class="col-md-6">
      <div id="messages">${messagesHtml()}</div>
      <div id="proposal-panel">${proposalPanel()}</div>
      ${flashHtml()}
      <form id="chat-form" class="d-flex gap-2 mt-2">
        <input class="form-control" id="chat-input" placeholder="Tell me about your trip…" autocomplete="off" ${state.busy ? "disabled" : ""}>
        <button class="btn btn-primary" ${state.busy ? "disabled" : ""}>Send</button>
      </form>
    </div>
    <div class="col-md-3">${slotsPanel()}</div>
  </div></div>`;

  attachNavbar();
  $("#new-chat").addEventListener("click", async () => {
    const c = await api("/api/conversations", "POST");
    state.threadId = c.id; state.messages = []; state.slots = {}; state.proposal = null;
    await renderChat();
  });
  document.querySelectorAll(".conv-item").forEach((el) => el.addEventListener("click", async () => {
    await loadThread(el.dataset.id);
    await renderChat();
  }));
  $("#chat-form").addEventListener("submit", async (ev) => { ev.preventDefault(); await sendMessage(); });
  $("#confirm-book")?.addEventListener("click", confirmBooking);
  $("#toggle-card")?.addEventListener("click", async () => { state.cardCollapsed = !state.cardCollapsed; await renderChat(); });
  const box = $("#messages"); box.scrollTop = box.scrollHeight;
  $("#chat-input")?.focus();
}

function messagesHtml() {
  const bubbles = state.messages
    .filter((m) => m.role === "human" || m.role === "ai")
    .map((m) => `<div class="d-flex ${m.role === "human" ? "justify-content-end" : "justify-content-start"} mb-2">
      <div class="msg ${m.role === "human" ? "msg-human" : "msg-ai"}">${esc(m.content)}</div></div>`).join("");
  const loading = state.busy
    ? `<div class="text-muted small loading-dots">Assistant is planning</div>` : "";
  return bubbles + loading;
}

function proposalPanel() {
  const p = state.proposal;
  if (!p) return "";
  const badge = p.status === "proposed" ? '<span class="badge bg-primary">proposed</span>'
    : p.status === "booked" ? `<span class="badge bg-success">booked #${esc(p.booking_id)}</span>`
    : `<span class="badge bg-secondary">${esc(p.status)}</span>`;
  const btn = p.status === "proposed"
    ? '<button class="btn btn-success btn-sm" id="confirm-book">Confirm booking</button>' : "";
  const toggle = `<button class="btn btn-outline-secondary btn-sm" id="toggle-card">${state.cardCollapsed ? "Show details" : "Hide details"}</button>`;
  let body = "";
  if (!state.cardCollapsed) {
    const flights = (p.flights || []).map((f) =>
      `<tr><td>${esc(f.date)}</td><td>${esc(f.from)} &rarr; ${esc(f.to)}</td><td>${esc(f.depart_time)}</td></tr>`).join("");
    const days = (p.days || []).map((d) =>
      `<tr><td>${esc(d.date)}</td><td>${esc(d.name)}</td><td><span class="badge bg-light text-dark">${esc(d.category)}</span></td></tr>`).join("");
    body = `<div class="card-body small">
      <p class="mb-2">${esc(p.start)} &rarr; ${esc(p.end)} &middot; ${esc(p.travelers)} traveler(s)</p>
      <h6 class="mb-1">Flights</h6><table class="table table-sm mb-2">${flights}</table>
      <h6 class="mb-1">Hotel</h6>
      <p class="mb-2">${esc(p.hotel?.name)} (${esc(p.hotel?.tier)}, ${esc(p.hotel?.rooms_needed)} room(s))</p>
      <h6 class="mb-1">Day by day</h6><table class="table table-sm mb-2">${days}</table>
      <p class="mb-0"><strong>Total &euro;${esc(p.total_price)}</strong> / budget &euro;${esc(p.budget)} &middot; margin &euro;${esc(p.margin)}</p>
    </div>`;
  }
  return `<div class="card border-primary my-2"><div class="card-header d-flex justify-content-between align-items-center flex-wrap gap-2 py-2">
      <strong class="small">Itinerary &mdash; ${esc(p.city)} &middot; ${esc(p.start)} &rarr; ${esc(p.end)} &middot; &euro;${esc(p.total_price)}</strong>
      <div class="d-flex align-items-center gap-2">${badge}${btn}${toggle}</div>
    </div>${body}</div>`;
}

function slotsPanel() {
  const required = ["budget", "nation", "preferences", "month", "nights", "travelers", "city"];
  const keys = ["budget", "nation", "city", "preferences", "month", "nights", "travelers", "origin", "targets"];
  const rows = keys.map((k) => {
    const v = state.slots[k];
    const has = v !== undefined && v !== null && !(Array.isArray(v) && v.length === 0);
    const val = has ? (Array.isArray(v) ? v.join(", ") : v) : (required.includes(k) ? "missing" : "—");
    return `<tr><td class="text-muted">${esc(k)}</td>
      <td class="${!has && required.includes(k) ? "slot-missing" : ""}">${esc(val)}</td></tr>`;
  }).join("");
  return `<div class="card"><div class="card-body py-2">
    <h6 class="card-title mb-2">Requirements</h6>
    <table class="table table-sm small mb-0">${rows}</table>
  </div></div>`;
}

async function sendMessage() {
  const text = $("#chat-input").value.trim();
  if (!text || state.busy) return;
  if (!state.threadId) {
    const c = await api("/api/conversations", "POST");
    state.threadId = c.id; state.messages = []; state.slots = {}; state.proposal = null;
  }
  state.messages.push({ role: "human", content: text });
  state.busy = true;
  await renderChat();
  try {
    const r = await api(`/api/conversations/${state.threadId}/chat`, "POST", { message: text });
    state.messages.push({ role: "ai", content: r.reply });
    state.slots = r.slots || {};
    state.proposal = r.proposal || null;
  } catch (e) {
    state.flash = { type: "danger", text: `Assistant error: ${e.message}` };
  }
  state.busy = false;
  await renderChat();
}

async function confirmBooking() {
  if (state.busy) return;
  state.busy = true;
  await renderChat();
  try {
    const r = await api(`/api/conversations/${state.threadId}/book`, "POST");
    state.proposal = { ...state.proposal, status: "booked", booking_id: r.booking_id };
    state.flash = { type: "success", text: `Booking confirmed (#${r.booking_id}) — total €${r.total_price}. See the Bookings page.` };
  } catch (e) {
    state.flash = { type: "danger", text: `Booking refused: ${e.message}` };
  }
  state.busy = false;
  await renderChat();
}

/* ---------------- bookings dashboard ---------------- */

async function renderBookings() {
  let bookings = [];
  try { bookings = await api("/api/bookings"); } catch (e) {
    state.flash = { type: "danger", text: e.message };
  }
  const cards = bookings.map((b) => `
    <div class="card mb-3"><div class="card-body py-3">
      <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
        <div>
          <strong>#${esc(b.id)} &mdash; ${esc(b.city_name)}</strong>
          <span class="badge ${b.status === "confirmed" ? "bg-success" : "bg-secondary"} ms-2">${esc(b.status)}</span>
          <div class="small text-muted">${esc(b.start_date)} &rarr; ${esc(b.end_date)} &middot;
            ${esc(b.n_travelers)} traveler(s) &middot; from ${esc(b.origin_airport)} &middot;
            <strong>&euro;${esc(b.total_price)}</strong></div>
        </div>
        <div class="d-flex gap-2">
          <button class="btn btn-outline-secondary btn-sm details-btn" data-id="${esc(b.id)}">Details</button>
          ${b.status === "confirmed" ? `<button class="btn btn-outline-danger btn-sm cancel-btn" data-id="${esc(b.id)}">Cancel</button>` : ""}
        </div>
      </div>
      <div class="details mt-2 small" id="details-${esc(b.id)}"></div>
    </div></div>`).join("");

  $("#app").innerHTML = navbar() + `<div class="container" style="max-width: 900px">
    <h4 class="mb-3">My bookings</h4>${flashHtml()}
    ${cards || '<p class="text-muted">No bookings yet — plan a trip in the chat!</p>'}
  </div>`;
  attachNavbar();
  document.querySelectorAll(".details-btn").forEach((el) => el.addEventListener("click", async () => {
    const box = $(`#details-${el.dataset.id}`);
    if (box.innerHTML) { box.innerHTML = ""; return; }
    const b = await api(`/api/bookings/${el.dataset.id}`);
    box.innerHTML = `<table class="table table-sm">
      <thead><tr><th>type</th><th>ref</th><th>date</th><th>qty</th><th>unit &euro;</th><th>subtotal &euro;</th></tr></thead>
      <tbody>${b.items.map((i) => `<tr><td>${esc(i.item_type)}</td><td>${esc(i.ref_id)}</td><td>${esc(i.date)}</td>
        <td>${esc(i.quantity)}</td><td>${esc(i.unit_price)}</td><td>${esc(i.subtotal)}</td></tr>`).join("")}</tbody></table>`;
  }));
  document.querySelectorAll(".cancel-btn").forEach((el) => el.addEventListener("click", async () => {
    if (!confirm(`Cancel booking #${el.dataset.id}? Inventory will be released.`)) return;
    try {
      await api(`/api/bookings/${el.dataset.id}/cancel`, "POST");
      state.flash = { type: "success", text: `Booking #${el.dataset.id} cancelled.` };
    } catch (e) { state.flash = { type: "danger", text: e.message }; }
    await renderBookings();
  }));
}

/* ---------------- boot ---------------- */
window.addEventListener("hashchange", render);
render();
