# Orkestra

[![CI](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml/badge.svg)](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**English** · [Türkçe](README.tr.md)

**A budget-aware CLI that lets one strong "chief" model (e.g. Claude) hand work to many cheaper or local "worker" models, verify the results, and keep working on another provider when one fails or runs out of quota.**

> **Status: early release, in development.** Everything in the table below works and is
> covered by about 1,900 offline tests on Linux, macOS and Windows, but it has seen little
> real-world use yet. It is not on PyPI yet. Measured: handing a **whole phase** to a code
> agent (`orkestra delegate`) and reviewing it in a fresh session cost the chief ~68% fewer
> tokens per line; handing over small tasks does **not** save tokens, and the context filter
> cuts a big job's cost by ~20%. Read [Known limits](#known-limits) before you rely on it. What is done and what is next:
> [Roadmap](#roadmap).

```text
You ──► Claude (chief: plans, splits, reviews)
            │
            ▼
        Orkestra ──► router (tier + budget + health + quota)
            │
   ┌────────┼──────────────┬───────────────┐
   ▼        ▼              ▼               ▼
 Ollama  OpenRouter    Codex CLI     Antigravity CLI
 (local) (API)         (code agent)  (code agent)
            │
            ▼
   verification ──► short result envelope (JSON) ──► the chief reads only this
```

## Why

Strong models have small quotas; models with big quotas are less reliable. Orkestra does two
things about it:

- **Keeps the work going.** When a provider is down, offline, out of budget or out of quota,
  the next one takes over in the same command, and the exhausted one is paused until it resets.
  A whole session can be handed from one chief to another (Claude → Codex → Antigravity).
- **Keeps the chief's context small.** Bulky, easy-to-check work (summaries, docstrings, tests,
  data extraction, mechanical refactors, long command output) goes to cheap or local models.
  The output is checked automatically and the chief gets a short JSON envelope instead.

## What works today

| Feature | Command |
|---|---|
| Setup wizard (finds Ollama, Codex/agy/Claude and API key variables) or the example config | `orkestra init [--plain \| --defaults] [--project]` |
| Web interface: home, team, keys (keyring), usage charts, guide, advanced settings | `orkestra ui [--window]` |
| Terminal interface: status, providers, budgets, profiles, consent, night queue, handoff brief, settings | `orkestra ui --tui` |
| Add any OpenAI-compatible service, or import one from OpenCode | `orkestra providers add NAME --base-url URL --model ID`, `providers import opencode` |
| Explicit consent per provider; providers with health and remaining budget | `orkestra providers enable NAME`, `providers list` |
| One question to a worker, with context files and an optional JSON Schema | `orkestra ask "…" [--context f] [--schema s.json] [--json]` |
| Routing by tier, budget, health, quota, kind of work and past success; see why each candidate was chosen or skipped | `ask … --dry-run`, `routing.by_kind`, `routing.adaptive` |
| Failover in the same command; a provider out of quota is paused until it resets | see [When an AI runs out](docs/guide.md#when-an-ai-runs-out) |
| Task files: verify the answer, retry with feedback, move up a tier | `orkestra run task.yaml [--json]` |
| Edit tasks: a worker changes code in an isolated git worktree, your tests decide | `orkestra run edit.yaml`, `show RUN_ID --diff`, `apply RUN_ID`, `discard RUN_ID` |
| Code agents (Codex CLI, Antigravity) as workers, in the worktree | `cli_agent` providers |
| Hand a whole phase to a code agent in the background: your plan in, your tests decide, another agent continues if one stops, a notification at the end | `orkestra delegate PLAN.md --verify "pytest -q"` |
| Batches with dependencies, in parallel; cost estimate first; apply the passing runs | `orkestra batch tasks.yaml [--estimate]`, `apply --batch ID --only-ok` |
| Task templates (docstring, type hints, tests, summary, rename, translate, your own) | `orkestra run --template docstring --files "src/*.py"`, `templates list` |
| A second AI reviews a worker's change; apply only the low-risk ones | `orkestra review RUN_ID`, `apply RUN_ID --max-risk low` |
| Long command output for the chief: test/lint findings with `file:line`, the rest summarised | `orkestra exec -- pytest` |
| A worker reads files or search hits and answers with checked `file:line` pointers | `orkestra read FILE "question"`, `orkestra find PATTERN` |
| Where Claude Code's tokens go (reads its transcripts, uses no quota); per phase against git history | `orkestra tokens [--since 7d]`, `tokens --compare` |
| The chief's view at a glance (at most 15 lines) | `orkestra status` |
| Handoff file and brief for the next chief; hand over to another one | `orkestra handoff init`, `handoff show --brief`, `handoff to codex` |
| Night queue: add now, run later on local models; stop at a set hour or cost | `orkestra queue add FILE`, `queue run --until 07:00 --notify`, `queue remove --finished` |
| Notifications when a batch or the queue ends: desktop and phone (ntfy, also self-hosted) | `--notify`, `orkestra notify test` |
| How the workers did: success rate, attempts, tokens, cost and time | `orkestra stats [--since 7d]` |
| Daily budgets (tokens, USD, requests, runs), reset at local midnight | `orkestra budget` |
| Environment check: config, providers, keys, models, consent, quota, git, install | `orkestra doctor [--warm]` |
| Clean up old worktrees, run records, database rows and stale reservations | `orkestra gc [--dry-run]` |
| Claude skill: when and how Claude delegates to Orkestra | [`skill/orkestra/SKILL.md`](skill/orkestra/SKILL.md) |
| Interface in English, Turkish, German, Spanish or French | `--lang en\|tr\|de\|es\|fr`, `ORKESTRA_LANG` |

**Providers:**

- **Ollama** through its native API (`num_ctx` is sent every time, so long prompts are never cut silently).
- **Any OpenAI-compatible API**: OpenRouter, LM Studio, vLLM, your own server (`providers add`). OpenRouter's reported cost is read; elsewhere the cost comes from `price_per_mtok`.
- **Code agents** as `cli_agent` providers: Codex CLI, Antigravity (`agy`, experimental: its CLI still changes), or any other command-line agent (`generic`).

## Install

Requirements: Python 3.11+, git, [uv](https://docs.astral.sh/uv/). Optional: Ollama, an API key
(OpenRouter or another OpenAI-compatible service), Codex CLI or Antigravity.

```bash
uv tool install git+https://github.com/BurakYildizGameDev/orkestra
# with desktop notifications:
uv tool install git+https://github.com/BurakYildizGameDev/orkestra --with "desktop-notifier>=6.0,<7"
orkestra --help
```

Not on PyPI yet (planned as `orkestra-cli`). From a clone, `uv sync` and `uv run orkestra --help` work
too. If you install a clone with `uv tool install --editable .`, the `orkestra` command runs
whatever branch that clone has checked out: keep it on `main` (`orkestra doctor` warns otherwise).

## Quick start

```bash
# 1. API keys go into environment variables; the config holds only the variable's NAME.
export OPENROUTER_API_KEY="..."      # PowerShell: $env:OPENROUTER_API_KEY="..."

# 2. Set up ~/.orkestra/config.yaml: the wizard finds Ollama and its models, codex/agy/claude
#    and which key variables exist (never their values), then asks providers, tiers, budgets
#    and consent. Your comments in an existing file are kept.
orkestra init                        # --plain: the same questions; --project: ./orkestra.yaml

# 3. Check everything and allow the providers you want to use
orkestra doctor
orkestra providers enable ollama
orkestra providers enable openrouter    # shows the URL and key variable, then asks

# 4. Ask; see who would answer and why
orkestra ask "What does this function do?" --context src/util.py
orkestra ask "Summarize in one line" --dry-run

# 5. Or write the task down, with checks, and run it
orkestra run examples/tasks/summarize-readme.yaml --json
```

Each provider has a **tier** (1 small/free … 3 strongest). The router tries the lowest tier the
profile allows first and keeps higher tiers as the fallback. A provider is skipped when it is
disabled, has no consent, is paused, is over its daily budget, or is remote while the context
contains secrets. With no internet, `ask` answers from local Ollama in the same command. The
whole story: [Routing and failover](docs/guide.md#routing-and-failover).

To let Claude use Orkestra, install the skill:

```bash
mkdir -p ~/.claude/skills && cp -r skill/orkestra ~/.claude/skills/
```

## Known limits

- **Only handing over a whole phase saves Claude tokens; the context filter does a little.** Benchmark
  (Faz 13, Claude Code 2.1.329 with Opus 5.5, Windows 11, i9-13900HX, 32 GB, RTX 5070 Ti 12 GB;
  details in [`bench/README.md`](bench/README.md#results)):

  | Run | Passed | Claude tokens / task | Claude cost / task |
  |---|---|---|---|
  | 20 small tasks, Claude only (2 rounds) | 20/20 | 9.1k | $0.117 |
  | the same with the skill (Claude chose never to delegate) | 20/20 | 11.4k (+26%) | $0.136 (+16%) |
  | the same, told to delegate to agy (1 round) | 20/20 | 15.7k (+73%) | $0.197 (+68%) |
  | Orkestra alone, local qwen2.5-coder:14b, no chief | 7.5/20 | – | – |
  | big task (~1,200-line project, 160 KB log), Claude only (2 rounds) | 2/2 | 87.4k | $1.38 |
  | the same with the context filter (`exec`/`read`/`find`) | 2/2 | 76.9k (−12%) | $1.10 (−20%) |
  | the same plus delegation and cross-review | 2/2 | 76.7k (−12%) | $1.19 (−13%) |

  On these tasks the 25% saving the project aimed for was not reached: delegating small tasks,
  or pieces of a big task inside one session, costs the chief more than it saves. What did save
  was handing a **whole phase** to a code agent with `orkestra delegate` and having Claude
  review it in a fresh session: ~0.85M weighted Claude tokens per 1,000 added lines, against
  ~2.65M for the phases Claude wrote itself (~68% less; measured on this repository with
  `orkestra tokens --compare`, a rough measure, since the lines include tests and docs).
  Orkestra also gives continuity (another provider or chief takes over when one runs out) and
  a context filter (−46% context re-reading on the big task).
- **Delegated work stops while the computer sleeps.** Turn sleep off for long
  `orkestra delegate` runs.
- **Little real-world use.** The night queue, notifications, the terminal interface and the
  wizard are covered by tests but have had little use on real models and real terminals. The
  code was written and reviewed with AI help. Expect rough edges and please
  [report them](https://github.com/BurakYildizGameDev/orkestra/issues).
- **Learned routing needs data.** `routing.adaptive` reorders a tier only after `min_samples`
  runs (default 10) of the same tag; before that it is neutral.
- **Antigravity (`agy`) support is experimental**: its CLI and its output still change.
- **Local models load your computer.** Only one heavy local model runs at a time, across
  terminals; `doctor` suggests model sizes for your RAM/GPU.
- **Translations:** German, Spanish and French were translated with AI and not yet reviewed by
  native speakers.
- **Not on PyPI yet.** v0.9.0 is the first numbered release, on GitHub (see the roadmap).

## Security

- API keys are never stored in config files, only the environment variable's name; `doctor` says whether it is set, never its value.
- Errors from providers are scrubbed, so a key echoed back by an API does not reach the output.
- No provider is used without explicit consent, tied to where data goes and what may run (URL, key variable, headers, command, sandbox, models); changing one of them asks again.
- Context and prompts are scanned for secrets; such context never goes to a remote provider unless you pass `--allow-secrets`. Files matched by `.orkestraignore` are never sent.
- Everything written to `~/.orkestra/runs/` is redacted. `danger-full-access` sandboxing for code agents is rejected.
- A `command` verifier runs a command you wrote, in your working directory; a shell only with `shell: true`.
- No telemetry. Everything stays on your machine and with the providers you choose.

## Documentation

- [Guide](docs/guide.md): routing and failover, task files, edits, code agents, quota and
  continuity, batches, the night queue, chief tools, cross-review, `exec`/`read`/`find`, token
  map, configuration, the result envelope and exit codes.
- [Recipes](docs/recipes.md): ready-made workflows.
- [Example config](examples/orkestra.example.yaml) and [example tasks](examples/tasks/).
- [`docs/PROGRESS.md`](docs/PROGRESS.md): what each phase did; [`docs/DECISIONS.md`](docs/DECISIONS.md): every deviation from the plan, with its reason.

## Roadmap

| Phase | Topic | Status |
|---|---|---|
| 0–4 | Skeleton, config, Ollama/OpenAI adapters, budgets, consent, circuit breaker, router with failover | ✅ |
| 5–6 | Task files and verifiers, worktrees, edit tasks, code agents (Codex, Antigravity) | ✅ |
| 6b | MCP limits: a stalled MCP server no longer blocks agy; `doctor --mcp` | ✅ |
| 7–8 | Batches, cost estimates, `stats`; chief tools (`status`, templates, cache, `review`, `map`) | ✅ |
| 9 | Claude skill; SEARCH/REPLACE edits for cheap models | ✅ |
| 10 | Chief handoff (Claude ↔ Codex ↔ Antigravity) | ✅ |
| 11 | Terminal interface, setup wizard, 5 languages | ✅ |
| 11c | Web interface | ✅ |
| 12 | Night queue, notifications, adaptive routing | ✅ |
| 13a–e, 13g, 13p | Benchmark tool, 20 tasks, full rounds, the big-task experiment, a short skill | ✅ |
| 13f–o | Quota continuity, token map, context filter (`exec`/`read`/`find`), short sessions, quota forecast, model by kind of work, cross-review, non-Claude chief, `providers add` | ✅ |
| 13q–r | Speed awareness; hand a whole phase to a code agent (`delegate`), another agent continues when one stops; `tokens --compare` | ✅ |
| fixes | `gc` database cleanup, file splits and this README are done; a manual usage tour on real models is next | ⏳ |
| 14 | Packaging, docs, PyPI release | ⏳ |

## Development

```bash
uv sync
uv run pytest                 # offline; real services only with: uv run pytest -m live
uv run ruff check . && uv run ruff format --check .
uv run pyright
```

CI runs on Linux, macOS and Windows with Python 3.11, 3.12 and 3.13. Rules for coding agents
working on this repo are in [`AGENTS.md`](AGENTS.md).

## License

[MIT](LICENSE)
