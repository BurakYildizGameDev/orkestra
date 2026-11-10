# Orkestra

[![CI](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml/badge.svg)](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**English** · [Türkçe](README.tr.md)

**A budget-aware CLI that lets one strong "chief" model (e.g. Claude) hand work to many cheaper or local "worker" models, verify the results, and fall back to another provider when one fails.**

> **Status: in development.** Phases 0–2 of 14 are done: the project skeleton, configuration, the Ollama and OpenAI-compatible adapters, `ask` and `doctor`. Routing, budgets, failover, isolated code edits and the rest are on the [roadmap](#roadmap). This README only describes what already works.

```
You ──► Claude (chief: plans, splits, reviews)
            │
            ▼
        orkestra ──► router (tier + budget + health)      ← Phase 3–4
            │
   ┌────────┼──────────────┬───────────────┐
   ▼        ▼              ▼               ▼
 Ollama  OpenRouter    Codex CLI     Antigravity CLI
 (local) (API)         (code agent)  (code agent)          ← Phase 6
            │
            ▼
   verification ──► short result envelope (JSON) ──► the chief reads only this
```

## Why

Strong models have small quotas; models with big quotas are less reliable. Orkestra sends bulky,
easy-to-check work (summaries, docstrings, tests, data extraction, mechanical refactors) to cheap
or local models, checks the output automatically, and gives the chief a short JSON envelope instead
of the whole output. When a provider is down, out of budget or offline, the next one takes over.

## What works today

| Feature | Command |
|---|---|
| Example config, global or per project | `orkestra init [--project] [--force]` |
| Merged config with its sources, validation with readable errors | `orkestra config show [--json]`, `orkestra config validate` |
| One question to a worker model, with context files and an optional JSON Schema | `orkestra ask "…" [--context f] [--schema s.json] [--json]` |
| Environment check: config, provider access, API key variables, Ollama models, git, codex/agy | `orkestra doctor [--json] [--warm]` |
| Interface in English or Turkish | `--lang en\|tr`, `ORKESTRA_LANG`, or `language:` in the config |

Providers supported so far:

- **Ollama** through its native `/api/chat` API. `num_ctx` is sent on every request, so long prompts are never cut silently (Ollama's OpenAI-compatible endpoint ignores it).
- **Any OpenAI-compatible API**: OpenRouter, LM Studio, vLLM, your own server. OpenRouter's reported cost (`usage.cost`) is read; for other providers the cost comes from `price_per_mtok`.

## Install

Requirements: Python 3.11+, git, [uv](https://docs.astral.sh/uv/). Optional: Ollama, an OpenRouter key.

```bash
git clone https://github.com/BurakYildizGameDev/orkestra
cd orkestra
uv sync
uv run orkestra --help
```

The package will be published on PyPI as `orkestra-cli`; the command is `orkestra`.

## Quick start

```bash
# 1. Create a config from the example (~/.orkestra/config.yaml)
uv run orkestra init                 # or: init --project → ./orkestra.yaml

# 2. Edit the config: keep the providers you use, set your model names.
#    API keys go into environment variables. The config holds only the variable's NAME.
export OPENROUTER_API_KEY="..."      # PowerShell: $env:OPENROUTER_API_KEY="..."

# 3. Check everything
uv run orkestra config validate
uv run orkestra doctor               # --warm also loads each Ollama model

# 4. Ask
uv run orkestra ask "What does this function do?" --context src/util.py
uv run orkestra ask "Summarize in one line" --provider openrouter --tier 2
uv run orkestra ask "Extract the names" --context people.txt --schema names.schema.json --json
```

Without `--provider`/`--model`, `ask` picks the first enabled provider that has a model on the
requested tier (default 1), in config order. Providers that are disabled, are code agents, or have
no API key in the environment are skipped, and the reasons are listed if nothing is left.

## Configuration

Orkestra reads a base file and a project file, and the project file wins:

1. Base: `--config <file>` › `$ORKESTRA_CONFIG` › `~/.orkestra/config.yaml`
2. Project: the nearest `orkestra.yaml` from the current directory up to the git root

Mappings are merged deeply, lists are replaced, and `providers.<name>: null` removes a provider.
Unknown keys are rejected so that typos do not pass silently. The full example with comments is
[`examples/orkestra.example.yaml`](examples/orkestra.example.yaml).

```yaml
version: 1
language: auto                 # auto | en | tr

providers:
  ollama:
    type: ollama
    models:
      - id: qwen2.5-coder:14b
        tier: 1
        context_window: 32768  # sent to Ollama as num_ctx
  openrouter:
    type: openai_compat
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY   # the variable's NAME, never the key
    models:
      - id: provider/model-name
        tier: 2
    budget:
      daily_usd: 2.00
```

Errors point at the exact field, in the selected language:

```
Error: Invalid configuration (~/.orkestra/config.yaml):
  - providers.openrouter.models[0].tier: must be 1, 2 or 3
  - providers.codex.sandbox: 'danger-full-access' is not supported; use 'read-only' or 'workspace-write'
```

## Result envelope and exit codes

With `--json`, stdout contains exactly one JSON document and everything else goes to stderr. For
`ask`, the document is the result envelope. The full answer stays on disk in
`~/.orkestra/runs/<run_id>/`, together with the request, the response and the task.

```json
{
  "envelope_version": 1,
  "run_id": "20261109-193405-3679",
  "task_id": "ask",
  "status": "ok",
  "provider": "ollama",
  "model": "qwen2.5-coder:1.5b",
  "tier": 1,
  "attempts": 1,
  "summary": "4",
  "verification": [],
  "output_path": "~/.orkestra/runs/20261109-193405-3679/output.md",
  "usage": {"prompt_tokens": 142, "completion_tokens": 2, "cost_usd": 0.0},
  "duration_s": 0.375,
  "error": null
}
```

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 1 | Verification failed (e.g. the answer does not match `--schema`); for `doctor`: a check failed |
| 2 | Configuration or usage error |
| 3 | No suitable provider (unreachable, auth failed, no key, no model on that tier) |
| 4 | User consent required (Phase 3) |
| 5 | Worktree / apply conflict (Phase 5) |
| 10 | Unexpected internal error |

## Security

- API keys are never stored in config files. Only the environment variable's name is kept there, and `doctor` reports whether the variable is set, never its value.
- Error messages from providers are scrubbed, so a key echoed back by an API (e.g. in a 401 body) does not reach the output.
- `danger-full-access` sandboxing for code agents is rejected by the config.
- No telemetry. Everything stays on your machine and with the providers you choose.

## Roadmap

| Phase | Topic | Status |
|---|---|---|
| 0 | Skeleton, tooling, i18n foundation | ✅ |
| 1 | Configuration: schema, merge, `init`, `config` | ✅ |
| 2 | Ollama + OpenAI-compatible adapters, `ask`, `doctor` | ✅ |
| 3 | State DB, daily budgets, provider consent, circuit breaker, secret scanning | ⏳ |
| 4 | Router, retries and **failover**: offline → local Ollama, failing API → next provider | ⏳ |
| 5 | Task files, verifiers, git worktrees, `edit`, `apply` | ⏳ |
| 6 | Code agents: Codex CLI, Antigravity CLI | ⏳ |
| 7 | Batch runs, parallelism, cost estimate | ⏳ |
| 8 | Chief tools: `status`, `review`, `map`, templates, `plan expand`, cache, savings counter | ⏳ |
| 9 | Claude skill | ⏳ |
| 10 | Chief handoff (Claude ↔ Codex ↔ Antigravity) | ⏳ |
| 11 | Terminal UI, setup wizard, 5 languages | ⏳ |
| 12 | Night shift queue, notifications, adaptive routing | ⏳ |
| 13 | Benchmark (with the bad results too) | ⏳ |
| 14 | Packaging, docs, PyPI release | ⏳ |

Progress notes are in [`docs/PROGRESS.md`](docs/PROGRESS.md). Every deviation from the plan, with
its reason, is in [`docs/DECISIONS.md`](docs/DECISIONS.md).

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
