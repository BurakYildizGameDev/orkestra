"""HTML/CSS/JS user interface template for Orkestra Web UI (Faz 11c-b).

Self-contained: no external CDN or fonts. Light and dark theme via CSS variables.
"""

from __future__ import annotations

import html
import json

from orkestra import __version__
from orkestra.i18n import get_language, t


def render_home_html(token: str) -> str:
    current_lang = get_language()
    safe_token = html.escape(token)

    i18n_dict = {
        "error_prefix": t("home.error_prefix"),
        "load_failed": t("home.feedback.load_failed"),
        "today_runs": t("home.today.runs_suffix"),
        "pending_unapplied": t("home.pending.unapplied"),
        "queue_summary": t("home.queue.summary"),
        "home_no_providers": t("home.no_providers"),
        "home_local": t("home.provider.local"),
        "home_doctor_running": t("home.doctor.running"),
        "home_doctor_done": t("home.doctor.done"),
        "home_doctor_failed": t("home.doctor.failed"),
        "home_doctor_start_failed": t("home.doctor.start_failed"),
        "home_doctor_idle": t("home.doctor.idle"),
        "home_notify_sending": t("home.notify.sending"),
        "home_notify_sent": t("home.notify.sent"),
        "home_notify_error": t("home.notify.error"),
    }
    safe_i18n_json = (
        json.dumps(i18n_dict, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )

    return f"""<!DOCTYPE html>
<html lang="{html.escape(current_lang)}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Orkestra</title>
    <style>
        :root {{
            --bg-page: #f8fafc;
            --bg-card: #ffffff;
            --bg-sidebar: #0f172a;
            --sidebar-text: #94a3b8;
            --sidebar-active: #ffffff;
            --sidebar-active-bg: #1e293b;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --border: #e2e8f0;
            --btn-bg: #2563eb;
            --btn-text: #ffffff;
            --btn-hover: #1d4ed8;
            --btn-sec-bg: #f1f5f9;
            --btn-sec-text: #334155;
            --btn-sec-hover: #e2e8f0;
            --ok-bg: #ecfdf5;
            --ok-text: #065f46;
            --ok-border: #a7f3d0;
            --warn-bg: #fffbeb;
            --warn-text: #92400e;
            --warn-border: #fde68a;
            --fail-bg: #fef2f2;
            --fail-text: #991b1b;
            --fail-border: #fecaca;
            --tag-local-bg: #eff6ff;
            --tag-local-text: #1e40af;
        }}
        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg-page: #0b0f17;
                --bg-card: #151d2a;
                --bg-sidebar: #070a0f;
                --sidebar-text: #64748b;
                --sidebar-active: #f8fafc;
                --sidebar-active-bg: #1e293b;
                --text-main: #f8fafc;
                --text-muted: #94a3b8;
                --border: #222f3e;
                --btn-bg: #3b82f6;
                --btn-text: #ffffff;
                --btn-hover: #2563eb;
                --btn-sec-bg: #1e293b;
                --btn-sec-text: #cbd5e1;
                --btn-sec-hover: #334155;
                --ok-bg: #064e3b;
                --ok-text: #a7f3d0;
                --ok-border: #047857;
                --warn-bg: #78350f;
                --warn-text: #fde68a;
                --warn-border: #b45309;
                --fail-bg: #7f1d1d;
                --fail-text: #fecaca;
                --fail-border: #b91c1c;
                --tag-local-bg: #1e3a8a;
                --tag-local-text: #bfdbfe;
            }}
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                Helvetica, Arial, sans-serif;
            background-color: var(--bg-page);
            color: var(--text-main);
            display: flex;
            min-height: 100vh;
        }}
        .sidebar {{
            width: 240px;
            background-color: var(--bg-sidebar);
            color: var(--sidebar-text);
            display: flex;
            flex-direction: column;
            padding: 1.5rem 1rem;
            flex-shrink: 0;
        }}
        .brand {{
            font-size: 1.25rem;
            font-weight: 700;
            color: #ffffff;
            margin-bottom: 2rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .brand .version {{
            font-size: 0.75rem;
            font-weight: 400;
            color: var(--sidebar-text);
            background: var(--sidebar-active-bg);
            padding: 0.15rem 0.4rem;
            border-radius: 4px;
        }}
        .nav-list {{
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }}
        .nav-item a {{
            display: block;
            padding: 0.6rem 0.8rem;
            color: var(--sidebar-text);
            text-decoration: none;
            border-radius: 6px;
            font-size: 0.875rem;
            transition: all 0.15s ease;
        }}
        .nav-item a:hover {{
            color: var(--sidebar-active);
            background-color: var(--sidebar-active-bg);
        }}
        .nav-item.active a {{
            color: var(--sidebar-active);
            background-color: var(--sidebar-active-bg);
            font-weight: 600;
        }}
        .main-content {{
            flex: 1;
            padding: 2rem;
            max-width: 1200px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.5rem;
        }}
        .header h1 {{
            font-size: 1.5rem;
            font-weight: 700;
        }}
        .header-actions {{
            display: flex;
            gap: 0.75rem;
        }}
        .btn {{
            display: inline-flex;
            align-items: center;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-size: 0.875rem;
            font-weight: 500;
            border: 1px solid transparent;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.15s ease;
        }}
        .btn-primary {{
            background-color: var(--btn-bg);
            color: var(--btn-text);
        }}
        .btn-primary:hover:not(:disabled) {{
            background-color: var(--btn-hover);
        }}
        .btn-secondary {{
            background-color: var(--btn-sec-bg);
            color: var(--btn-sec-text);
            border-color: var(--border);
        }}
        .btn-secondary:hover:not(:disabled) {{
            background-color: var(--btn-sec-hover);
        }}
        .btn:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}
        .feedback-banner {{
            display: none;
            padding: 0.75rem 1rem;
            border-radius: 6px;
            margin-bottom: 1rem;
            font-size: 0.875rem;
            background: var(--bg-card);
            border: 1px solid var(--border);
        }}
        .status-banner {{
            padding: 1.25rem 1.5rem;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            border: 1px solid transparent;
        }}
        .status-ok {{
            background-color: var(--ok-bg);
            color: var(--ok-text);
            border-color: var(--ok-border);
        }}
        .status-warn {{
            background-color: var(--warn-bg);
            color: var(--warn-text);
            border-color: var(--warn-border);
        }}
        .status-fail {{
            background-color: var(--fail-bg);
            color: var(--fail-text);
            border-color: var(--fail-border);
        }}
        .status-title {{
            font-size: 1.125rem;
            font-weight: 600;
            margin-bottom: 0.25rem;
        }}
        .status-next {{
            font-size: 0.875rem;
            opacity: 0.9;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }}
        .card {{
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.25rem;
        }}
        .card-title {{
            font-size: 0.875rem;
            font-weight: 600;
            color: var(--text-muted);
            margin-bottom: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        .card-number {{
            font-size: 1.75rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
        }}
        .card-subtitle {{
            font-size: 0.875rem;
            color: var(--text-muted);
        }}
        .provider-list {{
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            margin-top: 0.5rem;
        }}
        .provider-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.6rem 0;
            border-bottom: 1px solid var(--border);
        }}
        .provider-row:last-child {{
            border-bottom: none;
        }}
        .provider-info {{
            display: flex;
            flex-direction: column;
        }}
        .provider-name {{
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        .provider-meta {{
            font-size: 0.75rem;
            color: var(--text-muted);
            display: flex;
            gap: 0.5rem;
            align-items: center;
        }}
        .tag {{
            display: inline-block;
            padding: 0.15rem 0.45rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        .tag-ready {{ background: var(--ok-bg); color: var(--ok-text); }}
        .tag-paused {{ background: var(--warn-bg); color: var(--warn-text); }}
        .tag-no_consent {{ background: var(--warn-bg); color: var(--warn-text); }}
        .tag-no_key {{ background: var(--fail-bg); color: var(--fail-text); }}
        .tag-check_failed {{ background: var(--fail-bg); color: var(--fail-text); }}
        .tag-disabled {{ background: var(--btn-sec-bg); color: var(--text-muted); }}
        .tag-local {{ background: var(--tag-local-bg); color: var(--tag-local-text); }}
        .doc-badge {{
            font-size: 0.75rem;
            padding: 0.1rem 0.35rem;
            border-radius: 3px;
            margin-left: 0.35rem;
        }}
        .doc-ok {{ background: var(--ok-bg); color: var(--ok-text); }}
        .doc-fail {{ background: var(--fail-bg); color: var(--fail-text); }}
        .doc-warn {{ background: var(--warn-bg); color: var(--warn-text); }}
        .doc-info {{ background: var(--btn-sec-bg); color: var(--text-muted); }}
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="brand">
            Orkestra
            <span class="version">v{__version__}</span>
        </div>
        <ul class="nav-list">
            <li class="nav-item active"><a href="#home">{html.escape(t("home.nav.home"))}</a></li>
            <li class="nav-item"><a href="#team">{html.escape(t("home.nav.team"))}</a></li>
            <li class="nav-item"><a href="#keys">{html.escape(t("home.nav.keys"))}</a></li>
            <li class="nav-item"><a href="#usage">{html.escape(t("home.nav.usage"))}</a></li>
            <li class="nav-item"><a href="#guide">{html.escape(t("home.nav.guide"))}</a></li>
            <li class="nav-item"><a href="#advanced">{html.escape(t("home.nav.advanced"))}</a></li>
        </ul>
    </div>
    <div class="main-content">
        <div class="header">
            <h1 id="page-title">{html.escape(t("home.title"))}</h1>
            <div class="header-actions">
                <button id="btn-test-all" class="btn btn-primary">
                    {html.escape(t("home.button.test_all"))}
                </button>
                <button id="btn-notify-test" class="btn btn-secondary">
                    {html.escape(t("home.button.notify_test"))}
                </button>
            </div>
        </div>

        <div id="feedback" class="feedback-banner"></div>

        <div id="status-card" class="status-banner status-ok">
            <div id="status-text" class="status-title">{html.escape(t("home.loading"))}</div>
            <div id="next-step-text" class="status-next"></div>
        </div>

        <div class="grid">
            <div class="card">
                <div class="card-title">{html.escape(t("home.card.today"))}</div>
                <div id="today-runs" class="card-number">0</div>
                <div class="card-subtitle">
                    <span id="today-cost">$0.0000</span> {html.escape(t("home.card.cost_label"))}
                </div>
            </div>
            <div id="claude-card" class="card" style="display: none;">
                <div class="card-title">{html.escape(t("home.card.claude_quota"))}</div>
                <div id="claude-content" class="provider-list"></div>
            </div>
            <div class="card">
                <div class="card-title">{html.escape(t("home.card.pending"))}</div>
                <div id="unapplied-count" class="card-number">0</div>
                <div id="queue-count" class="card-subtitle"></div>
            </div>
        </div>

        <div class="card">
            <div class="card-title">{html.escape(t("home.card.providers"))}</div>
            <div id="providers-container" class="provider-list"></div>
        </div>
    </div>

    <script>
        const TOKEN = "{safe_token}";
        const API_BASE = window.location.origin;
        const I18N = {safe_i18n_json};

        async function fetchWithToken(path, options = {{}}) {{
            const url = new URL(path, API_BASE);
            url.searchParams.set("token", TOKEN);
            return fetch(url.toString(), options);
        }}

        function showFeedback(text, isError = false) {{
            const fb = document.getElementById("feedback");
            fb.style.display = "block";
            fb.style.color = isError ? "var(--fail-text)" : "var(--text-main)";
            fb.textContent = text;
        }}

        async function loadHome() {{
            try {{
                const res = await fetchWithToken("/api/home");
                if (!res.ok) throw new Error("HTTP " + res.status);
                const data = await res.json();
                renderSummary(data);
            }} catch (err) {{
                showFeedback(I18N.load_failed + ": " + err.message, true);
            }}
        }}

        function renderSummary(data) {{
            const card = document.getElementById("status-card");
            card.className = "status-banner status-" + (data.status || "ok");
            document.getElementById("status-text").textContent = data.status_text || "";
            document.getElementById("next-step-text").textContent = data.next_step || "";

            if (data.today) {{
                const runsEl = document.getElementById("today-runs");
                runsEl.textContent = data.today.runs + " " + I18N.today_runs;
                const cost = "$" + (data.today.cost_usd || 0).toFixed(4);
                document.getElementById("today-cost").textContent = cost;
            }}

            if (data.pending) {{
                const unappliedEl = document.getElementById("unapplied-count");
                unappliedEl.textContent = (
                    data.pending.unapplied_runs + " " + I18N.pending_unapplied
                );
                const qp = data.pending.queue_pending || 0;
                const qr = data.pending.queue_running || 0;
                const qf = data.pending.queue_failed || 0;
                const qText = (I18N.queue_summary || "")
                    .replace("{{pending}}", qp)
                    .replace("{{running}}", qr)
                    .replace("{{failed}}", qf);
                const queueFallback = "Kuyruk: " + qp + ", " + qr + ", " + qf;
                document.getElementById("queue-count").textContent = qText || queueFallback;
            }}

            const claudeCard = document.getElementById("claude-card");
            const claudeCont = document.getElementById("claude-content");
            claudeCont.replaceChildren();
            if (data.claude_windows && data.claude_windows.length > 0) {{
                claudeCard.style.display = "block";
                data.claude_windows.forEach(w => {{
                    const row = document.createElement("div");
                    row.className = "provider-row";
                    const spanLabel = document.createElement("span");
                    spanLabel.textContent = w.label || w.name || "";
                    const spanTag = document.createElement("span");
                    spanTag.className = "tag tag-ready";
                    spanTag.textContent = "%" + Math.round(w.used || 0);
                    row.appendChild(spanLabel);
                    row.appendChild(spanTag);
                    claudeCont.appendChild(row);
                }});
            }} else {{
                claudeCard.style.display = "none";
            }}

            const pCont = document.getElementById("providers-container");
            pCont.replaceChildren();
            if (!data.providers || data.providers.length === 0) {{
                const empty = document.createElement("div");
                empty.className = "card-subtitle";
                empty.textContent = I18N.home_no_providers;
                pCont.appendChild(empty);
            }} else {{
                const validDocStatus = ["ok", "warn", "fail", "info"];
                const validProviderStatus = [
                    "ready", "paused", "no_consent", "no_key", "disabled", "check_failed"
                ];
                data.providers.forEach(p => {{
                    const row = document.createElement("div");
                    row.className = "provider-row";

                    const info = document.createElement("div");
                    info.className = "provider-info";

                    const nameDiv = document.createElement("div");
                    nameDiv.className = "provider-name";
                    nameDiv.textContent = p.name || "";

                    if (p.doctor_status && validDocStatus.includes(p.doctor_status)) {{
                        const docBadge = document.createElement("span");
                        docBadge.className = "doc-badge doc-" + p.doctor_status;
                        docBadge.textContent = p.doctor_status.toUpperCase();
                        nameDiv.appendChild(document.createTextNode(" "));
                        nameDiv.appendChild(docBadge);
                    }}

                    const meta = document.createElement("div");
                    meta.className = "provider-meta";

                    const typeSpan = document.createElement("span");
                    typeSpan.textContent = p.type || "";
                    meta.appendChild(typeSpan);

                    if (p.limits_text) {{
                        const dotSpan = document.createElement("span");
                        dotSpan.textContent = "·";
                        const limitsSpan = document.createElement("span");
                        limitsSpan.textContent = p.limits_text;
                        meta.appendChild(dotSpan);
                        meta.appendChild(limitsSpan);
                    }}

                    info.appendChild(nameDiv);
                    info.appendChild(meta);

                    const actions = document.createElement("div");
                    actions.style.display = "flex";
                    actions.style.gap = "0.5rem";
                    actions.style.alignItems = "center";

                    if (p.is_local) {{
                        const localTag = document.createElement("span");
                        localTag.className = "tag tag-local";
                        localTag.textContent = p.local_text || I18N.home_local;
                        actions.appendChild(localTag);
                    }}

                    const statusTag = document.createElement("span");
                    const stCls = validProviderStatus.includes(p.status) ? p.status : "disabled";
                    statusTag.className = "tag tag-" + stCls;
                    statusTag.textContent = p.status_text || "";
                    actions.appendChild(statusTag);

                    row.appendChild(info);
                    row.appendChild(actions);
                    pCont.appendChild(row);
                }});
            }}
        }}

        document.getElementById("btn-test-all").addEventListener("click", async () => {{
            const btn = document.getElementById("btn-test-all");
            btn.disabled = true;
            showFeedback(I18N.home_doctor_running);
            try {{
                const postRes = await fetchWithToken("/api/doctor", {{ method: "POST" }});
                if (!postRes.ok) {{
                    throw new Error("HTTP " + postRes.status);
                }}
                const poll = setInterval(async () => {{
                    try {{
                        const res = await fetchWithToken("/api/doctor");
                        if (!res.ok) {{
                            clearInterval(poll);
                            btn.disabled = false;
                            showFeedback(I18N.error_prefix + " HTTP " + res.status, true);
                            return;
                        }}
                        const docData = await res.json();
                        if (docData.status === "done") {{
                            clearInterval(poll);
                            btn.disabled = false;
                            showFeedback(I18N.home_doctor_done);
                            loadHome();
                        }} else if (docData.status === "failed") {{
                            clearInterval(poll);
                            btn.disabled = false;
                            const docErr = docData.error ? ": " + docData.error : "";
                            showFeedback(I18N.home_doctor_failed + docErr, true);
                        }} else if (docData.status === "idle") {{
                            clearInterval(poll);
                            btn.disabled = false;
                            showFeedback(I18N.home_doctor_idle, false);
                        }}
                    }} catch (pollErr) {{
                        clearInterval(poll);
                        btn.disabled = false;
                        showFeedback(I18N.error_prefix + ": " + pollErr.message, true);
                    }}
                }}, 1000);
            }} catch (err) {{
                btn.disabled = false;
                showFeedback(I18N.home_doctor_start_failed + ": " + err.message, true);
            }}
        }});

        document.getElementById("btn-notify-test").addEventListener("click", async () => {{
            const btn = document.getElementById("btn-notify-test");
            btn.disabled = true;
            showFeedback(I18N.home_notify_sending);
            try {{
                const res = await fetchWithToken("/api/notify/test", {{ method: "POST" }});
                const data = await res.json();
                btn.disabled = false;
                if (!res.ok) {{
                    const notifyErr = data.error || ("HTTP " + res.status);
                    showFeedback(I18N.home_notify_error + ": " + notifyErr, true);
                }} else if (data.lines && data.lines.length > 0) {{
                    showFeedback(data.lines.join(" · "));
                }} else {{
                    showFeedback(I18N.home_notify_sent);
                }}
            }} catch (err) {{
                btn.disabled = false;
                showFeedback(I18N.home_notify_error + ": " + err.message, true);
            }}
        }});

        loadHome();
    </script>
</body>
</html>
"""
