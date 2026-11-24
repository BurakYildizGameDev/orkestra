"use strict";
// Orkestra web interface (Faz 11c). Every visible text comes from the catalog through tr();
// nodes are built with textContent only (no innerHTML).
const TOKEN = __TOKEN__;
const I18N = __I18N__;

const OVERALL_STATES = ["ok", "warn", "fail"];
const PROVIDER_STATES = ["ready", "paused", "no_consent", "no_key", "disabled", "check_failed"];
const KEY_STATES = ["env", "keyring", "none"];
const DOC_LEVELS = ["ok", "warn", "fail", "info"];
const TYPES = ["ollama", "openai_compat", "cli_agent"];

let teamWorkers = [];
let toastTimer = null;

// ---------- helpers ----------
function tr(key, values) {
    let out = I18N[key];
    if (out === undefined) return key;
    if (values) {
        Object.keys(values).forEach(name => {
            out = out.split("{" + name + "}").join(String(values[name]));
        });
    }
    return out;
}

function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
}

function oneOf(value, allowed, fallback) {
    return allowed.includes(value) ? value : fallback;
}

function dot(state, allowed) {
    return el("span", "dot is-" + oneOf(state, allowed, allowed[allowed.length - 1]));
}

function statusLabel(state, allowed, text) {
    const wrap = el("span", "status");
    wrap.appendChild(dot(state, allowed));
    wrap.appendChild(el("span", "", text));
    return wrap;
}

function joined(container, parts) {
    parts.filter(p => p !== null && p !== undefined && p !== "").forEach((part, i) => {
        if (i > 0) container.appendChild(el("span", "sep", "·"));
        container.appendChild(typeof part === "string" ? el("span", "", part) : part);
    });
}

function money(value) {
    const v = Number(value || 0);
    if (v === 0) return "$0";
    return "$" + (v < 0.01 ? v.toFixed(4) : v.toFixed(2));
}

function typeLabel(type) {
    return TYPES.includes(type) ? tr("team.type." + type) : String(type || "");
}

function toast(text, isError) {
    const box = document.getElementById("feedback");
    box.textContent = text;
    box.classList.toggle("is-error", Boolean(isError));
    box.style.display = "block";
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { box.style.display = "none"; }, isError ? 12000 : 5000);
}

function toastError(err) {
    toast(tr("home.error_prefix") + ": " + (err && err.message ? err.message : String(err)), true);
}

async function api(path, body) {
    const url = new URL(path, window.location.origin);
    url.searchParams.set("token", TOKEN);
    const options = body === undefined ? {} : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    };
    const res = await fetch(url.toString(), options);
    let data = {};
    try {
        data = await res.json();
    } catch (parseErr) {
        data = {};
    }
    if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
    return data;
}

// ---------- navigation ----------
const LOADERS = {
    home: () => loadHome(),
    team: () => loadTeam(),
    keys: () => loadKeys(),
    usage: () => loadUsage(),
    guide: () => {},
    advanced: () => loadAdvanced(),
};

function switchTab(target) {
    const tab = Object.prototype.hasOwnProperty.call(LOADERS, target) ? target : "home";
    document.querySelectorAll(".nav-item").forEach(item => {
        const active = item.dataset.tab === tab;
        item.classList.toggle("active", active);
        item.setAttribute("aria-pressed", String(active));
    });
    Object.keys(LOADERS).forEach(name => {
        document.getElementById("view-" + name).hidden = (name !== tab);
    });
    LOADERS[tab]();
}

document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", () => switchTab(item.dataset.tab));
});

document.getElementById("feedback").addEventListener("click", () => {
    document.getElementById("feedback").style.display = "none";
});

// ---------- home ----------
async function loadHome() {
    try {
        renderHome(await api("/api/home"));
    } catch (err) {
        toast(tr("home.feedback.load_failed") + ": " + err.message, true);
    }
}

