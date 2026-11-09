# Orkestra

[![CI](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml/badge.svg)](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**English** · [Türkçe](README.tr.md)

**A budget-aware CLI that lets one strong "chief" model (e.g. Claude) hand work to many cheaper or local "worker" models, verify the results, and fall back to another provider when one fails.**

> **Status: in development.** Phases 0–4 of 14 are done: the project skeleton, configuration, the Ollama and OpenAI-compatible adapters, `ask`, `doctor`, daily budgets, provider consent, the circuit breaker, secret scanning, and the router with retries and failover. Task files, isolated code edits and the rest are on the [roadmap](#roadmap). This README only describes what already works.

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
| Routing with profiles, privacy and failover; see why each provider was chosen or skipped | `ask [--profile p] [--tier n] [--local-only] [--dry-run]` |
| Environment check: config, provider access, API key variables, Ollama models, consent, paused providers, git, codex/agy | `orkestra doctor [--json] [--warm]` |
| Explicit consent per provider, shown before it is granted | `orkestra providers enable <name>`, `providers disable <name>` |
| Providers with consent, health and remaining budget | `orkestra providers list [--json]` |
| Daily budgets (tokens, USD, requests, runs), reset at local midnight | `orkestra budget [--json]` |
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

# 3. Check everything and allow the providers you want to use
uv run orkestra config validate
uv run orkestra doctor               # --warm also loads each Ollama model
uv run orkestra providers enable ollama
uv run orkestra providers enable openrouter   # shows the URL and key variable, then asks

# 4. Ask
uv run orkestra ask "What does this function do?" --context src/util.py
uv run orkestra ask "Summarize in one line" --provider openrouter --tier 2
uv run orkestra ask "Summarize in one line" --dry-run      # who would answer, and why
uv run orkestra ask "Extract the names" --context people.txt --schema names.schema.json --json
```

`ask` goes through the **router**. It lists every (provider, model) that may run the task, in
this order: tier ascending → `priority` descending → the order you wrote them in the config
(providers first to last, then each provider's models as listed). Use `priority` to override it.
Budgets only filter: a provider that would exceed its limit is left out, but remaining budget
does not reorder. Tiers come from the
profile (`--profile cheap|balanced|quality`, default from the config) and `--tier` sets the lowest
one, so higher tiers act as a fallback.

A provider or model is left out when it:

- is disabled, is a code agent, or its API key variable is not set
- has no consent yet (`orkestra providers enable <name>`), or its settings changed since
- is **paused by the circuit breaker**: 3 network/server errors in a row pause it for 5 minutes, an authentication error for an hour
- is outside the profile's tier range, or its context window is too small for the prompt
- would exceed its daily budget
- is remote while the context contains secrets (API keys, private keys…), or the task is `--local-only`

`orkestra ask "…" --dry-run` prints the order and the reason for every left-out candidate,
without sending anything.

**Failover inside one command.** The candidates are tried in order until one answers:

| Error | What happens |
|---|---|
| No connection at all (offline, DNS, refused) | one quick retry after 0.5 s (network blip), then the next provider |
| Timeout, 5xx, rate limit (429) | retry the same model after 1 s, 2 s, 4 s (+ jitter) or the server's `retry-after`; the third failure pauses the provider and moves on |
| Authentication failed | provider skipped (and paused for an hour) |
| Prompt too long for the model | next model with a bigger context window |
| Empty or broken answer | next candidate |

So with no internet, `ask` answers from local Ollama in the same command, and the remote API is
listed under `failovers` in the envelope. If every candidate fails, the envelope lists all of
them and the exit code is 3.

## Configuration

Orkestra reads a base file and a project file, and the project file wins:

1. Base: `--config <file>` › `$ORKESTRA_CONFIG` › `~/.orkestra/config.yaml`
2. Project: the nearest `orkestra.yaml` from the current directory up to the git root

Mappings are merged deeply, lists are replaced, and `providers.<name>: null` removes a provider.
Unknown keys are rejected so that typos do not pass silently. A `daily_usd` limit is checked
before each request using `price_per_mtok`; without it Orkestra uses the provider's published
price list (OpenRouter, cached for a day) or, failing that, the cost seen in past requests. The full example with comments is
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
  "envelope_version": 2,
  "run_id": "20261109-193405-3679",
  "task_id": "ask",
  "status": "ok",
  "provider": "ollama",
  "model": "qwen2.5-coder:1.5b",
  "tier": 1,
  "attempts": 2,
  "failovers": [
    {"provider": "openrouter", "model": "some/model", "tier": 1,
     "error": "ProviderUnavailable", "reason": "openrouter: cannot connect to …", "attempts": 1}
  ],
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
| 3 | No suitable provider, or every candidate failed (unreachable, paused, budget exhausted, secrets in context, no key, outside the profile) |
| 4 | User consent required (`orkestra providers enable <name>`) |
| 5 | Worktree / apply conflict (Phase 5) |
| 10 | Unexpected internal error |

## Security

- API keys are never stored in config files. Only the environment variable's name is kept there, and `doctor` reports whether the variable is set, never its value.
- Error messages from providers are scrubbed, so a key echoed back by an API (e.g. in a 401 body) does not reach the output.
- `danger-full-access` sandboxing for code agents is rejected by the config.
- No provider is used without explicit consent. Consent is tied to the settings that decide where data goes and what may run (URL, key variable, headers, command, sandbox, model ids), so changing one of them asks again. Turning a provider off and on, or changing its budget or timeouts, does not.
- Context files are scanned for secrets (OpenAI/OpenRouter/AWS/GitHub/Slack/Google keys, private keys, and the values of your configured key variables). Such context never goes to a remote provider unless you pass `--allow-secrets`.
- Everything Orkestra writes to `~/.orkestra/runs/` (request, response, output, envelope, log) is redacted.
- No telemetry. Everything stays on your machine and with the providers you choose.

## Roadmap

| Phase | Topic | Status |
|---|---|---|
| 0 | Skeleton, tooling, i18n foundation | ✅ |
| 1 | Configuration: schema, merge, `init`, `config` | ✅ |
| 2 | Ollama + OpenAI-compatible adapters, `ask`, `doctor` | ✅ |
| 3 | State DB, daily budgets, provider consent, circuit breaker, secret scanning | ✅ |
| 4 | Router, retries and **failover**: offline → local Ollama, failing API → next provider | ✅ |
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
