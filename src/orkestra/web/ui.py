"""HTML/CSS/JS user interface template for Orkestra Web UI (Faz 11c-b, Faz 11c-c).

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

    nav_home = html.escape(t("home.nav.home"))
    nav_team = html.escape(t("home.nav.team"))
    nav_keys = html.escape(t("home.nav.keys"))
    nav_usage = html.escape(t("home.nav.usage"))
    nav_guide = html.escape(t("home.nav.guide"))
    nav_adv = html.escape(t("home.nav.advanced"))

    lbl_home_title = html.escape(t("home.title"))
    lbl_test_all = html.escape(t("home.button.test_all"))
    lbl_notify_test = html.escape(t("home.button.notify_test"))
    lbl_loading = html.escape(t("home.loading"))
    lbl_card_today = html.escape(t("home.card.today"))
    lbl_cost = html.escape(t("home.card.cost_label"))
    lbl_card_claude = html.escape(t("home.card.claude_quota"))
    lbl_card_pending = html.escape(t("home.card.pending"))
    lbl_card_providers = html.escape(t("home.card.providers"))

    lbl_patron_title = html.escape(t("team.patron.title"))
    lbl_patron_select = html.escape(t("team.patron.select"))
    lbl_add_title = html.escape(t("team.add.title"))
    lbl_add_type = html.escape(t("team.add.type"))
    lbl_type_ollama = html.escape(t("team.add.type_ollama"))
    lbl_type_openai = html.escape(t("team.add.type_openai"))
    lbl_type_cli = html.escape(t("team.add.type_cli"))
    lbl_add_name = html.escape(t("team.add.name"))
    lbl_add_model = html.escape(t("team.add.model"))
    lbl_add_tier = html.escape(t("team.add.tier"))
    lbl_add_url = html.escape(t("team.add.base_url"))
    lbl_add_key = html.escape(t("team.add.key_env"))
    lbl_add_cmd = html.escape(t("team.add.command"))
    lbl_add_sub = html.escape(t("team.add.submit"))
    lbl_add_can = html.escape(t("team.add.cancel"))
    lbl_work_title = html.escape(t("team.workers.title"))
    lbl_work_add = html.escape(t("team.workers.add"))

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
        "home_title": t("home.title"),
        "team_title": t("team.title"),
        "team_workers_empty": t("team.workers.empty"),
        "team_worker_enabled": t("team.worker.enabled"),
        "team_worker_disabled": t("team.worker.disabled"),
        "team_worker_tier": t("team.worker.tier"),
        "team_worker_remove": t("team.worker.remove"),
        "team_worker_remove_confirm": t("team.worker.remove_confirm", name="{name}"),
        "team_worker_move_up": t("team.worker.move_up"),
        "team_worker_move_down": t("team.worker.move_down"),
        "team_worker_consent_granted": t("team.worker.consent_granted"),
        "team_worker_consent_missing": t("team.worker.consent_missing"),
        "team_worker_consent_changed": t("team.worker.consent_changed"),
        "team_worker_consent_grant": t("team.worker.consent_grant"),
        "team_patron_saved": t("team.patron.saved", name="{name}"),
        "team_add_success": t("team.add.success", name="{name}"),
        "team_feedback_consent_granted": t("team.feedback.consent_granted", name="{name}"),
        "team_feedback_tier_saved": t("team.feedback.tier_saved", name="{name}", tier="{tier}"),
        "team_feedback_model_saved": t("team.feedback.model_saved", name="{name}", model="{model}"),
        "team_feedback_removed": t("team.feedback.removed", name="{name}"),
        "team_feedback_reordered": t("team.feedback.reordered"),
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
                --fail-border: #991b1b;
                --tag-local-bg: #1e293b;
                --tag-local-text: #93c5fd;
            }}
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }}
        body {{
            display: flex;
            min-height: 100vh;
            background-color: var(--bg-page);
            color: var(--text-main);
        }}
        .sidebar {{
            width: 240px;
            background-color: var(--bg-sidebar);
            color: var(--sidebar-text);
            display: flex;
            flex-direction: column;
            flex-shrink: 0;
        }}
        .brand {{
            padding: 1.5rem;
            font-size: 1.25rem;
            font-weight: 700;
            color: #ffffff;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            border-bottom: 1px solid #1e293b;
        }}
        .brand .version {{
            font-size: 0.75rem;
            color: #64748b;
            font-weight: 400;
        }}
        .nav-list {{
            list-style: none;
            padding: 1rem 0;
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }}
        .nav-item a {{
            display: block;
            padding: 0.75rem 1.5rem;
            color: var(--sidebar-text);
            text-decoration: none;
            font-size: 0.9rem;
            font-weight: 500;
            transition: all 0.15s;
            cursor: pointer;
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
            overflow-y: auto;
            max-width: 1280px;
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
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            border: none;
            transition: background 0.15s;
        }}
        .btn-primary {{
            background-color: var(--btn-bg);
            color: var(--btn-text);
        }}
        .btn-primary:hover {{
            background-color: var(--btn-hover);
        }}
        .btn-primary:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
        }}
        .btn-secondary {{
            background-color: var(--btn-sec-bg);
            color: var(--btn-sec-text);
        }}
        .btn-secondary:hover {{
            background-color: var(--btn-sec-hover);
        }}
        .btn-secondary:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
        }}
        .btn-sm {{
            padding: 0.25rem 0.5rem;
            font-size: 0.75rem;
        }}
        .btn-danger {{
            background-color: var(--fail-bg);
            color: var(--fail-text);
            border: 1px solid var(--fail-border);
        }}
        .btn-danger:hover {{
            background-color: var(--fail-border);
        }}
        .btn-icon {{
            padding: 0.2rem 0.45rem;
            font-size: 0.75rem;
            line-height: 1;
            background: var(--btn-sec-bg);
            color: var(--btn-sec-text);
            border: 1px solid var(--border);
            border-radius: 4px;
            cursor: pointer;
        }}
        .btn-icon:hover {{
            background: var(--btn-sec-hover);
        }}
        .select-sm {{
            padding: 0.3rem 0.5rem;
            font-size: 0.8rem;
            border-radius: 4px;
            border: 1px solid var(--border);
            background: var(--bg-card);
            color: var(--text-main);
        }}
        .input-sm {{
            padding: 0.3rem 0.5rem;
            font-size: 0.8rem;
            border-radius: 4px;
            border: 1px solid var(--border);
            background: var(--bg-card);
            color: var(--text-main);
        }}
        .feedback-banner {{
            padding: 0.75rem 1rem;
            border-radius: 6px;
            margin-bottom: 1rem;
            font-size: 0.875rem;
            display: none;
            background-color: var(--btn-sec-bg);
            border: 1px solid var(--border);
        }}
        .status-banner {{
            padding: 1.25rem;
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
        .team-worker-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem 0;
            border-bottom: 1px solid var(--border);
            gap: 1rem;
            flex-wrap: wrap;
        }}
        .team-worker-row:last-child {{
            border-bottom: none;
        }}
        .team-worker-left {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            flex: 1;
            min-width: 260px;
        }}
        .team-worker-right {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            flex-wrap: wrap;
        }}
        .reorder-btns {{
            display: flex;
            flex-direction: column;
            gap: 2px;
        }}
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="brand">
            Orkestra
            <span class="version">v{__version__}</span>
        </div>
        <ul class="nav-list">
            <li id="nav-home" class="nav-item active" data-tab="home">
                <a>{nav_home}</a>
            </li>
            <li id="nav-team" class="nav-item" data-tab="team">
                <a>{nav_team}</a>
            </li>
            <li id="nav-keys" class="nav-item" data-tab="keys">
                <a>{nav_keys}</a>
            </li>
            <li id="nav-usage" class="nav-item" data-tab="usage">
                <a>{nav_usage}</a>
            </li>
            <li id="nav-guide" class="nav-item" data-tab="guide">
                <a>{nav_guide}</a>
            </li>
            <li id="nav-advanced" class="nav-item" data-tab="advanced">
                <a>{nav_adv}</a>
            </li>
        </ul>
    </div>
    <div class="main-content">
        <div class="header">
            <h1 id="page-title">{lbl_home_title}</h1>
            <div id="home-actions" class="header-actions">
                <button id="btn-test-all" class="btn btn-primary">
                    {lbl_test_all}
                </button>
                <button id="btn-notify-test" class="btn btn-secondary">
                    {lbl_notify_test}
                </button>
            </div>
        </div>

        <div id="feedback" class="feedback-banner"></div>

        <!-- HOME TAB VIEW -->
        <div id="view-home">
            <div id="status-card" class="status-banner status-ok">
                <div id="status-text" class="status-title">{lbl_loading}</div>
                <div id="next-step-text" class="status-next"></div>
            </div>

            <div class="grid">
                <div class="card">
                    <div class="card-title">{lbl_card_today}</div>
                    <div id="today-runs" class="card-number">0</div>
                    <div class="card-subtitle">
                        <span id="today-cost">$0.0000</span> {lbl_cost}
                    </div>
                </div>
                <div id="claude-card" class="card" style="display: none;">
                    <div class="card-title">{lbl_card_claude}</div>
                    <div id="claude-content" class="provider-list"></div>
                </div>
                <div class="card">
                    <div class="card-title">{lbl_card_pending}</div>
                    <div id="unapplied-count" class="card-number">0</div>
                    <div id="queue-count" class="card-subtitle"></div>
                </div>
            </div>

            <div class="card">
                <div class="card-title">{lbl_card_providers}</div>
                <div id="providers-container" class="provider-list"></div>
            </div>
        </div>

        <!-- TEAM TAB VIEW -->
        <div id="view-team" style="display: none;">
            <div class="card" style="margin-bottom: 1.5rem;">
                <div class="card-title">{lbl_patron_title}</div>
                <div style="display:flex; align-items:center; gap: 1rem; flex-wrap:wrap;">
                    <label for="patron-select" style="font-weight:500;">
                        {lbl_patron_select}
                    </label>
                    <select id="patron-select" class="select-sm"
                            style="font-size:0.9rem; padding:0.4rem 0.8rem;">
                    </select>
                    <span id="patron-handoff-order"
                          style="font-size:0.8rem; color:var(--text-muted);">
                    </span>
                </div>
            </div>

            <div id="team-add-card" class="card" style="display: none; margin-bottom: 1.5rem;">
                <div class="card-title">{lbl_add_title}</div>
                <form id="team-add-form"
                      style="display:grid;
                             grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                             gap: 1rem; align-items:end;">
                    <div>
                        <label style="display:block; font-size:0.8rem; font-weight:600;
                                      margin-bottom:0.3rem;">
                            {lbl_add_type}
                        </label>
                        <select id="add-worker-type" class="select-sm"
                                style="width:100%; height:34px;">
                            <option value="ollama">{lbl_type_ollama}</option>
                            <option value="openai_compat">{lbl_type_openai}</option>
                            <option value="cli_agent">{lbl_type_cli}</option>
                        </select>
                    </div>
                    <div>
                        <label style="display:block; font-size:0.8rem; font-weight:600;
                                      margin-bottom:0.3rem;">
                            {lbl_add_name}
                        </label>
                        <input id="add-worker-name" type="text" class="input-sm"
                               style="width:100%; height:34px;"
                               placeholder="provider-name" required>
                    </div>
                    <div>
                        <label style="display:block; font-size:0.8rem; font-weight:600;
                                      margin-bottom:0.3rem;">
                            {lbl_add_model}
                        </label>
                        <input id="add-worker-model" type="text" class="input-sm"
                               style="width:100%; height:34px;"
                               placeholder="llama3:latest" required>
                    </div>
                    <div>
                        <label style="display:block; font-size:0.8rem; font-weight:600;
                                      margin-bottom:0.3rem;">
                            {lbl_add_tier}
                        </label>
                        <select id="add-worker-tier" class="select-sm"
                                style="width:100%; height:34px;">
                            <option value="1">1</option>
                            <option value="2" selected>2</option>
                            <option value="3">3</option>
                        </select>
                    </div>
                    <div id="add-group-url">
                        <label style="display:block; font-size:0.8rem; font-weight:600;
                                      margin-bottom:0.3rem;">
                            {lbl_add_url}
                        </label>
                        <input id="add-worker-url" type="text" class="input-sm"
                               style="width:100%; height:34px;" value="http://localhost:11434">
                    </div>
                    <div id="add-group-key-env" style="display: none;">
                        <label style="display:block; font-size:0.8rem; font-weight:600;
                                      margin-bottom:0.3rem;">
                            {lbl_add_key}
                        </label>
                        <input id="add-worker-key-env" type="text" class="input-sm"
                               style="width:100%; height:34px;" placeholder="SERVICE_API_KEY">
                    </div>
                    <div id="add-group-command" style="display: none;">
                        <label style="display:block; font-size:0.8rem; font-weight:600;
                                      margin-bottom:0.3rem;">
                            {lbl_add_cmd}
                        </label>
                        <input id="add-worker-command" type="text" class="input-sm"
                               style="width:100%; height:34px;" placeholder="agy / codex">
                    </div>
                    <div style="display:flex; gap:0.5rem; height:34px; align-items:center;">
                        <button id="btn-add-worker-submit" type="submit"
                                class="btn btn-primary btn-sm">{lbl_add_sub}</button>
                        <button id="btn-add-worker-cancel" type="button"
                                class="btn btn-secondary btn-sm">{lbl_add_can}</button>
                    </div>
                </form>
            </div>

            <div class="card">
                <div style="display:flex; justify-content:space-between; align-items:center;
                            margin-bottom:1rem;">
                    <div class="card-title" style="margin-bottom:0;">{lbl_work_title}</div>
                    <button id="btn-toggle-add-worker" class="btn btn-secondary btn-sm">
                        {lbl_work_add}
                    </button>
                </div>
                <div id="team-workers-container" class="provider-list"></div>
            </div>
        </div>
    </div>

    <script>
        const TOKEN = "{safe_token}";
        const API_BASE = window.location.origin;
        const I18N = {safe_i18n_json};

        let currentTab = "home";
        let teamWorkers = [];

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

        function switchTab(target) {{
            currentTab = target;
            document.querySelectorAll(".nav-item").forEach(el => {{
                el.classList.toggle("active", el.dataset.tab === target);
            }});
            const viewHome = document.getElementById("view-home");
            const viewTeam = document.getElementById("view-team");
            const homeActions = document.getElementById("home-actions");
            const titleEl = document.getElementById("page-title");

            if (target === "team") {{
                viewHome.style.display = "none";
                viewTeam.style.display = "block";
                homeActions.style.display = "none";
                titleEl.textContent = I18N.team_title || "Team";
                loadTeam();
            }} else {{
                viewHome.style.display = "block";
                viewTeam.style.display = "none";
                homeActions.style.display = "flex";
                titleEl.textContent = I18N.home_title || "Home";
                loadHome();
            }}
        }}

        document.querySelectorAll(".nav-item").forEach(item => {{
            item.addEventListener("click", () => {{
                const tab = item.dataset.tab;
                if (tab === "home" || tab === "team") {{
                    switchTab(tab);
                }}
            }});
        }});

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

        // --- TEAM TAB LOGIC ---
        async function loadTeam() {{
            try {{
                const res = await fetchWithToken("/api/team");
                if (!res.ok) throw new Error("HTTP " + res.status);
                const data = await res.json();
                renderTeam(data);
            }} catch (err) {{
                showFeedback(I18N.load_failed + ": " + err.message, true);
            }}
        }}

        function renderTeam(data) {{
            // 1. Patron select
            const patronSel = document.getElementById("patron-select");
            patronSel.replaceChildren();
            if (data.chiefs) {{
                data.chiefs.forEach(c => {{
                    const opt = document.createElement("option");
                    opt.value = c.name;
                    opt.textContent = c.name;
                    if (c.name === data.patron) opt.selected = true;
                    patronSel.appendChild(opt);
                }});
                const orderText = data.chiefs.map(c => c.name).join(" → ");
                document.getElementById("patron-handoff-order").textContent = orderText;
            }}

            // 2. Workers list
            teamWorkers = data.workers || [];
            renderTeamWorkers();
        }}

        function renderTeamWorkers() {{
            const cont = document.getElementById("team-workers-container");
            cont.replaceChildren();

            if (!teamWorkers || teamWorkers.length === 0) {{
                const empty = document.createElement("div");
                empty.className = "card-subtitle";
                empty.textContent = I18N.team_workers_empty;
                cont.appendChild(empty);
                return;
            }}

            teamWorkers.forEach((w, idx) => {{
                const row = document.createElement("div");
                row.className = "team-worker-row";

                // Left: reorder buttons + name + meta
                const left = document.createElement("div");
                left.className = "team-worker-left";

                const reorderDiv = document.createElement("div");
                reorderDiv.className = "reorder-btns";

                const upBtn = document.createElement("button");
                upBtn.className = "btn-icon";
                upBtn.textContent = "▲";
                upBtn.disabled = (idx === 0);
                upBtn.title = I18N.team_worker_move_up;
                upBtn.addEventListener("click", () => moveWorker(idx, -1));

                const downBtn = document.createElement("button");
                downBtn.className = "btn-icon";
                downBtn.textContent = "▼";
                downBtn.disabled = (idx === teamWorkers.length - 1);
                downBtn.title = I18N.team_worker_move_down;
                downBtn.addEventListener("click", () => moveWorker(idx, 1));

                reorderDiv.appendChild(upBtn);
                reorderDiv.appendChild(downBtn);
                left.appendChild(reorderDiv);

                const info = document.createElement("div");
                info.className = "provider-info";

                const nameDiv = document.createElement("div");
                nameDiv.className = "provider-name";
                nameDiv.textContent = w.name;

                const typeTag = document.createElement("span");
                typeTag.className = "tag " + (w.local ? "tag-local" : "tag-disabled");
                typeTag.textContent = w.type;
                nameDiv.appendChild(typeTag);

                info.appendChild(nameDiv);

                const metaDiv = document.createElement("div");
                metaDiv.className = "provider-meta";

                // Tier select
                const tierLabel = document.createElement("span");
                tierLabel.textContent = I18N.team_worker_tier + ":";
                metaDiv.appendChild(tierLabel);

                const tierSel = document.createElement("select");
                tierSel.className = "select-sm";
                [1, 2, 3].forEach(tVal => {{
                    const opt = document.createElement("option");
                    opt.value = tVal;
                    opt.textContent = tVal;
                    if (w.tier === tVal) opt.selected = true;
                    tierSel.appendChild(opt);
                }});
                tierSel.addEventListener("change", async (e) => {{
                    const newTier = parseInt(e.target.value, 10);
                    try {{
                        const res = await fetchWithToken("/api/team/worker/tier", {{
                            method: "POST",
                            body: JSON.stringify({{ name: w.name, tier: newTier }})
                        }});
                        const data = await res.json();
                        if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
                        const msg = (I18N.team_feedback_tier_saved || "")
                            .replace("{{name}}", w.name)
                            .replace("{{tier}}", newTier);
                        showFeedback(msg);
                        renderTeam(data);
                    }} catch (err) {{
                        showFeedback(I18N.error_prefix + ": " + err.message, true);
                    }}
                }});
                metaDiv.appendChild(tierSel);

                // Model select / display
                if (w.models && w.models.length > 1) {{
                    const modelSel = document.createElement("select");
                    modelSel.className = "select-sm";
                    w.models.forEach(mId => {{
                        const opt = document.createElement("option");
                        opt.value = mId;
                        opt.textContent = mId;
                        if (mId === w.selected_model) opt.selected = true;
                        modelSel.appendChild(opt);
                    }});
                    modelSel.addEventListener("change", async (e) => {{
                        const newModel = e.target.value;
                        try {{
                            const res = await fetchWithToken("/api/team/worker/model", {{
                                method: "POST",
                                body: JSON.stringify({{ name: w.name, model: newModel }})
                            }});
                            const data = await res.json();
                            if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
                            const msg = (I18N.team_feedback_model_saved || "")
                                .replace("{{name}}", w.name)
                                .replace("{{model}}", newModel);
                            showFeedback(msg);
                            renderTeam(data);
                        }} catch (err) {{
                            showFeedback(I18N.error_prefix + ": " + err.message, true);
                        }}
                    }});
                    metaDiv.appendChild(modelSel);
                }} else if (w.selected_model) {{
                    const modelSpan = document.createElement("span");
                    modelSpan.textContent = "· " + w.selected_model;
                    metaDiv.appendChild(modelSpan);
                }}

                info.appendChild(metaDiv);
                left.appendChild(info);

                // Right: toggle + consent + remove
                const right = document.createElement("div");
                right.className = "team-worker-right";

                // Toggle enabled
                const toggleBtn = document.createElement("button");
                toggleBtn.className = "btn btn-sm btn-secondary";
                toggleBtn.textContent = w.enabled ?
                    I18N.team_worker_enabled : I18N.team_worker_disabled;
                toggleBtn.style.opacity = w.enabled ? "1" : "0.7";
                toggleBtn.addEventListener("click", async () => {{
                    try {{
                        const res = await fetchWithToken("/api/team/worker/toggle", {{
                            method: "POST",
                            body: JSON.stringify({{ name: w.name, enabled: !w.enabled }})
                        }});
                        const data = await res.json();
                        if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
                        renderTeam(data);
                    }} catch (err) {{
                        showFeedback(I18N.error_prefix + ": " + err.message, true);
                    }}
                }});
                right.appendChild(toggleBtn);

                // Consent badge & grant button
                if (w.consent_state === "granted") {{
                    const cBadge = document.createElement("span");
                    cBadge.className = "tag tag-ready";
                    cBadge.textContent = I18N.team_worker_consent_granted;
                    right.appendChild(cBadge);
                }} else if (w.consent_state === "missing" || w.consent_state === "changed") {{
                    const cBadge = document.createElement("span");
                    cBadge.className = "tag tag-warn";
                    cBadge.textContent = (w.consent_state === "missing")
                        ? I18N.team_worker_consent_missing
                        : I18N.team_worker_consent_changed;
                    right.appendChild(cBadge);

                    const grantBtn = document.createElement("button");
                    grantBtn.className = "btn btn-sm btn-primary";
                    grantBtn.textContent = I18N.team_worker_consent_grant;
                    grantBtn.addEventListener("click", async () => {{
                        try {{
                            const res = await fetchWithToken("/api/team/consent", {{
                                method: "POST",
                                body: JSON.stringify({{ name: w.name }})
                            }});
                            const data = await res.json();
                            if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
                            const msg = (I18N.team_feedback_consent_granted || "")
                                .replace("{{name}}", w.name);
                            showFeedback(msg);
                            renderTeam(data);
                        }} catch (err) {{
                            showFeedback(I18N.error_prefix + ": " + err.message, true);
                        }}
                    }});
                    right.appendChild(grantBtn);
                }}

                // Remove button
                const rmBtn = document.createElement("button");
                rmBtn.className = "btn btn-sm btn-danger";
                rmBtn.textContent = I18N.team_worker_remove;
                rmBtn.addEventListener("click", async () => {{
                    const confirmMsg = (I18N.team_worker_remove_confirm || "")
                        .replace("{{name}}", w.name);
                    if (!confirm(confirmMsg)) return;
                    try {{
                        const res = await fetchWithToken("/api/team/worker/remove", {{
                            method: "POST",
                            body: JSON.stringify({{ name: w.name }})
                        }});
                        const data = await res.json();
                        if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
                        const msg = (I18N.team_feedback_removed || "")
                            .replace("{{name}}", w.name);
                        showFeedback(msg);
                        renderTeam(data);
                    }} catch (err) {{
                        showFeedback(I18N.error_prefix + ": " + err.message, true);
                    }}
                }});
                right.appendChild(rmBtn);

                row.appendChild(left);
                row.appendChild(right);
                cont.appendChild(row);
            }});
        }}

        async function moveWorker(idx, dir) {{
            const newIdx = idx + dir;
            if (newIdx < 0 || newIdx >= teamWorkers.length) return;
            const names = teamWorkers.map(w => w.name);
            const tmp = names[idx];
            names[idx] = names[newIdx];
            names[newIdx] = tmp;

            try {{
                const res = await fetchWithToken("/api/team/worker/reorder", {{
                    method: "POST",
                    body: JSON.stringify({{ names }})
                }});
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
                showFeedback(I18N.team_feedback_reordered);
                renderTeam(data);
            }} catch (err) {{
                showFeedback(I18N.error_prefix + ": " + err.message, true);
            }}
        }}

        // Patron change listener
        document.getElementById("patron-select").addEventListener("change", async (e) => {{
            const chief = e.target.value;
            try {{
                const res = await fetchWithToken("/api/team/patron", {{
                    method: "POST",
                    body: JSON.stringify({{ chief }})
                }});
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
                const msg = (I18N.team_patron_saved || "").replace("{{name}}", chief);
                showFeedback(msg);
                renderTeam(data);
            }} catch (err) {{
                showFeedback(I18N.error_prefix + ": " + err.message, true);
            }}
        }});

        // Add worker toggling and form logic
        document.getElementById("btn-toggle-add-worker").addEventListener("click", () => {{
            const card = document.getElementById("team-add-card");
            card.style.display = card.style.display === "none" ? "block" : "none";
        }});

        document.getElementById("btn-add-worker-cancel").addEventListener("click", () => {{
            document.getElementById("team-add-card").style.display = "none";
        }});

        document.getElementById("add-worker-type").addEventListener("change", (e) => {{
            const tVal = e.target.value;
            const grpUrl = document.getElementById("add-group-url");
            const grpKey = document.getElementById("add-group-key-env");
            const grpCmd = document.getElementById("add-group-command");
            const urlInput = document.getElementById("add-worker-url");
            const tierSel = document.getElementById("add-worker-tier");

            if (tVal === "ollama") {{
                grpUrl.style.display = "block";
                grpKey.style.display = "none";
                grpCmd.style.display = "none";
                urlInput.value = "http://localhost:11434";
                tierSel.value = "1";
            }} else if (tVal === "openai_compat") {{
                grpUrl.style.display = "block";
                grpKey.style.display = "block";
                grpCmd.style.display = "none";
                urlInput.value = "https://api.example.test/v1";
                tierSel.value = "2";
            }} else if (tVal === "cli_agent") {{
                grpUrl.style.display = "none";
                grpKey.style.display = "none";
                grpCmd.style.display = "block";
                tierSel.value = "3";
            }}
        }});

        document.getElementById("team-add-form").addEventListener("submit", async (e) => {{
            e.preventDefault();
            const tVal = document.getElementById("add-worker-type").value;
            const name = document.getElementById("add-worker-name").value.trim();
            const model = document.getElementById("add-worker-model").value.trim();
            const tier = parseInt(document.getElementById("add-worker-tier").value, 10);
            const base_url = document.getElementById("add-worker-url").value.trim();
            const api_key_env = document.getElementById("add-worker-key-env").value.trim();
            const command = document.getElementById("add-worker-command").value.trim();

            const payload = {{
                type: tVal,
                name: name,
                model: model,
                tier: tier,
                base_url: (tVal !== "cli_agent") ? base_url : null,
                api_key_env: (tVal === "openai_compat" && api_key_env) ? api_key_env : null,
                command: (tVal === "cli_agent" && command) ? command : null,
            }};

            try {{
                const res = await fetchWithToken("/api/team/worker/add", {{
                    method: "POST",
                    body: JSON.stringify(payload)
                }});
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
                document.getElementById("team-add-card").style.display = "none";
                document.getElementById("team-add-form").reset();
                const msg = (I18N.team_add_success || "").replace("{{name}}", name);
                showFeedback(msg);
                renderTeam(data);
            }} catch (err) {{
                showFeedback(I18N.error_prefix + ": " + err.message, true);
            }}
        }});

        // --- DOCTOR & NOTIFY ACTIONS ---
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
