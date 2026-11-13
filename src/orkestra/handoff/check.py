"""The ``handoff check`` service: one place decides what a stale file warns about (GLM B5).

``cli.py`` only calls ``run`` and prints the result, so the warning wording and the order of
the checks cannot drift between ``handoff check``, ``status`` and the brief.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orkestra.config.schema import Config
from orkestra.handoff import brief, model, store
from orkestra.i18n import t

CHECK_WARNING_KEYS: dict[str, str] = {
    "no_git": "handoff.check.no_git",
    "unknown_commit": "handoff.check.unknown_commit",
    "stale": "handoff.check.stale",
}


@dataclass(frozen=True)
class CheckResult:
    exists: bool
    stale: bool
    warnings: list[str]
    state: brief.Staleness | None


def run(path: Path, config: Config, cwd: Path, git: brief.Git | None = None) -> CheckResult:
    """Check the handoff file; a missing file is a warning, not an error."""
    if not path.exists():
        return CheckResult(False, False, [t("handoff.check.missing")], None)
    document = model.parse(store.read(path))
    state = brief.staleness(document, config, cwd, brief.default_git if git is None else git)
    warnings = brief.warning_lines(state, CHECK_WARNING_KEYS)
    return CheckResult(True, bool(state is not None and state.stale), warnings, state)