function renderHome(data) {
    const status = oneOf(data.status, OVERALL_STATES, "warn");
    document.getElementById("status-dot").className = "dot is-" + status;
    document.getElementById("status-text").textContent = data.status_text || "";
    document.getElementById("next-step-text").textContent = data.next_step || "";

    const list = document.getElementById("providers-container");
    list.replaceChildren();
    const providers = data.providers || [];
    if (providers.length === 0) list.appendChild(el("div", "empty", tr("home.no_providers")));
    providers.forEach(p => {
        const row = el("div", "row");
        row.appendChild(el("div", "row-name", p.name));
        const desc = el("div", "row-desc");
        joined(desc, [p.is_local && p.local_text ? p.local_text : typeLabel(p.type), p.limits_text]);
        row.appendChild(desc);
        const side = el("div", "row-side");
        if (p.doctor_status && DOC_LEVELS.includes(p.doctor_status)) {
            side.appendChild(el("span", "doc doc-" + p.doctor_status,
                tr("home.doctor.badge." + p.doctor_status)));
        }
        side.appendChild(statusLabel(p.status, PROVIDER_STATES, p.status_text || ""));
        row.appendChild(side);
        list.appendChild(row);
    });

    const today = data.today || {};
    document.getElementById("today-text").textContent =
        tr("home.today.runs", { count: today.runs || 0 }) + " · " + money(today.cost_usd);

    const windows = data.claude_windows || [];
    document.getElementById("claude-fact").hidden = windows.length === 0;
    document.getElementById("claude-text").textContent = windows.map(w =>
        tr("home.claude.window", {
            label: tr("home.claude." + w.name),
            used: Math.round(w.used || 0),
        })).join(" · ");

    const pending = data.pending || {};
    const parts = [];
    if (pending.unapplied_runs > 0) {
        parts.push(tr("home.pending.unapplied", { count: pending.unapplied_runs }));
    }
    if (pending.queue_pending > 0 || pending.queue_running > 0 || pending.queue_failed > 0) {
        parts.push(tr("home.queue.summary", {
            pending: pending.queue_pending || 0,
            running: pending.queue_running || 0,
            failed: pending.queue_failed || 0,
        }));
    }
    document.getElementById("pending-text").textContent =
        parts.length > 0 ? parts.join(" · ") : tr("home.pending.none");
}

document.getElementById("btn-test-all").addEventListener("click", async () => {
    const btn = document.getElementById("btn-test-all");
    btn.disabled = true;
    toast(tr("home.doctor.running"));
    const finish = (text, isError) => {
        btn.disabled = false;
        toast(text, isError);
    };
    try {
        await api("/api/doctor", {});
    } catch (err) {
        finish(tr("home.doctor.start_failed") + ": " + err.message, true);
        return;
    }
    const poll = setInterval(async () => {
        try {
            const doc = await api("/api/doctor");
            if (doc.status === "running") return;
            clearInterval(poll);
            if (doc.status === "done") {
                finish(tr("home.doctor.done"));
                loadHome();
            } else if (doc.status === "failed") {
                finish(tr("home.doctor.failed") + (doc.error ? ": " + doc.error : ""), true);
            } else {
                finish(tr("home.doctor.idle"));
            }
        } catch (err) {
            clearInterval(poll);
            finish(tr("home.error_prefix") + ": " + err.message, true);
        }
    }, 1000);
});

document.getElementById("btn-notify-test").addEventListener("click", async () => {
    const btn = document.getElementById("btn-notify-test");
    btn.disabled = true;
    toast(tr("home.notify.sending"));
    try {
        const data = await api("/api/notify/test", {});
        const lines = data.lines || [];
        toast(lines.length > 0 ? lines.join(" · ") : tr("home.notify.sent"));
    } catch (err) {
        toast(tr("home.notify.error") + ": " + err.message, true);
    } finally {
        btn.disabled = false;
    }
});

// ---------- team ----------
async function loadTeam() {
    try {
        renderTeam(await api("/api/team"));
    } catch (err) {
        toast(tr("home.feedback.load_failed") + ": " + err.message, true);
    }
}

async function teamAction(path, body, message) {
    try {
        const data = await api(path, body);
        if (message) toast(message);
        renderTeam(data);
    } catch (err) {
        toastError(err);
        loadTeam();
    }
}

function renderTeam(data) {
    const select = document.getElementById("patron-select");
    select.replaceChildren();
    (data.chiefs || []).forEach(c => {
        const opt = el("option", "", c.name);
        opt.value = c.name;
        opt.selected = c.name === data.patron;
        select.appendChild(opt);
    });
    document.getElementById("patron-handoff-order").textContent =
        (data.handoff_order || []).join(" → ");
    teamWorkers = data.workers || [];
    renderWorkers();
}

