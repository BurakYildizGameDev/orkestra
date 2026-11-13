"""Check one translation catalog against en.yaml; the verifier of the translation tasks.

Run as ``python tests/fixtures/check_catalog.py de`` from the repository root (or a worktree).
Exit 0 when the catalog has exactly the English keys, the same ``{placeholders}`` in every
value, no empty value, formats cleanly, and is really translated; otherwise every problem is
printed (a worker reads this as feedback) and the exit code is 1.
"""

from __future__ import annotations

import sys
from pathlib import Path
from string import Formatter

from ruamel.yaml import YAML

LOCALES = Path("src/orkestra/i18n/locales")


def _load(lang: str) -> dict[str, str]:
    data = YAML(typ="safe").load((LOCALES / f"{lang}.yaml").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{lang}.yaml is not a mapping")
    return {str(key): str(value) for key, value in data.items()}


def _fields(text: str) -> set[str]:
    return {field for _, field, _, _ in Formatter().parse(text) if field is not None}


def problems(lang: str) -> list[str]:
    english = _load("en")
    catalog = _load(lang)
    found: list[str] = []
    for key in sorted(set(english) - set(catalog)):
        found.append(f"missing key: {key}")
    for key in sorted(set(catalog) - set(english)):
        found.append(f"extra key (not in en.yaml): {key}")
    for key, text in catalog.items():
        if key not in english:
            continue
        if not text.strip():
            found.append(f"empty value: {key}")
            continue
        try:
            fields = _fields(text)
            text.format(**{field: "x" for field in fields})
        except (ValueError, KeyError, IndexError) as exc:
            found.append(f"does not format ({exc}): {key}")
            continue
        if fields != _fields(english[key]):
            wanted = sorted(_fields(english[key]))
            found.append(f"placeholders differ: {key}: {sorted(fields)} != {wanted}")
    prose = [key for key, text in english.items() if len(text.split()) >= 4 and key in catalog]
    copied = [key for key in prose if catalog[key] == english[key]]
    if len(copied) > len(prose) // 20:
        found.append(
            f"{len(copied)} of {len(prose)} sentences are still English, e.g. {copied[:5]}"
        )
    return found


def main() -> int:
    lang = sys.argv[1]
    found = problems(lang)
    for line in found:
        print(line)
    if not found:
        print(f"{lang}.yaml: ok")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
