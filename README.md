# Orkestra

[![CI](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml/badge.svg)](https://github.com/BurakYildizGameDev/orkestra/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**English** · [Türkçe](README.tr.md)

**A budget-aware CLI that lets one strong "chief" model (e.g. Claude) hand work to many cheaper or local "worker" models, verify the results, and fall back to another provider when one fails.**

> **Status: in development.** Phases 0–4 of 14 and the first two parts of phase 5 are done: the project skeleton, configuration, the Ollama and OpenAI-compatible adapters, `ask`, `doctor`, daily budgets, provider consent, the circuit breaker, secret scanning, the router with retries and failover, task files with verification, feedback retries and escalation, and isolated git worktrees with `show`, `apply`, `discard` and `gc`. Edit tasks that let workers change code (in those worktrees) and the rest are on the [roadmap](#roadmap). This README only describes what already works.

```
You ──► Claude (chief: plans, splits, reviews)
            │
            ▼
        orkestra ──► router (tier + budget + health)      ← Phase 3–4
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
| Task files (YAML/JSON): verify the answer, retry with feedback, move up a tier | `orkestra run task.yaml [--dry-run] [--json]` |
| Edit tasks: a worker changes code in an isolated worktree, your tests decide | `orkestra run edit.yaml`, then `show --diff`, `apply` |
| Batches: many tasks with dependencies, in parallel, each provider within its concurrency | `orkestra batch tasks.yaml [--parallel N] [--fail-fast] [--json]` |
| Code agents (Codex CLI, Antigravity) as workers, in the worktree, with process-tree cleanup | `cli_agent` providers |
| A run's envelope, full output, log or change | `orkestra show <run_id> [--output\|--log\|--diff] [--json]` |
| Bring a run's change into your working tree, or throw it away | `orkestra apply <run_id>`, `orkestra discard <run_id>` |
| Clean up abandoned worktrees, old run records and stale reservations | `orkestra gc [--older-than 30] [--dry-run]` |
| Environment check: config, provider access, API key variables, Ollama models, consent, paused providers, git, codex/agy | `orkestra doctor [--json] [--warm]` |
| Explicit consent per provider, shown before it is granted | `orkestra providers enable <name>`, `providers disable <name>` |
| Providers with consent, health and remaining budget | `orkestra providers list [--json]` |
| Daily budgets (tokens, USD, requests, runs), reset at local midnight | `orkestra budget [--json]` |
| Claude skill: when and how Claude delegates to Orkestra | `skill/orkestra/SKILL.md` |
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

# 5. Or write the task down, with checks, and run it
uv run orkestra run examples/tasks/summarize-readme.yaml --json
```

`ask` goes through the **router**. It lists every (provider, model) that may run the task, in
this order: tier ascending → `priority` descending → the order you wrote them in the config
(providers first to last, then each provider's models as listed). Use `priority` to override it.
Budgets only filter: a provider that would exceed its limit is left out, but remaining budget
does not reorder. Tiers come from the
profile (`--profile cheap|balanced|quality`, default from the config) and `--tier` sets the lowest
one, so higher tiers act as a fallback.

A provider or model is left out when it:

- is disabled, or its API key variable is not set (a code agent: its program is not installed)
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
| Authentication failed | provider skipped (and paused for an hour; `providers enable` resumes it) |
| Model not found (404) | next model; the provider's other models are still tried |
| Prompt too long for the model | next model with a bigger context window |
| Empty or broken answer | next candidate |
| The model answers `CANNOT_DO: <reason>` | next candidate on a higher tier; none left → status `escalate`, exit code 1 |

A timed-out request counts against the daily budget with its estimate (the provider may have
billed it); retries and failovers count as one run per provider for `daily_runs`.

So with no internet, `ask` answers from local Ollama in the same command, and the remote API is
listed under `failovers` in the envelope. If every candidate fails, the envelope lists all of
them and the exit code is 3.

## Task files and verification

A task file describes one job and how to check the result. `orkestra ask` builds the same kind of
task from its options. See [`examples/tasks/`](examples/tasks/).

```yaml
id: summarize-readme
kind: ask                    # ask | edit (see "Edit tasks" below)
tier: 1                      # lowest tier to start on
prompt: |
  Summarize what this project does in one sentence and list its key features.
context:
  files: [README.md]
  globs: []                  # e.g. ["src/**/*.py"]; .gitignore and .orkestraignore apply
output:
  format: json               # text | json
  schema: summary.schema.json
verify:
  - type: regex
    must_not_match: ["(?i)lorem ipsum"]
  - type: command            # your own check; exit code 0 passes
    run: "python check_summary.py"
    timeout_s: 60
limits:
  max_retries: 1             # retries with feedback per model (default: defaults.max_retries)
  timeout_s: 120             # per request (default: the provider's timeout)
privacy: normal              # local_only keeps the task on local models
tags: [docs]
```

Relative paths are resolved from the directory you run `orkestra` in, or from `workspace` if
the task sets one.

**Verifiers:** `command` (exit code 0; no shell unless `shell: true`, which pipes and `&&` need),
`json_schema` (added automatically for `format: json`), `regex` (`must_match`, `must_not_match`),
`files_exist`, and for code changes `max_changed_files`, `max_diff_lines`, `protect_paths`,
`forbid_paths` (they pass trivially for `ask` tasks, which change nothing).

**What happens when a check fails:**

1. The same model gets its previous answer and the failed checks back (in English) and tries
   again, up to `max_retries` times.
2. If it keeps failing, or answers `CANNOT_DO: <reason>`, the run moves up to the next tier and
   skips the other candidates on the same tier. The move is listed under `escalations`.
3. If no answer passes: `status: failed`, or `escalate` when tier 3 failed too (the chief has to
   take over). Exit code 1. The last answer is still kept in `output.md`.

Every attempt's request, response and check log (`verify.log`) is kept in
`~/.orkestra/runs/<run_id>/attempts/<n>/`.

## Edit tasks: workers change code

An edit task asks a worker to change files. It runs in a worktree (see below), so your checkout
stays as it is until you apply the result.

```yaml
id: fix-add
kind: edit
prompt: Fix add() in calc.py so that the tests pass. Do not change the tests.
context:
  files: [calc.py]           # the files the worker may change
verify:
  - type: command
    run: "python -m pytest -q"
  - type: protect_paths      # changing a test to make it pass is a failure
    paths: ["tests/**"]
allow_new_files: true        # default; false: only the context files may change
```

API workers answer in one of two formats; `edit_format` (in the task file, or per model in the
config) picks it, and the default `auto` chooses by file size:

- **`whole`** (auto, up to `security.max_api_edit_lines`, 400 lines): whole files as JSON,
  `{"files": [{"path", "content"}], "note"}`.
- **`replace`** (auto, above 400 lines): only the places that change, as SEARCH/REPLACE blocks:

```
calc.py
<<<<<<< SEARCH
    return a - b
=======
    return a + b
>>>>>>> REPLACE
```

With `replace` the rest of the file is never rewritten, so large files can go to cheap models
too (whole-file answers of that size get cut off). A SEARCH must match whole lines in exactly
one place (line endings and trailing spaces do not matter); an empty SEARCH creates a new file.
Why `auto` and not always `replace`: in our manual runs a 14B local model did better with whole
files on a small file, and copied large chunks into its blocks anyway (see `docs/DECISIONS.md`,
D-051). Unified diffs from models break too often, so they are not used. Orkestra then:

1. takes the blocks (or the JSON) even with code fences or text around them; a SEARCH that is
   not found (the closest lines of the file are sent back), matches more than once, or a
   broken or cut-off answer goes back to the worker as feedback (`edit_format` check);
2. checks every path: relative, inside the project, no `..` or `.git`, not a `forbid_paths`
   match, and either a context file or a new file. A file the worker was not shown is never
   overwritten;
3. writes the files with the original line endings (CRLF/LF) and runs your checks in the
   worktree. Files your checks leave behind (`__pycache__`, build output) are not part of the
   change;
4. on a failed check: feedback, retry from your original files, escalation, as for any task.

If an answer is cut off at the output limit, the file is too big for that model: the run goes
straight to tier 3. Only with an explicit `edit_format: whole`, files longer than
`security.max_api_edit_lines` (400) are not given to API workers at all; code agents edit them
in place. The envelope has
`edit_format` and `changes: {files, insertions, deletions, patch_path}`, and
`run --dry-run` shows the format of every candidate; then:

```bash
orkestra show <run_id> --diff      # look at it
orkestra apply <run_id>            # take it
```

A run that did not pass its checks keeps its worktree so you can look at the change, but
`apply` then needs `--force`. A run that ends without a change removes its worktree. Context
files that are not UTF-8, that git ignores, or that match `protect_paths`/`forbid_paths` are
shown to the worker read-only. A worker that cannot do the task answers
`CANNOT_DO: <reason>` (`{"cannot_do": "<reason>"}` with `whole`) and the run moves up a tier
at once.

Ctrl+C during a run releases the budget reservation, writes an envelope with
`error: interrupted` and keeps the worktree.

## Code agents: Codex CLI and Antigravity

A `cli_agent` provider runs a real code agent as a subprocess, normally on tier 3. For an edit
task it works directly in the run's worktree; for an `ask` task it reads your project with a
read-only sandbox. Everything else is the same as for API workers: your checks decide,
feedback goes back on failure, `show --diff` and `apply` at the end.

```yaml
providers:
  codex:
    type: cli_agent
    command: codex               # found on PATH (codex.cmd on Windows works too)
    tier: 3
    sandbox: workspace-write     # read-only agents cannot do edit tasks
    model: null                  # null = the agent's default
    timeout_s: 1200              # default: 30 minutes
    budget: {daily_runs: 20}
  agy:
    type: cli_agent
    command: agy
    experimental: true           # agy is experimental: both lines are needed
    enabled: true
```

- The prompt goes through stdin (codex) or a file next to the run records (agy), never the
  command line, so long prompts work on Windows. The agent's output goes to files in
  `~/.orkestra/runs/<run_id>/attempts/<n>/`.
- On timeout or Ctrl+C the agent **and all its child processes** are stopped.
- Codex runs as `codex exec --sandbox workspace-write|read-only --json --output-last-message …`;
  `danger-full-access` is never used. agy runs in its `--sandbox` print mode. Your own login
  sessions (`codex login`) are used; Orkestra never reads them.
- The diff is always taken against the run's baseline, so commits the agent makes count too.
- Your repository is checked before and after every agent run. If anything changed there,
  the `workspace_scope` check fails and you get a warning (Orkestra does not undo it).
- Agent files in your repository (`AGENTS.md`, `.codex/` …) are in the worktree as well and
  steer the agent as usual.
- A feedback run continues from the agent's previous change instead of starting over.
- Any other program (`kind: generic`: prompt on stdin, answer on stdout) works too, but it
  has **no sandbox**: it runs with your permissions (in your project directory for `ask`).
- `doctor` shows the agent's version, warns when codex is not logged in and when agy's
  `permissions.deny` list does not block `rm`/`sudo` (agy approves tool calls by itself in
  print mode).
- A missing program, agy without `experimental: true` and a read-only agent for an edit task
  are listed with their reason in `--dry-run`. Agents have no price: use `daily_runs`.
- **agy and MCP servers:** agy starts every MCP server in `~/.gemini/config/mcp_config.json`
  before it sends anything, even ones marked `disabled`, and waits until all of them connect.
  A server that cannot connect (for example Unity's relay while the Unity editor is closed)
  would hold every run until the timeout. Orkestra stops such a run once agy has waited
  `mcp_wait_s` (default 60 seconds; agy reports every 30 s; `0` never stops it) with an error
  naming the server and moves on to the next provider; `doctor` and `providers enable` warn
  about `disabled` entries. To keep such a server for interactive use, start it through a small
  script that exits at once when its app is not running, e.g. on Windows
  (`command: "cmd.exe"`, `args: ["/d", "/c", "<script>.cmd", "--mcp"]`):
  ```bat
  @echo off
  "%SystemRoot%\System32\tasklist.exe" /FI "IMAGENAME eq Unity.exe" /NH | "%SystemRoot%\System32\find.exe" /I "Unity.exe" >nul || exit /b 1
  "%USERPROFILE%\.unity\relay\relay_win.exe" %*
  ```

Tested with codex-cli 0.160.0 and agy 1.5.5 (agy 1.5.3 before `--log-file` was used).

## Batches: many tasks at once

```yaml
parallel: 4                  # tasks in flight at once (default 4; --parallel overrides)
tasks:
  - id: docs-a
    kind: edit
    prompt: Add docstrings to src/a.py; do not change the code.
    context: {files: [src/a.py]}
    verify: [{type: command, run: "python -m pytest -q"}]
  - id: docs-b
    kind: edit
    prompt: Add docstrings to src/b.py; do not change the code.
    context: {files: [src/b.py]}
    verify: [{type: command, run: "python -m pytest -q"}]
  - id: summary
    kind: ask
    prompt: Summarize what src/a.py and src/b.py do.
    context: {files: [src/a.py, src/b.py]}
    depends_on: [docs-a, docs-b]
```

```bash
orkestra batch tasks.yaml --json              # one JSON document: batch_id, results, totals
orkestra batch tasks.yaml --parallel 2 --fail-fast
```

- Every task is checked like a task file before anything starts. Duplicate ids and unknown
  or cyclic `depends_on` are exit code 2.
- Each provider gets at most its `concurrency` requests at a time across the whole batch
  (Ollama: 1 by default), whatever `--parallel` says.
- Edit tasks whose context files overlap run one after the other, with a warning. Each still
  starts from your files in its own worktree, so applying both may conflict.
- A task whose dependency did not end `ok` is `skipped`. `--fail-fast` starts nothing after
  the first failure. A task that crashes is an `error` item; the rest goes on.
- A dependency only orders tasks: it does not hand its unapplied change to the next task.
  A task that needs another one's change goes into a later batch, after `apply`.
- Exit code: 0 when every task is `ok`, else 1. Each result has the task's envelope; apply the
  good ones with `orkestra apply <run_id>` (batch apply comes in phase 7b).

## Worktrees: isolated changes

Workers never change your checkout. A run that changes code gets its own git worktree under
`~/.orkestra/worktrees/`, which starts from what is on your disk **now**: the last commit plus
your uncommitted changes and untracked files (ignored files stay behind). You look at the
result and decide:

```bash
orkestra show <run_id> --diff      # the change
orkestra apply <run_id>            # bring it into your working tree, remove the worktree
orkestra discard <run_id>          # or throw it away
orkestra gc                        # abandoned worktrees, runs older than 30 days, stale reservations
```

`apply` never stages anything and never touches your other uncommitted work. If you edited the
same files after the run started, it merges them three ways; if a change overlaps yours, it
writes **nothing**, lists the conflicting files and exits with code 5, and the worktree stays
for you to look at. Git hooks do not run in worktrees. Submodules and Git LFS files are not
handled yet (you get a warning). On Windows, `doctor` suggests `core.longpaths` because the
worktree paths are deep. Ignored files (`node_modules/`, `.venv/`) are not copied into the
worktree, so a check that needs them must bring its own (a Python check run with your active
interpreter works).

## Claude skill

`skill/orkestra/SKILL.md` teaches Claude (in Claude Code, or anywhere it has a local shell) when
to hand work to Orkestra and how: delegate only large, checkable work, write a task file with
real verifiers, read only the result envelope, read the diff before `apply`, and never grant
consent (`--yes`), send secrets (`--allow-secrets`) or force an unverified change (`--force`)
on its own. A test checks that every command and flag the skill names exists in the CLI.

```bash
# as a personal skill
mkdir -p ~/.claude/skills && cp -r skill/orkestra ~/.claude/skills/
# or only for one project
mkdir -p .claude/skills && cp -r skill/orkestra .claude/skills/
```

Then ask Claude, for example: *"Add docstrings to these 20 files with orkestra, and review the
result."* The skill is in Turkish for now (it will be translated with the release) and covers
the commands that exist today; `status`, `map`, `review`, templates, batch runs and handoff
come back into it once those phases land.

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
| 1 | Verification failed (`failed`) or the chief has to take over (`escalate`); for `doctor`: a check failed |
| 2 | Configuration or usage error |
| 3 | No suitable provider, or every candidate failed (unreachable, paused, budget exhausted, secrets in context, no key, outside the profile) |
| 4 | User consent required (`orkestra providers enable <name>`) |
| 5 | `apply` conflict: nothing was written, the worktree is kept |
| 10 | Unexpected internal error |

## Security

- API keys are never stored in config files. Only the environment variable's name is kept there, and `doctor` reports whether the variable is set, never its value.
- Error messages from providers are scrubbed, so a key echoed back by an API (e.g. in a 401 body) does not reach the output.
- `danger-full-access` sandboxing for code agents is rejected by the config.
- No provider is used without explicit consent. Consent is tied to the settings that decide where data goes and what may run (URL, key variable, headers, command, sandbox, model ids), so changing one of them asks again. Turning a provider off and on, or changing its budget or timeouts, does not.
- Context files are scanned for secrets (OpenAI/OpenRouter/AWS/GitHub/Slack/Google keys, private keys, and the values of your configured key variables). Such context never goes to a remote provider unless you pass `--allow-secrets`.
- Everything Orkestra writes to `~/.orkestra/runs/` (request, response, output, envelope, log) is redacted. The prompt itself is scanned too, and files matched by `.orkestraignore` are never sent.
- A `command` verifier runs a command you wrote, in your working directory. That is the same risk as running it yourself; Orkestra adds nothing to it and uses a shell only with `shell: true`.
- No telemetry. Everything stays on your machine and with the providers you choose.

## Roadmap

| Phase | Topic | Status |
|---|---|---|
| 0 | Skeleton, tooling, i18n foundation | ✅ |
| 1 | Configuration: schema, merge, `init`, `config` | ✅ |
| 2 | Ollama + OpenAI-compatible adapters, `ask`, `doctor` | ✅ |
| 3 | State DB, daily budgets, provider consent, circuit breaker, secret scanning | ✅ |
| 4 | Router, retries and **failover**: offline → local Ollama, failing API → next provider | ✅ |
| 5a | Task files, verifiers, retries with feedback, escalation (`orkestra run`) | ✅ |
| 5b | Git worktrees, `show`, `apply`, `discard`, `gc` | ✅ |
| 5c | Edit tasks with API workers | ✅ |
| 6 | Code agents: Codex CLI, Antigravity CLI | ✅ |
| 7a | Batch runs: dependencies, parallelism, per-provider limits | ✅ |
| 7b | Cost estimate, batch apply, `stats` | ⏳ |
| 8 | Chief tools: `status`, `review`, `map`, templates, `plan expand`, cache, savings counter | ⏳ |
| 9a | Claude skill: `SKILL.md`, checked against the CLI | ✅ |
| 9b | Claude skill: review and manual scenarios | ✅ |
| 9c | SEARCH/REPLACE edits for cheap models (`edit_format: auto`) | ✅ |
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
