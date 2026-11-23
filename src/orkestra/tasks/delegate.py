"""``orkestra delegate <plan>``: delegate an entire phase to a coding agent (Faz 13r-a, D-128)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from orkestra import paths
from orkestra.config.schema import CliAgentProvider, Config
from orkestra.errors import OrkestraError, UsageError
from orkestra.i18n import t
from orkestra.notify import notify
from orkestra.queue import store as queue_store
from orkestra.routing.router import Route, describe_candidates
from orkestra.state import db, process
from orkestra.tasks import prepare, runner, spec
from orkestra.workspace import git_worktree as gw

DEFAULT_TIMEOUT_S = 3600
DEFAULT_ROUNDS = 5
DEFAULT_PROFILE = "balanced"
LOG_FILE = "queue_runner.log"

RunnerLauncher = Callable[[list[str], Path, Path], Any]


def default_launcher(cmd: list[str], log_path: Path, cwd: Path) -> Any:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log_file:
        kwargs: dict[str, Any] = {
            "cwd": cwd,
            "stdin": subprocess.DEVNULL,
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
        }
        if sys.platform == "win32":
            detached_process = 0x00000008
            create_new_process_group = 0x00000200
            kwargs["creationflags"] = detached_process | create_new_process_group
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(cmd, **kwargs)


@dataclass(frozen=True)
class DelegateResult:
    queue_id: int | None
    task_file: Path
    route: Route
    started_runner: bool
    dry_run: bool = False
    task_spec: spec.TaskSpec | None = None
    notify_ready: bool = True  # a channel can deliver the end-of-run message (D-130)

    @property
    def first_candidate(self) -> str:
        if self.route.candidates:
            return self.route.candidates[0].label
        return "-"

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_id": self.queue_id,
            "task_file": str(self.task_file),
            "candidates": describe_candidates(self.route.candidates),
            "started_runner": self.started_runner,
            "notify_ready": self.notify_ready,
        }


def _rel_path(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def is_delegated(item: queue_store.QueueItem, conn: sqlite3.Connection) -> bool:
    """Is a queue item a task created by ``orkestra delegate``? Its ``delegated`` tag says so,
    in the finished run's ``runs.tags`` or in the task file (no migration; D-129, D-130).
    Where the file lives says nothing: chiefs write their own tasks to ``.orkestra/tasks/``.
    """
    if item.result_ref:
        row = conn.execute("SELECT tags FROM runs WHERE run_id = ?", (item.result_ref,)).fetchone()
        if row and row[0]:
            try:
                tags = json.loads(row[0])
            except ValueError:
                tags = None
            if isinstance(tags, list) and "delegated" in tags:
                return True
    path = Path(item.path)
    if not path.is_file():
        return False
    try:
        data = spec.read_document(path)
    except (OSError, OrkestraError):
        return False
    tags = data.get("tags") if isinstance(data, dict) else None
    return isinstance(tags, list) and "delegated" in tags


def _desktop_installed() -> bool:
    return importlib.util.find_spec("desktop_notifier") is not None


def notify_ready(config: Config) -> bool:
    """Can a channel deliver the message at the end (desktop extra installed, or ntfy)?"""
    if config.notify.ntfy_topic_env and notify.is_variable_name(config.notify.ntfy_topic_env):
        return True
    return config.notify.desktop and _desktop_installed()


def _agent_tier(config: Config, to_provider: str | None, low: int, high: int) -> int | None:
    """The lowest tier a code agent works on inside ``low..high`` (``--to``: that one's)."""
    tiers = [
        cfg.tier for name, cfg in config.providers.items()
        if isinstance(cfg, CliAgentProvider) and cfg.enabled
        and (to_provider is None or name == to_provider) and low <= cfg.tier <= high
    ]  # fmt: skip
    return min(tiers) if tiers else None


def _ignored(where: Path, rels: Sequence[str]) -> set[str]:
    """Paths git ignores (an ignored plan never reaches the worktree); outside a repository
    nothing is checked here, the run itself says it needs one."""
    try:
        gw.repo_root(where)
    except OrkestraError:
        return set()
    return gw.ignored(where, rels)


def _outside_repo(where: Path, rels: Sequence[str]) -> list[str]:
    """Files outside the repository never reach the worker's worktree (B-18, D-140)."""
    try:
        root = gw.repo_root(where)
    except OrkestraError:
        return []  # not a repository: the run itself says it needs one
    return [rel for rel in rels if not (where / rel).resolve().is_relative_to(root)]


def delegate_task(
    plan_path: Path,
    verify_commands: Sequence[str],
    config: Config,
    *,
    config_path: Path | None = None,
    context_files: Sequence[Path] = (),
    to_provider: str | None = None,
    profile: str | None = None,
    timeout_s: int | None = None,
    task_id: str | None = None,
    dry_run: bool = False,
    cwd: Path | None = None,
    conn: sqlite3.Connection | None = None,
    launcher: RunnerLauncher | None = None,
    is_alive: process.Alive = process.process_alive,
    now: db.Clock = db.local_now,
    fix_commands: Sequence[str] = (),
    rounds: int | None = None,
) -> DelegateResult:
    if not verify_commands:
        raise UsageError(t("delegate.error.verify_required"))

    where = (cwd or Path.cwd()).resolve()
    resolved_plan = plan_path if plan_path.is_absolute() else (where / plan_path).resolve()
    if not resolved_plan.is_file():
        raise UsageError(t("delegate.error.plan_not_found", path=resolved_plan))

    tid = task_id.strip() if task_id else resolved_plan.stem
    if not spec._TASK_ID.match(tid):
        raise UsageError(t("task.validation.id", id=tid))

    task_dir = where / ".orkestra" / "tasks"
    target_file = task_dir / f"{tid}.yaml"
    if not dry_run and target_file.exists():
        raise UsageError(t("delegate.error.task_file_exists", path=target_file))

    read_first: list[str] = [_rel_path(resolved_plan, where)]
    for cf in context_files:
        rcf = cf if cf.is_absolute() else (where / cf).resolve()
        if not rcf.is_file():
            raise UsageError(t("delegate.error.plan_not_found", path=rcf))
        read_first.append(_rel_path(rcf, where))
    outside = _outside_repo(where, read_first)
    if outside:
        raise UsageError(t("delegate.error.plan_outside", path=", ".join(outside)))
    hidden = _ignored(where, read_first)
    if hidden:
        raise UsageError(t("delegate.error.plan_ignored", path=", ".join(sorted(hidden))))

    chosen_profile = profile or DEFAULT_PROFILE
    if chosen_profile not in config.profiles:
        raise UsageError(
            t(
                "route.unknown_profile",
                name=chosen_profile,
                available=", ".join(sorted(config.profiles)),
            )
        )
    bounds = config.profiles[chosen_profile]
    tier = _agent_tier(config, to_provider, bounds.min_tier, bounds.max_tier)
    if tier is None:
        raise UsageError(t("delegate.error.no_agent"))

    effective_timeout = timeout_s or DEFAULT_TIMEOUT_S
    effective_rounds = DEFAULT_ROUNDS if rounds is None else rounds
    task_dict: dict[str, Any] = {
        "id": tid,
        "kind": "edit",
        "tier": tier,
        "agents_only": True,
        "on_failover": "continue",
        "prompt": (
            f"Read these files first (do not change them): {', '.join(read_first)}. "
            "Implement the plan exactly as described. Do not go beyond its scope. "
            "Write the tests required by the plan and pass all verifiers."
        ),
        "verify": [
            *(
                {"type": "command", "run": cmd, "timeout_s": effective_timeout}
                for cmd in verify_commands
            ),
            {"type": "protect_paths", "paths": read_first},
        ],
        "limits": {
            "timeout_s": effective_timeout,
            "max_retries": effective_rounds,
        },
        "tags": ["delegated"],
    }
    if fix_commands:
        task_dict["fix"] = [{"run": cmd} for cmd in fix_commands]
    if to_provider is not None:
        task_dict["provider"] = to_provider

    task_spec = spec.parse_task(task_dict, source=str(target_file))

    state_conn = db.connect() if conn is None else conn
    try:
        options = runner.RunOptions(profile=chosen_profile)
        planned = asyncio.run(
            prepare.plan_task(task_spec, config, options, cwd=where, conn=state_conn)
        )
        has_code_agent = any(
            isinstance(c.config, CliAgentProvider) for c in planned.route.candidates
        )
        if not has_code_agent:
            raise UsageError(t("delegate.error.no_agent"))

        if dry_run:
            return DelegateResult(
                queue_id=None,
                task_file=target_file,
                route=planned.route,
                started_runner=False,
                dry_run=True,
                task_spec=task_spec,
                notify_ready=notify_ready(config),
            )

        paths.ensure_project_dir(where)
        task_dir.mkdir(parents=True, exist_ok=True)
        yaml = YAML()
        yaml.default_flow_style = False
        with open(target_file, "w", encoding="utf-8") as f:
            yaml.dump(task_dict, f)

        current_moment = now()
        item = queue_store.add(
            state_conn,
            target_file,
            now=current_moment,
            profile=chosen_profile,
            workdir=where,
        )

        owner = queue_store.lock_owner(state_conn)
        runner_running = owner is not None and is_alive(owner.pid, owner.created)
        started_runner = False
        if not runner_running:
            cmd = [sys.executable, "-m", "orkestra"]
            if config_path is not None:
                cmd.extend(["--config", str(config_path)])
            cmd.extend(["queue", "run", "--notify"])
            log_path = paths.orkestra_home() / LOG_FILE
            launch = launcher or default_launcher
            launch(cmd, log_path, where)
            started_runner = True

        return DelegateResult(
            queue_id=item.id,
            task_file=target_file,
            route=planned.route,
            started_runner=started_runner,
            dry_run=False,
            task_spec=task_spec,
            notify_ready=notify_ready(config),
        )
    finally:
        if conn is None:
            state_conn.close()