function workerRow(w, idx) {
    const row = el("div", "row");

    const nameCell = el("div", "row-name name-cell");
    const reorder = el("span", "reorder");
    const up = el("button", "btn btn-quiet btn-icon", "▲");
    up.title = tr("team.worker.move_up");
    up.setAttribute("aria-label", up.title);
    up.disabled = idx === 0;
    up.addEventListener("click", () => moveWorker(idx, -1));
    const down = el("button", "btn btn-quiet btn-icon", "▼");
    down.title = tr("team.worker.move_down");
    down.setAttribute("aria-label", down.title);
    down.disabled = idx === teamWorkers.length - 1;
    down.addEventListener("click", () => moveWorker(idx, 1));
    reorder.appendChild(up);
    reorder.appendChild(down);
    nameCell.appendChild(reorder);
    nameCell.appendChild(el("span", "", w.name));
    row.appendChild(nameCell);

    const desc = el("div", "row-desc");
    let model = w.selected_model || null;
    if ((w.models || []).length > 1) {
        model = el("select", "");
        model.setAttribute("aria-label", tr("team.worker.model"));
        w.models.forEach(id => {
            const opt = el("option", "", id);
            opt.value = id;
            opt.selected = id === w.selected_model;
            model.appendChild(opt);
        });
        model.addEventListener("change", e => teamAction("/api/team/worker/model",
            { name: w.name, model: e.target.value },
            tr("team.feedback.model_saved", { name: w.name, model: e.target.value })));
    }
    const tier = el("span", "");
    tier.appendChild(el("span", "", tr("team.worker.tier") + " "));
    const tierSelect = el("select", "");
    tierSelect.setAttribute("aria-label", tr("team.worker.tier"));
    [1, 2, 3].forEach(value => {
        const opt = el("option", "", value);
        opt.value = String(value);
        opt.selected = w.tier === value;
        tierSelect.appendChild(opt);
    });
    tierSelect.addEventListener("change", e => {
        const value = parseInt(e.target.value, 10);
        teamAction("/api/team/worker/tier", { name: w.name, tier: value },
            tr("team.feedback.tier_saved", { name: w.name, tier: value }));
    });
    tier.appendChild(tierSelect);
    joined(desc, [typeLabel(w.type), model, tier]);
    row.appendChild(desc);

    const side = el("div", "row-side");
    if (w.consent_state === "missing" || w.consent_state === "changed") {
        side.appendChild(statusLabel("paused", PROVIDER_STATES, w.consent_state === "missing"
            ? tr("team.worker.consent_missing") : tr("team.worker.consent_changed")));
        const grant = el("button", "btn btn-primary", tr("team.worker.consent_grant"));
        grant.addEventListener("click", () => teamAction("/api/team/consent", { name: w.name },
            tr("team.feedback.consent_granted", { name: w.name })));
        side.appendChild(grant);
    }
    const toggle = el("label", "switch");
    const box = el("input", "");
    box.type = "checkbox";
    box.checked = Boolean(w.enabled);
    box.addEventListener("change", () => teamAction("/api/team/worker/toggle",
        { name: w.name, enabled: box.checked }, null));
    toggle.appendChild(box);
    toggle.appendChild(el("span", "", w.enabled ? tr("team.worker.enabled") : tr("team.worker.disabled")));
    side.appendChild(toggle);
    const remove = el("button", "btn btn-quiet btn-danger", tr("team.worker.remove"));
    remove.addEventListener("click", () => {
        if (!confirm(tr("team.worker.remove_confirm", { name: w.name }))) return;
        teamAction("/api/team/worker/remove", { name: w.name },
            tr("team.feedback.removed", { name: w.name }));
    });
    side.appendChild(remove);
    row.appendChild(side);
    return row;
}

function renderWorkers() {
    const list = document.getElementById("team-workers-container");
    list.replaceChildren();
    if (teamWorkers.length === 0) list.appendChild(el("div", "empty", tr("team.workers.empty")));
    teamWorkers.forEach((w, idx) => list.appendChild(workerRow(w, idx)));
}

function moveWorker(idx, dir) {
    const target = idx + dir;
    if (target < 0 || target >= teamWorkers.length) return;
    const names = teamWorkers.map(w => w.name);
    [names[idx], names[target]] = [names[target], names[idx]];
    teamAction("/api/team/worker/reorder", { names }, tr("team.feedback.reordered"));
}

document.getElementById("patron-select").addEventListener("change", e => {
    teamAction("/api/team/patron", { chief: e.target.value },
        tr("team.patron.saved", { name: e.target.value }));
});

const ADD_DEFAULTS = {
    ollama: { tier: "1", url: "http://localhost:11434" },
    openai_compat: { tier: "2", url: "https://openrouter.ai/api/v1" },
    cli_agent: { tier: "3", url: "" },
};

