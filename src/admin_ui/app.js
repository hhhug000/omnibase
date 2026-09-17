/* Omnibase Admin — vanilla JS single-page app (no build step). */

(() => {
  "use strict";

  const APP = document.getElementById("app");
  const TOASTS = document.getElementById("toast-stack");

  /* ---------------- helpers ---------------- */

  function esc(v) {
    if (v === null || v === undefined) return "";
    return String(v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function toast(message, type = "info") {
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = message;
    TOASTS.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  function fmtCell(v) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "boolean") return v ? "true" : "false";
    return String(v);
  }

  /* ---------------- session ---------------- */

  const Session = {
    get token() { return localStorage.getItem("ob_token"); },
    set token(v) { v ? localStorage.setItem("ob_token", v) : localStorage.removeItem("ob_token"); },
    get user() {
      try { return JSON.parse(localStorage.getItem("ob_user") || "null"); } catch { return null; }
    },
    set user(v) { v ? localStorage.setItem("ob_user", JSON.stringify(v)) : localStorage.removeItem("ob_user"); },
    clear() { this.token = null; this.user = null; },
  };

  /* ---------------- api ---------------- */

  async function api(path, { method = "GET", body, auth = true, raw = false } = {}) {
    const headers = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (auth && Session.token) headers["Authorization"] = `Bearer ${Session.token}`;

    let res;
    try {
      res = await fetch(path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      throw new Error("Network error — is the server running?");
    }

    if (res.status === 401 && auth) {
      Session.clear();
      location.hash = "#/login";
      throw new Error("Session expired. Please sign in again.");
    }

    let data = null;
    const text = await res.text();
    if (text) {
      try { data = JSON.parse(text); } catch { data = null; }
    }

    if (!res.ok) {
      const msg = (data && (data.detail || data.message)) || `Request failed (${res.status})`;
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return raw ? data : data;
  }

  /* ---------------- tiny router ---------------- */

  const state = {
    tables: [],
    tablesLoaded: false,
    canManage: true, // becomes false if /api/tables 403s (non-admin)
  };

  function currentRoute() {
    const hash = location.hash.replace(/^#/, "") || "/";
    const parts = hash.split("/").filter(Boolean);
    return parts;
  }

  window.addEventListener("hashchange", render);
  window.addEventListener("DOMContentLoaded", render);

  async function render() {
    if (!Session.token) {
      renderLogin();
      return;
    }
    await renderShell();
  }

  /* ================= LOGIN ================= */

  function renderLogin(opts = {}) {
    const { showTotp = false, error = "" } = opts;
    APP.innerHTML = `
      <div class="login-screen">
        <div class="login-card">
          <div class="login-brand">
            <div class="brand-mark">OB</div>
            <div>
              <div class="brand-name">Omnibase</div>
              <span class="brand-tag">Admin Console</span>
            </div>
          </div>
          ${error ? `<div class="error-banner">${esc(error)}</div>` : ""}
          <form id="login-form">
            <div class="field">
              <label>Username or email</label>
              <input class="input" name="login" autocomplete="username" required />
            </div>
            <div class="field">
              <label>Password</label>
              <input class="input" type="password" name="password" autocomplete="current-password" required />
            </div>
            <div class="field" id="totp-field" style="${showTotp ? "" : "display:none"}">
              <label>2FA code</label>
              <input class="input" name="totp" inputmode="numeric" autocomplete="one-time-code" placeholder="6-digit code" />
            </div>
            <button class="btn btn-accent btn-block" type="submit" id="login-submit">Sign in</button>
          </form>
        </div>
      </div>
    `;

    const form = document.getElementById("login-form");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const login = fd.get("login").trim();
      const password = fd.get("password");
      const totp = fd.get("totp").trim();
      const btn = document.getElementById("login-submit");
      btn.disabled = true;
      btn.textContent = "Signing in…";
      try {
        const payload = { login, password };
        if (totp) payload.totp = totp;
        const res = await api("/api/auth/login", { method: "POST", body: payload, auth: false });
        const exchanged = await api("/api/auth/exchange", { method: "POST", body: { code: res.code }, auth: false });
        Session.token = exchanged.token;
        Session.user = exchanged.user;
        toast(`Welcome back, ${exchanged.user.username}.`, "success");
        location.hash = "#/";
        render();
      } catch (err) {
        const needsTotp = /totp/i.test(err.message) && !totp;
        renderLogin({ showTotp: needsTotp || showTotp, error: err.message });
      }
    });
  }

  /* ================= SHELL ================= */

  async function renderShell() {
    if (!state.tablesLoaded) {
      try {
        const res = await api("/api/tables");
        state.tables = res.tables || [];
        state.canManage = true;
      } catch (err) {
        if (/admin/i.test(err.message)) {
          state.canManage = false;
          state.tables = [];
        } else {
          toast(err.message, "error");
        }
      }
      state.tablesLoaded = true;
    }

    const route = currentRoute();
    const activeTable = route[0] === "t" ? decodeURIComponent(route[1] || "") : null;

    APP.innerHTML = `
      <div class="shell">
        <aside class="sidebar">
          <div class="brand">
            <div class="brand-mark">OB</div>
            <div>
              <div class="brand-name">Omnibase</div>
              <span class="brand-tag">Admin</span>
            </div>
          </div>
          <div class="nav-section">
            <span class="nav-section-title">Collections</span>
            <button class="icon-btn" id="new-table-btn" title="New table">+</button>
          </div>
          <ul class="nav-list" id="nav-list"></ul>
          <div class="sidebar-footer">
            <button class="account-chip" id="account-btn">
              <div class="avatar">${esc((Session.user?.username || "?")[0]?.toUpperCase() || "?")}</div>
              <div style="overflow:hidden">
                <div class="account-chip-name">${esc(Session.user?.username || "Account")}</div>
                <div class="account-chip-sub">${esc(Session.user?.email || "")}</div>
              </div>
            </button>
          </div>
        </aside>
        <main class="main" id="main-outlet"></main>
      </div>
    `;

    const navList = document.getElementById("nav-list");
    if (!state.tables.length) {
      navList.innerHTML = `<li class="nav-empty">${state.canManage ? "No tables yet." : "No admin access."}</li>`;
    } else {
      navList.innerHTML = state.tables.map((t) => `
        <li class="nav-item ${t === activeTable ? "active" : ""}" data-table="${esc(t)}">
          <span class="dot"></span>${esc(t)}
        </li>
      `).join("");
      navList.querySelectorAll(".nav-item").forEach((el) => {
        el.addEventListener("click", () => {
          location.hash = `#/t/${encodeURIComponent(el.dataset.table)}/records`;
        });
      });
    }

    document.getElementById("new-table-btn").addEventListener("click", openCreateTableModal);
    document.getElementById("account-btn").addEventListener("click", () => { location.hash = "#/account"; });

    await renderOutlet(route);
  }

  async function renderOutlet(route) {
    const outlet = document.getElementById("main-outlet");

    if (route[0] === "account") {
      await renderAccount(outlet);
      return;
    }

    if (route[0] === "t" && route[1]) {
      const tableName = decodeURIComponent(route[1]);
      const tab = route[2] || "records";
      await renderTable(outlet, tableName, tab);
      return;
    }

    outlet.innerHTML = `
      <div class="empty-state" style="margin:auto">
        <strong>${state.tables.length ? "Pick a collection" : "No collections yet"}</strong>
        ${state.tables.length
          ? "Choose a table from the sidebar to browse its records."
          : "Create your first table to start storing data."}
        <div style="margin-top:14px">
          <button class="btn btn-accent" id="empty-new-table">+ New table</button>
        </div>
      </div>
    `;
    const btn = document.getElementById("empty-new-table");
    if (btn) btn.addEventListener("click", openCreateTableModal);
  }

  /* ================= TABLE VIEW ================= */

  async function renderTable(outlet, tableName, tab) {
    outlet.innerHTML = `<div class="center-loading"><span class="spinner"></span>Loading ${esc(tableName)}…</div>`;

    let schema, access, count;
    try {
      schema = (await api(`/api/tables/${encodeURIComponent(tableName)}/schema`)).columns;
    } catch (err) {
      outlet.innerHTML = `<div class="content"><div class="error-banner">${esc(err.message)}</div></div>`;
      return;
    }
    try {
      access = (await api(`/api/tables/${encodeURIComponent(tableName)}/access`)).access;
    } catch { access = null; }

    outlet.innerHTML = `
      <div class="topbar">
        <h1>${esc(tableName)} <span class="badge" id="row-count-badge">…</span></h1>
        <div style="display:flex;gap:8px">
          ${tab === "records" ? `<button class="btn btn-accent" id="new-record-btn">+ New record</button>` : ""}
          ${tab === "schema" ? `<button class="btn btn-accent" id="add-column-btn">+ Add column</button>` : ""}
          <button class="btn btn-danger" id="delete-table-btn">Delete table</button>
        </div>
      </div>
      <div class="tabs">
        <div class="tab ${tab === "records" ? "active" : ""}" data-tab="records">Records</div>
        <div class="tab ${tab === "schema" ? "active" : ""}" data-tab="schema">Schema</div>
        <div class="tab ${tab === "access" ? "active" : ""}" data-tab="access">Access rules</div>
      </div>
      <div class="content" id="tab-content"></div>
    `;

    outlet.querySelectorAll(".tab").forEach((el) => {
      el.addEventListener("click", () => {
        location.hash = `#/t/${encodeURIComponent(tableName)}/${el.dataset.tab}`;
      });
    });
    document.getElementById("delete-table-btn").addEventListener("click", () => confirmDeleteTable(tableName));

    const tabContent = document.getElementById("tab-content");

    if (tab === "schema") {
      renderSchemaTab(tabContent, tableName, schema);
    } else if (tab === "access") {
      renderAccessTab(tabContent, tableName, access);
    } else {
      await renderRecordsTab(tabContent, tableName, schema);
    }

    // row count, best-effort
    api(`/api/db/count/${encodeURIComponent(tableName)}`).then((res) => {
      const badge = document.getElementById("row-count-badge");
      if (badge) badge.textContent = `${res.count} row${res.count === 1 ? "" : "s"}`;
    }).catch(() => {
      const badge = document.getElementById("row-count-badge");
      if (badge) badge.remove();
    });
  }

  function pkColumn(schema) {
    return schema.find((c) => c.primary_key)?.name || "id";
  }

  function inputTypeFor(col) {
    const t = (col.type || "").toUpperCase();
    if (t.includes("INT")) return "number";
    if (t.includes("REAL") || t.includes("FLOA") || t.includes("DOUB")) return "number";
    return "text";
  }

  async function renderRecordsTab(container, tableName, schema) {
    container.innerHTML = `
      <div class="card" style="margin-bottom:14px">
        <div class="input-row">
          <input class="input" id="filter-input" placeholder="filter e.g. status=active&amp;age=&gt;18" />
          <button class="btn" id="filter-apply">Apply</button>
          <button class="btn" id="filter-refresh">Refresh</button>
        </div>
        <div class="hint">Query params are passed straight through — supports =, &gt;, &lt;, &gt;=, &lt;= per column.</div>
      </div>
      <div class="table-wrap" id="records-wrap"><div class="center-loading" style="padding:40px"><span class="spinner"></span>Loading records…</div></div>
    `;

    const filterInput = document.getElementById("filter-input");
    const load = async () => {
      const wrap = document.getElementById("records-wrap");
      const qs = filterInput.value.trim();
      let url = `/api/db/read/${encodeURIComponent(tableName)}`;
      if (qs) {
        const params = new URLSearchParams();
        qs.split("&").forEach((pair) => {
          if (!pair) return;
          const idx = pair.indexOf("=");
          if (idx === -1) return;
          params.append(pair.slice(0, idx), pair.slice(idx + 1));
        });
        const str = params.toString();
        if (str) url += `?${str}`;
      }
      try {
        const rows = await api(url);
        renderRecordsGrid(wrap, tableName, schema, rows);
      } catch (err) {
        wrap.innerHTML = `<div class="error-banner" style="margin:16px">${esc(err.message)}</div>`;
      }
    };

    document.getElementById("filter-apply").addEventListener("click", load);
    document.getElementById("filter-refresh").addEventListener("click", load);
    filterInput.addEventListener("keydown", (e) => { if (e.key === "Enter") load(); });

    document.getElementById("new-record-btn")?.addEventListener("click", () => openRecordModal(tableName, schema, null, load));

    await load();
  }

  function renderRecordsGrid(wrap, tableName, schema, rows) {
    if (!rows.length) {
      wrap.innerHTML = `<div class="empty-state"><strong>No records</strong>This table is empty (or the filter matched nothing).</div>`;
      return;
    }
    const cols = Object.keys(rows[0]);
    const pk = pkColumn(schema);

    wrap.innerHTML = `
      <table class="grid">
        <thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}<th></th></tr></thead>
        <tbody>
          ${rows.map((row) => `
            <tr data-id="${esc(row[pk])}">
              ${cols.map((c) => `<td class="${c === pk ? "pk-cell" : ""}">${esc(fmtCell(row[c]))}</td>`).join("")}
              <td>
                <div class="row-actions">
                  <button class="btn btn-sm" data-act="edit">Edit</button>
                  <button class="btn btn-sm btn-danger" data-act="del">Delete</button>
                </div>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;

    wrap.querySelectorAll("tr[data-id]").forEach((tr) => {
      const id = tr.dataset.id;
      const row = rows.find((r) => String(r[pk]) === id);
      tr.querySelector('[data-act="edit"]').addEventListener("click", () => {
        openRecordModal(tableName, schema, row, () => renderTable(document.getElementById("main-outlet"), tableName, "records"));
      });
      tr.querySelector('[data-act="del"]').addEventListener("click", () => {
        confirmModal(`Delete this record from "${tableName}"? This cannot be undone.`, async () => {
          try {
            await api(`/api/db/delete/${encodeURIComponent(tableName)}?${pk}=${encodeURIComponent(id)}`, { method: "DELETE" });
            toast("Record deleted.", "success");
            renderTable(document.getElementById("main-outlet"), tableName, "records");
          } catch (err) {
            toast(err.message, "error");
          }
        });
      });
    });
  }

  function renderSchemaTab(container, tableName, schema) {
    container.innerHTML = `
      <div class="table-wrap">
        <table class="grid">
          <thead><tr><th>Column</th><th>Type</th><th>Nullable</th><th>Primary key</th></tr></thead>
          <tbody>
            ${schema.map((c) => `
              <tr>
                <td>${esc(c.name)}</td>
                <td>${esc(c.type)}</td>
                <td>${c.nullable ? "yes" : "no"}</td>
                <td>${c.primary_key ? "yes" : ""}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
    document.getElementById("add-column-btn")?.addEventListener("click", () => openAddColumnModal(tableName, () => {
      renderTable(document.getElementById("main-outlet"), tableName, "schema");
    }));
  }

  const ACCESS_LEVELS = ["none", "owner", "everyone"];
  const ACCESS_OPS = ["create", "read", "update", "delete"];

  function renderAccessTab(container, tableName, access) {
    if (!access) {
      container.innerHTML = `<div class="error-banner">Could not load access rules (admin only).</div>`;
      return;
    }
    container.innerHTML = `
      <div class="card">
        <div class="card-title">Access rules</div>
        <p class="hint" style="margin-top:-4px;margin-bottom:14px">
          <strong>none</strong> — nobody · <strong>owner</strong> — the signed-in creator of the row · <strong>everyone</strong> — any authenticated user
        </p>
        <div class="access-grid">
          ${ACCESS_OPS.map((op) => `
            <div class="field" style="margin-bottom:0">
              <label>${op}</label>
              <select class="input" id="access-${op}">
                ${ACCESS_LEVELS.map((lvl) => `<option value="${lvl}" ${access[op] === lvl ? "selected" : ""}>${lvl}</option>`).join("")}
              </select>
            </div>
          `).join("")}
        </div>
        <div style="margin-top:18px">
          <button class="btn btn-accent" id="save-access-btn">Save access rules</button>
        </div>
      </div>
    `;
    document.getElementById("save-access-btn").addEventListener("click", async () => {
      const payload = {};
      ACCESS_OPS.forEach((op) => { payload[op] = document.getElementById(`access-${op}`).value; });
      try {
        await api(`/api/tables/${encodeURIComponent(tableName)}/access`, { method: "PUT", body: { access: payload } });
        toast("Access rules saved.", "success");
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  function confirmDeleteTable(tableName) {
    confirmModal(`Delete table "${tableName}" and all of its data? This cannot be undone.`, async () => {
      try {
        await api(`/api/tables/${encodeURIComponent(tableName)}`, { method: "DELETE" });
        state.tablesLoaded = false;
        toast(`Table "${tableName}" deleted.`, "success");
        location.hash = "#/";
        render();
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  /* ================= ACCOUNT ================= */

  async function renderAccount(outlet) {
    outlet.innerHTML = `<div class="center-loading"><span class="spinner"></span>Loading account…</div>`;
    let me;
    try {
      me = (await api("/api/auth/me")).user;
    } catch (err) {
      outlet.innerHTML = `<div class="content"><div class="error-banner">${esc(err.message)}</div></div>`;
      return;
    }

    outlet.innerHTML = `
      <div class="topbar"><h1>Account</h1></div>
      <div class="content" style="max-width:520px">
        <div class="card">
          <div class="card-title">Profile</div>
          <div class="field"><label>Username</label><div class="code-box">${esc(me.username)}</div></div>
          <div class="field"><label>Email</label><div class="code-box">${esc(me.email)}</div></div>
          <div class="field" style="margin-bottom:0"><label>Member since</label><div class="code-box">${esc(me.created_at)}</div></div>
        </div>

        <div class="card" id="totp-card">
          <div class="card-title">
            Two-factor authentication
            <span class="badge">${me.totp_enabled ? "enabled" : "disabled"}</span>
          </div>
          <div id="totp-body"></div>
        </div>

        <button class="btn btn-danger" id="logout-btn">Log out</button>
      </div>
    `;

    renderTotpBody(document.getElementById("totp-body"), me);

    document.getElementById("logout-btn").addEventListener("click", async () => {
      try { await api("/api/auth/logout", { method: "POST" }); } catch { /* ignore */ }
      Session.clear();
      state.tablesLoaded = false;
      state.tables = [];
      location.hash = "#/login";
      render();
    });
  }

  function renderTotpBody(container, me) {
    if (!me.totp_enabled) {
      container.innerHTML = `
        <p class="hint" style="margin-top:0">Add an authenticator app for an extra login step.</p>
        <button class="btn btn-accent" id="totp-setup-btn">Enable 2FA</button>
      `;
      document.getElementById("totp-setup-btn").addEventListener("click", async () => {
        try {
          const res = await api("/api/auth/totp/setup", { method: "POST" });
          container.innerHTML = `
            <p class="hint" style="margin-top:0">Scan or enter this secret in your authenticator app, then confirm with a generated code.</p>
            <div class="field"><label>Secret</label><div class="code-box">${esc(res.secret)}</div></div>
            <div class="field"><label>Setup URI</label><div class="code-box">${esc(res.uri)}</div></div>
            <div class="field">
              <label>Confirmation code</label>
              <input class="input" id="totp-confirm-code" inputmode="numeric" placeholder="6-digit code" />
            </div>
            <button class="btn btn-accent" id="totp-confirm-btn">Confirm & enable</button>
          `;
          document.getElementById("totp-confirm-btn").addEventListener("click", async () => {
            const code = document.getElementById("totp-confirm-code").value.trim();
            try {
              await api("/api/auth/totp/confirm", { method: "POST", body: { code } });
              toast("Two-factor authentication enabled.", "success");
              me.totp_enabled = true;
              renderTotpBody(container, me);
              const badge = document.querySelector("#totp-card .badge");
              if (badge) badge.textContent = "enabled";
            } catch (err) { toast(err.message, "error"); }
          });
        } catch (err) { toast(err.message, "error"); }
      });
    } else {
      container.innerHTML = `
        <p class="hint" style="margin-top:0">Enter a current code to disable 2FA.</p>
        <div class="field">
          <label>Code</label>
          <input class="input" id="totp-disable-code" inputmode="numeric" placeholder="6-digit code" />
        </div>
        <button class="btn btn-danger" id="totp-disable-btn">Disable 2FA</button>
      `;
      document.getElementById("totp-disable-btn").addEventListener("click", async () => {
        const code = document.getElementById("totp-disable-code").value.trim();
        try {
          await api("/api/auth/totp", { method: "DELETE", body: { code } });
          toast("Two-factor authentication disabled.", "success");
          me.totp_enabled = false;
          renderTotpBody(container, me);
          const badge = document.querySelector("#totp-card .badge");
          if (badge) badge.textContent = "disabled";
        } catch (err) { toast(err.message, "error"); }
      });
    }
  }

  /* ================= MODALS ================= */

  function openModal(html) {
    const backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    backdrop.innerHTML = `<div class="modal">${html}</div>`;
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) backdrop.remove(); });
    document.body.appendChild(backdrop);
    return backdrop;
  }

  function confirmModal(message, onConfirm) {
    const backdrop = openModal(`
      <div class="modal-head"><h2>Please confirm</h2></div>
      <p>${esc(message)}</p>
      <div class="modal-actions">
        <button class="btn" id="confirm-cancel">Cancel</button>
        <button class="btn btn-danger" id="confirm-ok">Confirm</button>
      </div>
    `);
    backdrop.querySelector("#confirm-cancel").addEventListener("click", () => backdrop.remove());
    backdrop.querySelector("#confirm-ok").addEventListener("click", () => { backdrop.remove(); onConfirm(); });
  }

  function openCreateTableModal() {
    let colCount = 0;
    const backdrop = openModal(`
      <div class="modal-head"><h2>New table</h2></div>
      <div class="field">
        <label>Table name</label>
        <input class="input" id="ct-name" placeholder="e.g. posts" />
      </div>
      <label style="font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.04em">Columns</label>
      <div id="ct-columns" style="margin-top:8px"></div>
      <button class="btn btn-sm" id="ct-add-col" style="margin-top:4px">+ Add column</button>
      <hr class="divider" />
      <label style="font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.04em">Default access</label>
      <div class="access-grid" style="margin-top:8px">
        ${ACCESS_OPS.map((op) => `
          <div class="field" style="margin-bottom:0">
            <label>${op}</label>
            <select class="input" id="ct-access-${op}">
              ${ACCESS_LEVELS.map((lvl) => `<option value="${lvl}" ${lvl === "owner" ? "selected" : ""}>${lvl}</option>`).join("")}
            </select>
          </div>
        `).join("")}
      </div>
      <div class="modal-actions">
        <button class="btn" id="ct-cancel">Cancel</button>
        <button class="btn btn-accent" id="ct-create">Create table</button>
      </div>
    `);

    const colsEl = backdrop.querySelector("#ct-columns");
    function addColRow() {
      colCount += 1;
      const row = document.createElement("div");
      row.className = "col-row";
      row.innerHTML = `
        <input class="input" placeholder="column name" data-col-name />
        <select class="input" data-col-type>
          <option value="text">text</option>
          <option value="integer">integer</option>
          <option value="real">real</option>
          <option value="boolean">boolean</option>
        </select>
        <label class="checkbox-row"><input type="checkbox" checked data-col-nullable /> null?</label>
        <button class="icon-btn" data-remove-col title="Remove">×</button>
      `;
      row.querySelector("[data-remove-col]").addEventListener("click", () => row.remove());
      colsEl.appendChild(row);
    }
    addColRow();
    backdrop.querySelector("#ct-add-col").addEventListener("click", addColRow);
    backdrop.querySelector("#ct-cancel").addEventListener("click", () => backdrop.remove());

    backdrop.querySelector("#ct-create").addEventListener("click", async () => {
      const table_name = backdrop.querySelector("#ct-name").value.trim();
      if (!table_name) { toast("Table name is required.", "error"); return; }
      const columns = [...colsEl.querySelectorAll(".col-row")].map((row) => ({
        name: row.querySelector("[data-col-name]").value.trim(),
        type: row.querySelector("[data-col-type]").value,
        nullable: row.querySelector("[data-col-nullable]").checked,
      })).filter((c) => c.name);
      const access = {};
      ACCESS_OPS.forEach((op) => { access[op] = backdrop.querySelector(`#ct-access-${op}`).value; });

      try {
        await api("/api/tables/create", { method: "POST", body: { table_name, columns, access } });
        toast(`Table "${table_name}" created.`, "success");
        backdrop.remove();
        state.tablesLoaded = false;
        location.hash = `#/t/${encodeURIComponent(table_name)}/records`;
        render();
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  function openAddColumnModal(tableName, onDone) {
    const backdrop = openModal(`
      <div class="modal-head"><h2>Add column to ${esc(tableName)}</h2></div>
      <div class="field"><label>Name</label><input class="input" id="ac-name" /></div>
      <div class="field">
        <label>Type</label>
        <select class="input" id="ac-type">
          <option value="text">text</option>
          <option value="integer">integer</option>
          <option value="real">real</option>
          <option value="boolean">boolean</option>
        </select>
      </div>
      <label class="checkbox-row"><input type="checkbox" id="ac-nullable" checked /> Nullable</label>
      <div class="modal-actions">
        <button class="btn" id="ac-cancel">Cancel</button>
        <button class="btn btn-accent" id="ac-save">Add column</button>
      </div>
    `);
    backdrop.querySelector("#ac-cancel").addEventListener("click", () => backdrop.remove());
    backdrop.querySelector("#ac-save").addEventListener("click", async () => {
      const name = backdrop.querySelector("#ac-name").value.trim();
      const type = backdrop.querySelector("#ac-type").value;
      const nullable = backdrop.querySelector("#ac-nullable").checked;
      if (!name) { toast("Column name is required.", "error"); return; }
      try {
        await api(`/api/tables/${encodeURIComponent(tableName)}/columns`, { method: "POST", body: { name, type, nullable } });
        toast(`Column "${name}" added.`, "success");
        backdrop.remove();
        onDone();
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  function openRecordModal(tableName, schema, existing, onDone) {
    const pk = pkColumn(schema);
    const editable = schema.filter((c) => c.name !== pk);
    const backdrop = openModal(`
      <div class="modal-head"><h2>${existing ? "Edit record" : "New record"}</h2></div>
      <form id="rec-form">
        ${editable.map((c) => `
          <div class="field">
            <label>${esc(c.name)}${c.nullable ? "" : " *"}</label>
            <input class="input" data-field="${esc(c.name)}" type="${inputTypeFor(c)}"
              ${inputTypeFor(c) === "number" ? "step=\"any\"" : ""}
              value="${existing ? esc(existing[c.name]) : ""}" ${c.nullable ? "" : "required"} />
          </div>
        `).join("")}
        <div class="modal-actions">
          <button type="button" class="btn" id="rec-cancel">Cancel</button>
          <button type="submit" class="btn btn-accent">${existing ? "Save changes" : "Create record"}</button>
        </div>
      </form>
    `);
    backdrop.querySelector("#rec-cancel").addEventListener("click", () => backdrop.remove());
    backdrop.querySelector("#rec-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const payload = {};
      editable.forEach((c) => {
        const input = backdrop.querySelector(`[data-field="${CSS.escape(c.name)}"]`);
        const val = input.value;
        if (val === "") return;
        payload[c.name] = inputTypeFor(c) === "number" ? Number(val) : val;
      });
      try {
        if (existing) {
          await api(`/api/db/update/${encodeURIComponent(tableName)}?${pk}=${encodeURIComponent(existing[pk])}`, { method: "PUT", body: payload });
          toast("Record updated.", "success");
        } else {
          await api(`/api/db/create/${encodeURIComponent(tableName)}`, { method: "POST", body: payload });
          toast("Record created.", "success");
        }
        backdrop.remove();
        onDone();
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  render();
})();
