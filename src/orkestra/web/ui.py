"""The page of the Orkestra web interface (Faz 11c, D-121).

Self-contained: one HTML response with the stylesheet and script inline; no CDN, no fonts.
``assets/index.html`` holds ``[[catalog.key]]`` texts (HTML-escaped here) and ``[[@name]]``
slots; ``assets/app.js`` reads every visible text through ``tr("catalog.key")``, so the page
ships exactly the keys the script uses (``I18N``), never English baked into the script.
"""

from __future__ import annotations

import html
import json
import re
from functools import cache
from importlib import resources

from orkestra import __version__
from orkestra.i18n import get_language, load_catalog, t

# The guide's long form: relative links would hit this server (no token: 403).
REPO_URL = "https://github.com/BurakYildizGameDev/orkestra"

_SLOT = re.compile(r"\[\[(@?[a-z0-9_.]+)\]\]")
_SCRIPT_KEY = re.compile(r'\btr\("([a-z0-9_.]+)"')


@cache
def _asset(name: str) -> str:
    return resources.files("orkestra.web").joinpath("assets", name).read_text(encoding="utf-8")


def _script_keys(script: str) -> list[str]:
    """Keys the script names: ``tr("a.b")`` literally, and every catalog key under a prefix it
    completes at run time (``tr("team.type." + type)``)."""
    english = load_catalog("en")
    keys: list[str] = []
    for key in _SCRIPT_KEY.findall(script):
        matches = sorted(k for k in english if k.startswith(key)) if key.endswith(".") else [key]
        keys.extend(k for k in matches if k not in keys)
    return keys


def _json_for_script(value: object) -> str:
    """JSON that cannot end the ``<script>`` element or start markup."""
    text = json.dumps(value, ensure_ascii=True)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_home_html(token: str) -> str:
    script_source = _asset("app.js")
    catalog = {key: t(key) for key in _script_keys(script_source)}
    script = script_source.replace("__TOKEN__", _json_for_script(token), 1).replace(
        "__I18N__", _json_for_script(catalog), 1
    )
    slots = {
        "@lang": html.escape(get_language()),
        "@version": html.escape(__version__),
        "@guide_url": html.escape(f"{REPO_URL}/blob/main/docs/guide.md"),
        "@guide_tr_url": html.escape(f"{REPO_URL}/blob/main/docs/guide.tr.md"),
        "@css": _asset("app.css"),
        "@script": script,
    }

    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        return slots[name] if name.startswith("@") else html.escape(t(name))

    # One pass over the template only: text put into a slot is never scanned again.
    return _SLOT.sub(fill, _asset("index.html"))