function showAddFields(type) {
    document.getElementById("add-group-url").hidden = type === "cli_agent";
    document.getElementById("add-group-key-env").hidden = type !== "openai_compat";
    document.getElementById("add-group-command").hidden = type !== "cli_agent";
    document.getElementById("add-worker-tier").value = ADD_DEFAULTS[type].tier;
    document.getElementById("add-worker-url").value = ADD_DEFAULTS[type].url;
}

document.getElementById("btn-toggle-add-worker").addEventListener("click", () => {
    const form = document.getElementById("team-add-form");
    form.hidden = !form.hidden;
    if (!form.hidden) document.getElementById("add-worker-name").focus();
});

document.getElementById("btn-add-worker-cancel").addEventListener("click", () => {
    document.getElementById("team-add-form").hidden = true;
});

document.getElementById("add-worker-type").addEventListener("change", e => showAddFields(e.target.value));

document.getElementById("team-add-form").addEventListener("submit", async e => {
    e.preventDefault();
    const value = id => document.getElementById(id).value.trim();
    const type = document.getElementById("add-worker-type").value;
    const noKey = document.getElementById("add-worker-no-key").checked;
    const name = value("add-worker-name");
    const payload = {
        type: type,
        name: name,
        model: value("add-worker-model"),
        tier: parseInt(document.getElementById("add-worker-tier").value, 10),
        base_url: type !== "cli_agent" ? value("add-worker-url") : null,
        api_key_env: (type === "openai_compat" && !noKey && value("add-worker-key-env"))
            ? value("add-worker-key-env") : null,
        command: (type === "cli_agent" && value("add-worker-command")) ? value("add-worker-command") : null,
        no_key: type === "openai_compat" && noKey,
    };
    try {
        const data = await api("/api/team/worker/add", payload);
        const form = document.getElementById("team-add-form");
        form.reset();
        form.hidden = true;
        showAddFields("ollama");
        toast(tr("team.add.success", { name: name }));
        renderTeam(data);
    } catch (err) {
        toastError(err);
    }
});

// ---------- keys ----------
async function loadKeys() {
    try {
        renderKeys((await api("/api/keys")).keys || []);
    } catch (err) {
        toast(tr("home.feedback.load_failed") + ": " + err.message, true);
    }
}

function keyUsers(k) {
    return (k.providers || []).map(name => name === "notify" ? tr("keys.notify") : name).join(", ");
}

function keyRow(k) {
    const row = el("div", "row");
    row.appendChild(el("div", "row-name mono", k.var_name));
    row.appendChild(el("div", "row-desc", tr("keys.used_by", { names: keyUsers(k) })));
    const side = el("div", "row-side");
    side.appendChild(statusLabel(k.source, KEY_STATES, tr("keys.state." + oneOf(k.source, KEY_STATES, "none"))));
    row.appendChild(side);

    const extra = el("div", "row-extra");
    const controls = el("div", "inline");
    const result = el("span", "small muted");
    if (k.source === "env") {
        extra.appendChild(el("div", "", tr("keys.env_note")));
    } else {
        const input = el("input", "");
        input.type = "password";
        input.autocomplete = "off";
        input.placeholder = tr("keys.placeholder");
        input.setAttribute("aria-label", k.var_name);
        controls.appendChild(input);
        const save = el("button", "btn btn-primary", tr("keys.action.save"));
        save.addEventListener("click", async () => {
            const secret = input.value.trim();
            if (!secret) return;
            save.disabled = true;
            try {
                const data = await api("/api/keys/set", { var_name: k.var_name, key: secret });
                input.value = "";
                toast(tr("keys.feedback.saved", { var: k.var_name }));
                renderKeys(data.keys || []);
            } catch (err) {
                toastError(err);
            } finally {
                save.disabled = false;
            }
        });
        controls.appendChild(save);
    }
    if (k.source === "keyring") {
        const del = el("button", "btn btn-quiet btn-danger", tr("keys.action.delete"));
        del.addEventListener("click", async () => {
            if (!confirm(tr("keys.confirm_delete", { var: k.var_name }))) return;
            try {
                const data = await api("/api/keys/delete", { var_name: k.var_name });
                toast(tr("keys.feedback.deleted", { var: k.var_name }));
                renderKeys(data.keys || []);
            } catch (err) {
                toastError(err);
            }
        });
        controls.appendChild(del);
    }
    const testable = (k.providers || []).some(name => name !== "notify");
    if (k.defined && testable) {
        const tryBtn = el("button", "btn", tr("keys.action.test"));
        tryBtn.addEventListener("click", async () => {
            tryBtn.disabled = true;
            result.textContent = tr("keys.test.running");
            try {
                const data = await api("/api/keys/test", { var_name: k.var_name });
                result.replaceChildren();
                (data.results || []).forEach(r => {
                    const line = el("div", "");
                    line.appendChild(dot(r.status, DOC_LEVELS));
                    line.appendChild(el("span", "", " " + r.provider + ": " + r.message));
                    result.appendChild(line);
                });
            } catch (err) {
                result.textContent = tr("home.error_prefix") + ": " + err.message;
            } finally {
                tryBtn.disabled = false;
            }
        });
        controls.appendChild(tryBtn);
    }
    controls.appendChild(result);
    extra.appendChild(controls);
    row.appendChild(extra);
    return row;
}

