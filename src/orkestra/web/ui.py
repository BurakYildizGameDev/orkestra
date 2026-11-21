"""HTML/CSS/JS user interface template for Orkestra Web UI (Faz 11c-b).

Self-contained: no external CDN or fonts. Light and dark theme via CSS variables.
"""

from __future__ import annotations

import html

from orkestra import __version__
from orkestra.i18n import t


def render_home_html(token: str) -> str:
    safe_token = html.escape(token)

    return f"""<!DOCTYPE html>
<html lang="en">
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
            padding: 0 0.5rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        .version {{
            font-size: 0.75rem;
            background: #334155;
            padding: 0.15rem 0.4rem;
            border-radius: 4px;
            color: #94a3b8;
        }}
        .nav-list {{ list-style: none; display: flex; flex-direction: column; gap: 0.5rem; }}
        .nav-item a {{
            display: block;
            padding: 0.65rem 0.85rem;
            color: var(--sidebar-text);
            text-decoration: none;
            border-radius: 6px;
            font-weight: 500;
            font-size: 0.95rem;
            transition: all 0.15s ease;
        }}
        .nav-item.active a, .nav-item a:hover {{
            background-color: var(--sidebar-active-bg);
            color: var(--sidebar-active);
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
        .header h1 {{ font-size: 1.75rem; font-weight: 700; }}
        .header-actions {{ display: flex; gap: 0.75rem; }}
        .btn {{
            cursor: pointer;
            border: 1px solid transparent;
            border-radius: 6px;
            padding: 0.55rem 1rem;
            font-size: 0.9rem;
            font-weight: 500;
            transition: background 0.15s ease;
        }}
        .btn-primary {{
            background: var(--btn-bg);
            color: var(--btn-text);
        }}
        .btn-primary:hover {{ background: var(--btn-hover); }}
        .btn-secondary {{
            background: var(--btn-sec-bg);
            color: var(--btn-sec-text);
            border-color: var(--border);
        }}
        .btn-secondary:hover {{ background: var(--btn-sec-hover); }}
        .btn:disabled {{ opacity: 0.6; cursor: not-allowed; }}
        .status-banner {{
            border-radius: 8px;
            padding: 1.25rem;
            margin-bottom: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            border: 1px solid var(--border);
        }}
        .status-banner.status-ok {{
            background: var(--ok-bg);
            color: var(--ok-text);
            border-color: var(--ok-border);
        }}
        .status-banner.status-warn {{
            background: var(--warn-bg);
            color: var(--warn-text);
            border-color: var(--warn-border);
        }}
        .status-banner.status-fail {{
            background: var(--fail-bg);
            color: var(--fail-text);
            border-color: var(--fail-border);
        }}
        .status-title {{ font-size: 1.2rem; font-weight: 700; }}
        .status-next {{ font-size: 0.95rem; opacity: 0.9; }}
        .feedback-banner {{
            margin-bottom: 1.5rem;
            padding: 0.75rem 1rem;
            border-radius: 6px;
            background: var(--btn-sec-bg);
            font-size: 0.9rem;
            display: none;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 1.5rem;
            margin-bottom: 1.5rem;
        }}
        .card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.25rem;
        }}
        .card-title {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 1rem;
            color: var(--text-main);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .card-number {{
            font-size: 2rem;
            font-weight: 700;
            color: var(--text-main);
            margin-bottom: 0.25rem;
        }}
        .card-subtitle {{
            font-size: 0.85rem;
            color: var(--text-muted);
        }}
        .provider-list {{
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }}
        .provider-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem;
            background: var(--bg-page);
            border: 1px solid var(--border);
            border-radius: 6px;
        }}
        .provider-info {{ display: flex; flex-direction: column; gap: 0.2rem; }}
        .provider-name {{ font-weight: 600; font-size: 0.95rem; }}
        .provider-meta {{
            font-size: 0.8rem;
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
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="brand">
            Orkestra
            <span class="version">v{__version__}</span>
        </div>
        <ul class="nav-list">
            <li class="nav-item active"><a href="#home">Ana ekran</a></li>
            <li class="nav-item"><a href="#team">Ekip</a></li>
            <li class="nav-item"><a href="#keys">Anahtarlar</a></li>
            <li class="nav-item"><a href="#usage">Kullanım</a></li>
            <li class="nav-item"><a href="#guide">Nasıl kullanılır</a></li>
            <li class="nav-item"><a href="#advanced">Gelişmiş</a></li>
        </ul>
    </div>
    <div class="main-content">
        <div class="header">
            <h1 id="page-title">Ana ekran</h1>
            <div class="header-actions">
                <button id="btn-test-all" class="btn btn-primary">
                    {t("home.button.test_all")}
                </button>
                <button id="btn-notify-test" class="btn btn-secondary">
                    {t("home.button.notify_test")}
                </button>
            </div>
        </div>

        <div id="feedback" class="feedback-banner"></div>

        <div id="status-card" class="status-banner status-ok">
            <div id="status-text" class="status-title">Yükleniyor…</div>
            <div id="next-step-text" class="status-next"></div>
        </div>

        <div class="grid">
            <div class="card">
                <div class="card-title">Bugün</div>
                <div id="today-runs" class="card-number">0</div>
                <div class="card-subtitle"><span id="today-cost">$0.0000</span> harcama</div>
            </div>
            <div id="claude-card" class="card" style="display: none;">
                <div class="card-title">Claude Kotası</div>
                <div id="claude-content" class="provider-list"></div>
            </div>
            <div class="card">
                <div class="card-title">Bekleyenler</div>
                <div id="unapplied-count" class="card-number">0</div>
                <div id="queue-count" class="card-subtitle">Kuyruk: 0 bekleyen</div>
            </div>
        </div>

        <div class="card">
            <div class="card-title">Sağlayıcılar</div>
            <div id="providers-container" class="provider-list"></div>
        </div>
    </div>

    <script>
        const TOKEN = "{safe_token}";
        const API_BASE = window.location.origin;

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
                showFeedback("Yükleme başarısız: " + err.message, true);
            }}
        }}

        function renderSummary(data) {{
            const card = document.getElementById("status-card");
            card.className = "status-banner status-" + (data.status || "ok");
            document.getElementById("status-text").textContent = data.status_text || "";
            document.getElementById("next-step-text").textContent = data.next_step || "";

            if (data.today) {{
                document.getElementById("today-runs").textContent = data.today.runs + " iş";
                const cost = "$" + (data.today.cost_usd || 0).toFixed(4);
                document.getElementById("today-cost").textContent = cost;
            }}

            if (data.pending) {{
                const unappliedText = data.pending.unapplied_runs + " bekleyen";
                document.getElementById("unapplied-count").textContent = unappliedText;
                document.getElementById("queue-count").textContent =
                    "Kuyruk: " + data.pending.queue_pending + " bekleyen, " +
                    data.pending.queue_running + " çalışan, " +
                    data.pending.queue_failed + " başarısız";
            }}

            if (data.claude_windows && data.claude_windows.length > 0) {{
                const claudeCard = document.getElementById("claude-card");
                claudeCard.style.display = "block";
                const cont = document.getElementById("claude-content");
                cont.innerHTML = data.claude_windows.map(w =>
                    `<div class="provider-row">
                        <span>${{w.label || w.name}}</span>
                        <span class="tag tag-ready">%${{Math.round(w.used)}}</span>
                    </div>`
                ).join("");
            }}

            const pCont = document.getElementById("providers-container");
            if (!data.providers || data.providers.length === 0) {{
                pCont.innerHTML = "<div class='card-subtitle'>Tanımlı sağlayıcı yok.</div>";
            }} else {{
                pCont.innerHTML = data.providers.map(p => {{
                    let docBadge = "";
                    if (p.doctor_status) {{
                        const st = p.doctor_status;
                        const cls = "doc-badge doc-" + st;
                        docBadge = `<span class="${{cls}}">${{st.toUpperCase()}}</span>`;
                    }}
                    const localLabel = p.local_text || "yerel";
                    let localTag = "";
                    if (p.is_local) {{
                        localTag = `<span class="tag tag-local">${{localLabel}}</span>`;
                    }}
                    return `
                    <div class="provider-row">
                        <div class="provider-info">
                            <div class="provider-name">${{p.name}} ${{docBadge}}</div>
                            <div class="provider-meta">
                                <span>${{p.type}}</span>
                                <span>·</span>
                                <span>${{p.limits_text || ""}}</span>
                            </div>
                        </div>
                        <div style="display: flex; gap: 0.5rem; align-items: center;">
                            ${{localTag}}
                            <span class="tag tag-${{p.status}}">${{p.status_text}}</span>
                        </div>
                    </div>`;
                }}).join("");
            }}
        }}

        document.getElementById("btn-test-all").addEventListener("click", async () => {{
            const btn = document.getElementById("btn-test-all");
            btn.disabled = true;
            showFeedback("{t("home.doctor.running")}");
            try {{
                await fetchWithToken("/api/doctor", {{ method: "POST" }});
                const poll = setInterval(async () => {{
                    const res = await fetchWithToken("/api/doctor");
                    if (res.ok) {{
                        const docData = await res.json();
                        if (docData.status === "done") {{
                            clearInterval(poll);
                            btn.disabled = false;
                            showFeedback("Test tamamlandı.");
                            loadHome();
                        }}
                    }}
                }}, 1000);
            }} catch (err) {{
                btn.disabled = false;
                showFeedback("Test başlatılamadı: " + err.message, true);
            }}
        }});

        document.getElementById("btn-notify-test").addEventListener("click", async () => {{
            const btn = document.getElementById("btn-notify-test");
            btn.disabled = true;
            showFeedback("Bildirim gönderiliyor…");
            try {{
                const res = await fetchWithToken("/api/notify/test", {{ method: "POST" }});
                const data = await res.json();
                btn.disabled = false;
                if (data.lines && data.lines.length > 0) {{
                    showFeedback(data.lines.join(" · "));
                }} else {{
                    showFeedback("Bildirim gönderildi.");
                }}
            }} catch (err) {{
                btn.disabled = false;
                showFeedback("Bildirim hatası: " + err.message, true);
            }}
        }});

        loadHome();
    </script>
</body>
</html>
"""