function renderKeys(list) {
    const box = document.getElementById("keys-container");
    box.replaceChildren();
    if (list.length === 0) box.appendChild(el("div", "empty", tr("keys.empty")));
    list.forEach(k => box.appendChild(keyRow(k)));
}

// ---------- usage ----------
async function loadUsage() {
    try {
        const days = document.getElementById("usage-days").value;
        renderUsage(await api("/api/usage?days=" + encodeURIComponent(days)), Number(days));
    } catch (err) {
        toastError(err);
    }
}

document.getElementById("usage-days").addEventListener("change", () => loadUsage());

function renderUsage(data, days) {
    const totals = data.totals || {};
    document.getElementById("usage-stat-runs").textContent = String(totals.runs || 0);
    document.getElementById("usage-stat-rate").textContent =
        (totals.success_rate === null || totals.success_rate === undefined)
            ? "-" : Math.round(totals.success_rate * 100) + "%";
    document.getElementById("usage-stat-cost").textContent = money(totals.cost_usd);

    const savings = data.savings || {};
    const out = savings.worker_output_tokens || 0;
    const env = savings.envelope_tokens || 0;
    document.getElementById("usage-stat-savings").textContent =
        out > 0 ? tr("usage.savings_value", { tokens: out }) : "-";
    document.getElementById("usage-savings-detail").textContent = out > 0
        ? tr("usage.savings_detail", { out: out, env: env, ratio: env > 0 ? (out / env).toFixed(1) : "-" })
        : "";

    renderChart(document.getElementById("usage-chart-container"), data.daily || [], data.until, days);

    const body = document.getElementById("usage-providers-table");
    body.replaceChildren();
    const providers = data.providers || [];
    if (providers.length === 0) {
        const tr0 = el("tr", "");
        const td = el("td", "empty", tr("usage.chart.empty"));
        td.colSpan = 5;
        tr0.appendChild(td);
        body.appendChild(tr0);
    }
    providers.forEach(p => {
        const line = el("tr", "");
        line.appendChild(el("td", "", p.provider || "-"));
        line.appendChild(el("td", "num", p.runs || 0));
        line.appendChild(el("td", "num", (p.success_rate === null || p.success_rate === undefined)
            ? "-" : Math.round(p.success_rate * 100) + "%"));
        line.appendChild(el("td", "num", money(p.cost_usd)));
        line.appendChild(el("td", "num", (p.prompt_tokens || 0) + (p.completion_tokens || 0)));
        body.appendChild(line);
    });
}

function renderChart(box, daily, until, days) {
    box.replaceChildren();
    if (daily.length === 0) {
        box.appendChild(el("div", "empty", tr("usage.chart.empty")));
        return;
    }
    const byDay = {};
    daily.forEach(d => { byDay[d.date] = d; });
    const end = new Date(String(until || "").slice(0, 10) + "T00:00:00Z");
    const span = days || 7;
    const dates = [];
    for (let i = span - 1; i >= 0; i--) {
        dates.push(new Date(end.getTime() - i * 86400000).toISOString().slice(0, 10));
    }
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    // The real width: a stretched viewBox would stretch the labels too.
    const width = Math.max(320, Math.round(box.clientWidth || 600));
    const top = 16;
    const base = 150;
    svg.setAttribute("viewBox", "0 0 " + width + " 180");
    const most = Math.max(1, ...dates.map(day => (byDay[day] ? byDay[day].runs : 0)));
    const slot = width / dates.length;
    const barWidth = Math.max(3, slot * 0.6);
    const labelEvery = dates.length > 10 ? 5 : 1;
    const rect = (cls, x, y, h) => {
        const r = document.createElementNS(ns, "rect");
        r.setAttribute("class", cls);
        r.setAttribute("x", String(x));
        r.setAttribute("y", String(y));
        r.setAttribute("width", String(barWidth));
        r.setAttribute("height", String(Math.max(0, h)));
        r.setAttribute("rx", "2");
        svg.appendChild(r);
    };
    const text = (cls, x, y, value) => {
        const t = document.createElementNS(ns, "text");
        t.setAttribute("class", cls);
        t.setAttribute("x", String(x));
        t.setAttribute("y", String(y));
        t.setAttribute("text-anchor", "middle");
        t.textContent = value;
        svg.appendChild(t);
    };
    dates.forEach((day, i) => {
        const d = byDay[day] || { runs: 0, ok: 0 };
        const x = i * slot + (slot - barWidth) / 2;
        const okHeight = (d.ok / most) * (base - top);
        const failHeight = ((d.runs - d.ok) / most) * (base - top);
        if (d.ok > 0) rect("bar-ok", x, base - okHeight, okHeight);
        if (d.runs > d.ok) rect("bar-fail", x, base - okHeight - failHeight, failHeight);
        if (d.runs > 0) text("bar-count", x + barWidth / 2, base - okHeight - failHeight - 4, d.runs);
        if (i % labelEvery === 0 || i === dates.length - 1) {
            text("axis", x + barWidth / 2, 170, day.slice(5));
        }
    });
    box.appendChild(svg);
}

// ---------- advanced ----------
async function loadAdvanced() {
    try {
        renderAdvanced(await api("/api/advanced"));
    } catch (err) {
        toastError(err);
    }
}

function lines(box, texts) {
    box.replaceChildren();
    texts.forEach(text => box.appendChild(el("div", "", text)));
}

function renderAdvanced(data) {
    const breakers = document.getElementById("adv-breakers-container");
    breakers.replaceChildren();
    (data.circuit_breakers || []).forEach(br => {
        const row = el("div", "row");
        row.appendChild(el("div", "row-name", br.provider));
        const desc = el("div", "row-desc");
        joined(desc, [
            br.is_open ? br.reason_text : null,
            br.is_open && br.until_text ? tr("advanced.breaker.until", { until: br.until_text }) : null,
            br.consecutive_failures > 0
                ? tr("advanced.breaker.failures", { count: br.consecutive_failures }) : null,
        ]);
        row.appendChild(desc);
        const side = el("div", "row-side");
        side.appendChild(statusLabel(br.is_open ? "fail" : "ok", OVERALL_STATES,
            br.is_open ? tr("advanced.breaker.open") : tr("advanced.breaker.ok")));
        row.appendChild(side);
        breakers.appendChild(row);
    });

    const budgets = (data.budgets || {}).providers || {};
    const budgetLines = Object.keys(budgets).map(name => name + ": " + Object.keys(budgets[name])
        .map(limit => tr("advanced.budget." + limit, { value: budgets[name][limit] })).join(", "));
    lines(document.getElementById("adv-budgets-container"),
        budgetLines.length > 0 ? budgetLines : [tr("advanced.budget.none")]);

    const profiles = data.profiles || {};
    const defs = profiles.definitions || {};
    lines(document.getElementById("adv-profiles-container"),
        [tr("advanced.profile.active", { name: profiles.active || "" })].concat(
            Object.keys(defs).map(name => tr("advanced.profile.line",
                { name: name, min: defs[name].min_tier, max: defs[name].max_tier }))));

    const queue = document.getElementById("adv-queue-container");
    queue.replaceChildren();
    const items = (data.queue || {}).items || [];
    if (items.length === 0) queue.appendChild(el("div", "empty", tr("advanced.queue.empty")));
    items.forEach(it => {
        const row = el("div", "row");
        row.appendChild(el("div", "row-name", "#" + it.id));
        row.appendChild(el("div", "row-desc mono", it.path));
        const side = el("div", "row-side");
        side.appendChild(el("span", "small muted", it.kind + " · " + it.status));
        row.appendChild(side);
        queue.appendChild(row);
    });

    document.getElementById("adv-handoff-container").textContent = (data.handoff || {}).text || "";

    const st = data.settings || {};
    lines(document.getElementById("adv-settings-container"), [
        tr("advanced.settings.language", { value: st.language }),
        tr("advanced.settings.chief", { value: st.chief }),
        tr("advanced.settings.profile", { value: st.profile }),
    ]);
}

switchTab("home");
