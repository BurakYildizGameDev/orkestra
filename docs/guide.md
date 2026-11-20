# Orkestra guide

**English** · [Türkçe](guide.tr.md)

The details behind the [README](../README.md): how routing works, task files, edits, code agents, batches, the night queue, the chief tools and the configuration. Ready-made workflows are in [recipes](recipes.md).

## Contents

- [Routing and failover](#routing-and-failover)
- [Task files and verification](#task-files-and-verification)
- [Edit tasks: workers change code](#edit-tasks-workers-change-code)
- [Code agents: Codex CLI and Antigravity](#code-agents-codex-cli-and-antigravity)
- [When an AI runs out](#when-an-ai-runs-out)
- [Batches: many tasks at once](#batches-many-tasks-at-once)
- [Night queue and notifications](#night-queue-and-notifications)
- [Chief tools](#chief-tools)
- [A second AI reviews: cheaper writing for the chief](#a-second-ai-reviews-cheaper-writing-for-the-chief)
- [Long command output: `orkestra exec`](#long-command-output-orkestra-exec)
- [Reading and searching without filling the context: `orkestra read`, `orkestra find`](#reading-and-searching-without-filling-the-context-orkestra-read-orkestra-find)
- [Where do Claude's tokens go?](#where-do-claudes-tokens-go)
- [Short sessions: a fresh context when it pays off](#short-sessions-a-fresh-context-when-it-pays-off)
- [The right model for each kind of work](#the-right-model-for-each-kind-of-work)
- [Worktrees: isolated changes](#worktrees-isolated-changes)
- [Claude skill](#claude-skill)
- [Configuration](#configuration)
- [Result envelope and exit codes](#result-envelope-and-exit-codes)

## Routing and failover

`ask` goes through the **router**. It lists every (provider, model) that may run the task.
The tier always comes first (lowest first); inside a tier the order is:

1. a provider whose quota is about to run out goes last (`forecast`, see [Before it runs out](#before-it-runs-out));
2. `routing.by_kind`: the models you prefer for this kind of work (summary, code, …);
3. `routing.adaptive`: the model that did best on tasks with the same tag (after `min_samples` runs; neutral until then);
4. `priority`, higher first;
5. the order you wrote them in the config (providers first to last, then each provider's models).

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
task from its options. See [`examples/tasks/`](../examples/tasks/).

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

```text
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
  about `disabled` entries. `orkestra doctor --mcp` starts each enabled stdio server, sends the
  MCP `initialize` request and reports by name which answer, which time out (each agy run would
  wait for them) and which exit at once (a guard script while its app is closed); it starts
  your real servers, so it runs only when asked. To keep such a server for interactive use, start it through a small
  script that exits at once when its app is not running, e.g. on Windows
  (`command: "cmd.exe"`, `args: ["/d", "/c", "<script>.cmd", "--mcp"]`):
  ```bat
  @echo off
  "%SystemRoot%\System32\tasklist.exe" /FI "IMAGENAME eq Unity.exe" /NH | "%SystemRoot%\System32\find.exe" /I "Unity.exe" >nul || exit /b 1
  "%USERPROFILE%\.unity\relay\relay_win.exe" %*
  ```

Tested with codex-cli 0.160.0 and agy 1.5.5 (agy 1.5.3 before `--log-file` was used).

## When an AI runs out

The point of having several providers is that the work goes on when one of them stops. What
happens in each case, without you stepping in:

| What ran out | What Orkestra does |
|---|---|
| **Connection** (offline, DNS, refused) | one retry after 0.5 s, then the next provider in the same command; a local model takes over in about half a second |
| **API errors** (timeouts, 5xx, short rate limits) | retried with backoff; after 3 failures in a row the provider is paused for 5 minutes |
| **Your budget** (`daily_usd`, `daily_tokens`, `daily_runs` …) | the provider is left out until local midnight; the next one gets the work |
| **The provider's quota** (Codex or agy usage limit, Gemini `RESOURCE_EXHAUSTED`, OpenRouter's free daily requests, OpenAI `insufficient_quota`, Ollama cloud usage limits) | not retried: the provider is **paused until its quota resets** (the time in its message, else `quota_pause_s`, default 1 hour) and the task moves on in the same command; later tasks, the rest of a batch and the night queue do not try it again |
| **The chief's quota** (Claude's own limit) | `orkestra handoff to <chief>` hands the work to the next chief with a short brief (see Chief tools) |

```yaml
providers:
  agy:
    type: cli_agent
    command: agy
    quota_pause_s: 7200          # when the quota message has no reset time (default 3600)
```

- The quota message is looked for only when a run already failed (non-zero exit, no answer,
  HTTP 429), and for agents only in the last lines of their output, so an answer or test
  output that talks about quotas never pauses anything. A message Orkestra does not know
  still fails over to the next provider as before; only the pause is missing.
- A short rate limit ("429 Too Many Requests") is not a used-up quota: it is retried or
  counted as before (3 in a row pause for 5 minutes).
- A quota of one model, not the account (OpenRouter's free models per day, Gemini's
  per-model quotas), skips only that model; the provider's other models keep working.
- The reset time in the message wins over a generic `retry-after` header.
- The envelope's `failovers` say `ProviderQuotaExhausted` with the provider's own words;
  `status`, `providers list`, `doctor` and `--dry-run` show "quota used up, paused until 14:30"
  (with the date when it is a weekly limit). `orkestra providers enable <name>` lifts the
  pause at once.
- `batch --notify` and `queue run --notify` add one line naming the providers whose quota ran
  out during that batch or queue run and when they open, nothing else.
- Measured without network (`tests/integration/test_continuity_cli.py`): an agent that runs
  out of quota at task 4 of a 10-task batch → **10/10 tasks finish**, 4 to 10 on Ollama; the
  agent is started 4 times and never again after its quota message; switching costs one
  failed agent run and no waiting.

### Before it runs out

Orkestra also looks ahead. It compares each provider's pace over the last hour with its
limit and tells you when the limit will be reached:

- **Known limits** are your `budget` (`daily_runs` …). **Learned limits** cover quotas nobody
  wrote down, such as an agent's subscription: every used-up quota records how much was used
  since its window began, and the median of the last 5 becomes the limit.
- A provider is **running low** when it would run out within an hour or has 10 % or less
  left. `status`, `doctor` and the `--notify` messages say so ("quota running low: agy: ~40
  min (runs 18/20)"). The router then tries it **last in its tier**: work drifts to the
  others before the quota is gone, and nothing is blocked. `--dry-run --json` shows
  `quota_low`.

```yaml
forecast:
  enabled: true        # false: no warnings, no reordering
  window_s: 3600       # the pace is read over this span
  warn_within_s: 3600  # "running low" when the limit is this close
  low_share: 0.1       # ... or when this share of the limit is left
  learn_events: 5      # used-up quotas a learned limit is the median of
```

**The chief's own quota.** Claude Code passes its usage windows (5 hours, 7 days) to a status
line command. Wire up Orkestra's line and hook once:

```bash
orkestra statusline config   # prints the part for ~/.claude/settings.json
```

The line reads `Claude 5h 72% (~40 min) · 7d 40% | orkestra: agy ~20 min (runs 18/20)`. Once a
window passes `handoff.prepare_at_percent` (default 85), or would run out within an hour, the
hook tells Claude, once per window, to bring the handoff file up to date and commit. When the
limit then runs out, you type only `orkestra handoff to agy`. Both commands start in about
0.3 s: they skip the rest of the CLI.

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
- Exit code: 0 when every task is `ok`, else 1. Each result has the task's envelope.

**Cost.** `orkestra batch tasks.yaml --estimate` prices every task's first request on the
provider the router would pick (prompt + `max_output_tokens`, the same estimate a budget
reservation uses) and sends nothing; it uses cached price lists, like `--dry-run`. Retries,
feedback and moving up a tier can cost more. Code agents and models without a price are
listed as unpriced and left out of the total; a local model without a price costs 0.
A paid (remote) model whose price is not known cannot be checked, so a batch that uses
one asks first as well.

Before a real run the batch is estimated the same way. Above `estimate.confirm_above_usd`
(default `0.50`; `null` turns the check off) a terminal is asked; `--json`, or a run without
a terminal, prints the estimate (`needs_confirmation: true`), runs nothing and exits with 2
until you add `--yes-cost`. A setup with only local models without a price (and code
agents) costs nothing and skips this check.

**Applying.** Look at each run (`show <run_id> --diff`), discard the ones you do not want,
then `orkestra apply --batch <batch_id> --only-ok`: the batch's passing edit runs are applied
in the order they ran, runs that did not pass or were applied already are skipped. At the
first conflict it stops with exit code 5 and reports what was applied, the conflicting run
and the runs it did not try; any other error stops the same way, with its own exit code,
and the report keeps what was applied. Without `--only-ok`, a batch with a failed run that
still has a change is refused and nothing is applied (a failed run you discarded does not
count).

**Statistics.** `orkestra stats --since 7d` (or `24h`, `30m`) shows per provider and per task
tag: finished runs, success rate, average attempts and time, tokens and cost. A run counts for
the provider that answered; an escalated run counts for the last provider it used. Runs still
marked `running` are counted apart.

## Night queue and notifications

Queue work during the day; let it run while the computer is free (for example at night, on
free local models):

```bash
orkestra queue add tasks/docstrings.yaml                 # checked now; the folder is kept
orkestra queue add tasks/tests-batch.yaml --profile cheap
orkestra queue run --until 07:00 --notify                # leave the terminal open
```

- The queue lives in `state.db`. Items run one after another, each in the folder it was added
  from (with that project's `orkestra.yaml`). A file changed after `queue add` is announced and
  the current version runs. Without `--profile` an item runs on `queue.default_profile`.
- Only one `queue run` works at a time (a second one exits with code 5); a lock left by a
  crashed run is cleared, and items it left `running` are queued again.
- `--until HH:MM` starts no new item after that time; `--max-cost-usd` starts none once that
  much is spent (`0` means free work only). Nobody is there to confirm a cost at night: a batch
  that would ask is skipped and stays queued (with `--max-cost-usd`, the cap decides instead).
- It is not a service: a sleeping computer runs nothing. To start it every night, use cron or
  Windows Task Scheduler: see [`docs/recipes.md`](recipes.md).
- Notifications (`queue run --notify`, `batch --notify`) hold only the counts ("5 finished,
  1 failed"), never task text or code. Desktop notifications need the extra
  (`uv tool install git+https://github.com/BurakYildizGameDev/orkestra --with "desktop-notifier>=6.0,<7"`); without it they are skipped quietly. Phone
  notifications go to [ntfy](https://ntfy.sh): set `notify.ntfy_topic_env` to the name of an
  environment variable that holds the topic. `orkestra notify test` tries every channel.
- In the morning: `orkestra status` → `orkestra review` → `orkestra apply`.

## Chief tools

**`orkestra status`** is the one command to start a session with: the chief and profile, the
edit runs that passed and wait for `apply` or `discard`, today's budget per provider and the
paused providers, in at most 15 lines (`--json` has everything). It also shows the handoff
file's goal when the project has one, and the night queue's waiting, running and failed
items when there are any.

**Handoff file (`orkestra handoff`).** When a chief's quota runs out, the work continues in
`.orkestra/HANDOFF.md` instead of the next AI's memory: the goal, the status, what is done,
the decisions, open questions and the traps, plus who updated it and at which commit
(`orkestra handoff init` creates it, `update --section done --add "…"` appends a dated,
attributed item, `--set` replaces a text section). `orkestra handoff check` warns when the
file is older than `handoff.stale_after_commits` commits (`--strict` exits 1, `--warn-only`
never fails and prints only warnings). `orkestra handoff show --brief` prints the short brief for the next chief: the
file's key sections (including `In progress`, the next step) plus the real branch, `git status`, the last commits, unapplied runs and
the remaining budget, never more than `handoff.brief_max_lines` lines (when it has to cut,
the staleness warning and the Orkestra guide stay and project lines go first). A chief other than
Claude learns Orkestra from that guide (the context filter, when to delegate, review and
`apply --max-risk low`, the handoff file); `orkestra handoff show --guide` prints it alone, to give
an agy or codex session you opened yourself. Text written through
`update` is redacted, and `Done`/`Decisions` that outgrow `handoff.max_lines` move their
oldest items to `.orkestra/HANDOFF.archive.md` (appended, never deleted).

`orkestra handoff to <chief>` finally hands over: it builds the brief, writes one `handoffs`
row (who, to whom, when, at which commit, where the brief was written) and starts the target
agent in your terminal, in the repository root and with `ORKESTRA_CHIEF` set to its name
(run it yourself, not from inside a chief's command tool: the agent needs a real terminal;
Ctrl+C then belongs to the agent); Orkestra exits with the agent's own exit code. How the brief arrives is
`chiefs.<name>.prompt_mode`: `arg` (last argument), `stdin`, or `file`
(`.orkestra/BRIEF.md` plus one short instruction). A `.cmd`/`.bat` launcher or a brief over
8000 characters falls back to `file` with a warning. `--print-only` shows exactly what would be
sent without starting anything or recording a row. With uncommitted changes `to` stops with
exit code 5 and names the files unless you pass `--allow-dirty`; the handoff file, its
archive and the generated `BRIEF.md` never count as dirty. `orkestra handoff install-hook` adds a marked, idempotent block to the repository's
`pre-commit` hook right after its shebang, so the reminder is shown on every commit (it never
overwrites the hook and never blocks a commit; a hook that is not a shell script is left
alone with a message; in a worktree it uses the hooks path git reports).

**Templates** save writing task files:

```bash
orkestra templates list
orkestra run --template docstring --files "src/*.py" --param style=numpy --dry-run   # the tasks
orkestra run --template docstring --files "src/*.py" --param check="python -m pytest -q"
```

Every matching file becomes one task (tagged with the template's name), and they run as a
batch, with the same cost check. Built-in: `docstring`, `type-hints`, `tests`, `summarize`
(a JSON answer, changes nothing), `rename-refactor` (`old`, `new`), `translate` (`language`).
`templates show <name>` lists the parameters. The optional `check` parameter is a command that
must pass (your tests); without it only the number of changed files is checked. A project can
add or override templates in `.orkestra/templates/<name>.yaml`: `description`, `params`
(`name: {default, description}`; no default means required) and `task` (task fields without
`id`; `$file` and `$<param>` are filled in, a `$` in a file name stays as it is). A project
template that replaces a built-in one is announced on every use: a cloned repository could
ship its own commands, so look at it with `templates show` first. `--files` only takes real
files inside the working directory that `.gitignore` and the ignore file keep.

**Answer cache.** An `ask` task's answer that passed its checks is kept for `cache.ttl_days`
(14) days under `~/.orkestra/cache/responses/` (secrets masked, no prompt). The same question
to the same model with the same context files and checks comes from there: nothing is sent,
no budget is used, the envelope says `cached: true`. A changed context file is a new
question, and a cached answer that no longer passes its checks is dropped and the worker is
asked. `edit` tasks and code agents' answers are never cached. `--no-cache` (on `ask`, `run`, `batch`) skips it for one command,
`cache.enabled: false` turns it off, `orkestra cache clear` empties it.

**Savings (estimated).** `orkestra stats` also shows how many tokens the workers wrote and how
many came back to the chief in envelopes, for the runs that passed. The chief's own use
cannot be measured, so the line is always marked as an estimate.

## A second AI reviews: cheaper writing for the chief

Delegating writing has a fixed cost for the chief: writing the task and reading what came
back. Orkestra keeps the reading short. Another provider reviews the worker's change, and the
chief reads a few lines of report instead of the diff:

```bash
orkestra review RUN_ID --json        # reviewed by a provider other than the author
orkestra show RUN_ID --report        # done / checked / changes / review / look at / next
orkestra apply RUN_ID --max-risk low # only if an independent review said low
```

```yaml
review:
  auto: true            # every edit run that passes its checks is reviewed
  independent: true     # never the author when another provider can review (default)
  by:
    ollama: [agy, openrouter]   # Ollama's changes: agy reviews, else OpenRouter
    "*": [openrouter]           # everyone else's
```

- The reviewer is never the provider that wrote the change while another one can review. When
  none can, the author reviews and the report says `independent: false`. Code agents can
  review too (read-only sandbox).
- `apply --max-risk low` applies only when the checks ran and passed, an independent review
  found the change at most that risky with nothing flagged (`unknown` never passes), and the
  change is still the one that was reviewed; otherwise it refuses with code 2 and the chief
  reads the diff. Reviewers named in `review.by` and missing consents are never skipped
  silently; `doctor` warns about a `review.by` name that is no provider. `apply --batch ID --only-ok --max-risk low` applies the runs that
  passed and lists the others as skipped.
- `show --report` ends with the one command to run next: `apply --max-risk low`, the flagged
  lines, the whole diff, or `review` when there is none yet.
- The skill tells the chief not to delegate one small task, to hand over mechanical work in
  one batch (or `run --template`), and to use the project's own tests as the check.

## Long command output: `orkestra exec`

Test runs, linters and builds are the biggest thing that enters Claude's context (see the
token map below), and every later request reads them again. `orkestra exec` runs the
command and gives back only what matters:

```bash
orkestra exec -- uv run pytest
orkestra exec --max-lines 20 -- uv run ruff check .
orkestra exec --json -- npm test
```

```text
exit 1 · 412 lines · pytest · full output: ~/.orkestra/runs/20261117-205059-46bf/output.log
3 failed, 120 passed in 4.10s
tests/test_calc.py:6: FAILED tests/test_calc.py::test_add - assert -1 == 5
…
```

- Up to `exec.max_lines` lines (default 40) the output comes back as it is.
- Longer output of a tool Orkestra knows is digested by rules, with no model and no
  mistakes: **pytest** (every failed or errored test, never dropped, with the `file:line`
  where it failed), **ruff** (check and format), **pyright**, and compilers or type checkers
  that write `file:line` (mypy, gcc/clang, tsc, rustc). Paths are relative to the project.
- Other long output is summarised by a chat model on `exec.tier` (default 1, through the
  router, so output with keys stays local; code agents are never started for it). Without
  one, or with `--no-model`, the first and last lines are shown and the reason is named.
- The exit code is the command's own (127: program not found, 124: `--timeout` hit, the
  command and its child processes are stopped). The whole output, with keys masked, is in
  `runs/<id>/output.log` (cleaned by `gc` like other run records).
- There is no shell: pipes, `&&` and redirection do not work; give one command.

The Claude skill tells Claude to run tests, linters and builds this way.

## Reading and searching without filling the context: `orkestra read`, `orkestra find`

Reading a large file to answer one question costs that file in every later request.
Instead:

```bash
orkestra read src/config/loader.py "In what order are configs merged?"
orkestra find "load_config(" --glob "src/**"
orkestra find "TODO" --ask "Which of them are about security?"
```

- **`read FILES... QUESTION`**: a chat worker (`read.tier`, default 1; never a code agent)
  reads the files with numbered lines and answers in a few lines with `file:line` pointers.
  Every pointer is checked against the files: a valid one is shown with the line it names,
  an invalid one is marked so it is not trusted. The files are read like task context
  (`.orkestraignore` and binary files are left out and listed, the size limit applies). The
  same question on unchanged files comes from the answer cache (`--no-cache` asks again).
- **`find PATTERN`**: no model. Text (case-sensitive) or, with `--regex`, a regular
  expression, in the project's files (`.gitignore`, `.orkestraignore`, binary files and
  Orkestra's folders left out; `--glob` narrows it). Up to `find.max_hits` hits (default 40)
  come back as `file:line: text`; more are grouped per file with the file's summary from the
  project index and its first hits. No hit is exit code 1, like grep. `--ask "<question>"`
  lets a worker answer about the hits (with a few lines around each), with checked pointers.
- **The project index** is `orkestra map`'s per-file summaries. `orkestra map --install-hook`
  adds a post-commit hook that runs `orkestra map --after-commit` in the background: the files
  each commit changed are mapped, one run at a time (a rebase queues them), so the index stays
  current without slowing commits down.

## Where do Claude's tokens go?

`orkestra tokens` reads Claude Code's own session transcripts
(`~/.claude/projects/<project>/*.jsonl`, or under `$CLAUDE_CONFIG_DIR`) and shows what a
session spent and why. It sends nothing and uses no quota.

```bash
orkestra tokens                      # the latest session of this project
orkestra tokens --since 7d --top 10  # every session of the last week
orkestra tokens --session 1f49 --json
orkestra tokens --project ../other-repo
```

What a tool call costs is more than its size: its result is written to the prompt cache once
and then **read again with every later request** until the session ends or is compacted. A
300-line file read early in a 300-request session is paid for 300 times. The report shows:

- the measured totals (input, cache write, cache read, output) and a weighted sum with API
  prices relative to an input token (output ×5, cache write ×1.25, cache read ×0.1; set in
  `tokens.weights`, since a subscription may weigh them differently);
- where the weighted tokens go: reading, command output, writing, agents, Claude's own
  replies read again, your later messages and reminders, Claude's output, the fixed start
  (system prompt, tools, CLAUDE.md) read with every request, cache misses (the context
  written again after a pause or a model change), and the rest;
- the costliest tool calls with "as 10 lines it would cost …";
- how the context grows per request, subagents (counted apart) and compactions.

Tool call sizes are estimated (4 characters ≈ 1 token) and then scaled per session so that
they add up to the new context Claude Code measured; the factor is printed. Labels show
files relative to the project and commands with the project as `.` and home as `~`.

Example, this repository's own 12 sessions of building Orkestra (Claude Code 2.1.312–2.1.325,
2,793 requests):

```text
where the weighted tokens go:
  command output (Bash, PowerShell): 23%
  your later messages and reminders: 21%
  writing (Edit, Write): 16%
  Claude's output (text, thinking, tool calls): 14%
  Claude's replies and tool calls, read again later: 12%
  fixed start (system prompt, tools, CLAUDE.md, memory), read again by every request: 11%
  reading (Read, Grep, Glob, web): 8%
  cache misses (context written again after a pause or model change): 1%

costliest tool calls (size × requests it stayed in the context):
  Read YAPILIS_PLANI.md: ~23,027 tokens, 650 lines, read again 269×, weighted 648,210
    as 10 lines: 9,972 (saves 638,238)
context per request (newest session): 47,252 → 174,632 → 247,227 → 332,261 → 405,278
```

So about 85% of the cost is context being read again, not Claude's writing: big command
outputs and file reads early in a long session are the levers, which is what the next phases
(a context filter and shorter sessions) go after.

## Short sessions: a fresh context when it pays off

In a long session every request reads the whole context again (see the token map), so the
cost of a request grows with the session. Past `handoff.suggest_at_tokens` (default 120,000)
`orkestra status` and `orkestra tokens` say what a fresh session would save, from the
session's own numbers:

```text
context ~180,000 tokens: a fresh session saves ~1,300,000 weighted tokens per 100 requests
(orkestra handoff update …, then /clear and orkestra handoff show --brief, or orkestra handoff to claude)
```

A fresh session starts from the first request's context (system prompt, tools, CLAUDE.md)
plus the handoff brief (~3,000 tokens); every later request then reads that much less.
Two ways to take it, after updating the handoff file and committing: `/clear` in Claude
Code and read `orkestra handoff show --brief`, or close the session and run
`orkestra handoff to claude` (a handoff to the same chief). The Claude skill suggests it at
the end of a phase or subtask, never in the middle of one.

## The right model for each kind of work

Light work (digesting `exec` output, `read`, `find --ask`, file summaries for `map`) does not
need the model that writes your code, and on your own computer a big model for a one-line
summary only slows everything down. `routing.by_kind` says which models each kind of work
tries first:

```yaml
routing:
  by_kind:
    summary: {prefer: ["ollama/qwen2.5:1.5b", "openrouter/*:free"]}  # orkestra exec
    read:    {prefer: ["ollama/qwen2.5:3b"]}                         # read, find --ask
    map:     {prefer: ["ollama/qwen2.5:1.5b"]}
    edit:    {prefer: ["ollama/qwen2.5-coder:14b", "codex"]}
```

- Kinds: `summary` (`exec`), `read` (`read`, `find --ask`), `map`, `review`, `plan`, and the
  task kinds `ask` and `edit`. A pattern is a provider (`codex`), a `provider/model`, or a
  glob of them (`openrouter/*:free`); the first pattern that matches gives the place.
- It orders **inside each tier** only: the tier rule, budgets, privacy and a provider running
  low on quota come first; models it does not name follow in the usual order. Without
  `by_kind` nothing changes. `--dry-run --json` shows `prefer_rank`.
- **One heavy local model at a time.** A local provider's `concurrency` (default 1) now holds
  across processes: a batch in one terminal, `orkestra exec` from the chief and the night
  queue wait for each other instead of loading a second model next to the first. A slot
  left by a crashed process is taken back. Heavy work can still go to the night queue
  (`orkestra queue add`).
- `orkestra doctor` suggests sizes for this computer when a local provider is configured
  ("RAM 32 GB, GPU 12 GB: summaries on a 1.5b-3b model, code up to about 14b") and warns about
  a configured local model that looks bigger. Only a suggestion.

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
result."* The skill is two files: `SKILL.md`, a short English core that Claude loads (when to
delegate, how to run and review, the guardrails), and `reference.md`, the full details in Turkish
that Claude reads only when needed. Together they cover every command that exists today, including
`batch`, `map`, `review`, `plan expand` and the handoff file (`handoff update`, `show --brief`,
`to --print-only`). Copy the whole folder.

## Configuration

Orkestra reads a base file and a project file, and the project file wins:

1. Base: `--config <file>` › `$ORKESTRA_CONFIG` › `~/.orkestra/config.yaml`
2. Project: the nearest `orkestra.yaml` from the current directory up to the git root

Mappings are merged deeply, lists are replaced, and `providers.<name>: null` removes a provider.
Unknown keys are rejected so that typos do not pass silently. A `daily_usd` limit is checked
before each request using `price_per_mtok`; without it Orkestra uses the provider's published
price list (OpenRouter, cached for a day) or, failing that, the cost seen in past requests. The full example with comments is
[`examples/orkestra.example.yaml`](../examples/orkestra.example.yaml).

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

### Adding a provider

Any OpenAI-compatible service can be added without editing YAML; nothing is built in for a
particular service. The key itself is never written: only the name of the environment
variable that holds it (default `<NAME>_API_KEY`). Adding is not consenting, so
`providers enable` still follows.

```bash
orkestra providers add myapi --base-url https://api.example.com/v1 \
  --model some-model --model other-model --check     # --check asks the server for its models
orkestra providers add lab --base-url http://localhost:1234/v1 --model m --no-key
orkestra providers import opencode                   # from OpenCode's opencode.json
orkestra providers import opencode --name myapi      # when the file has several
orkestra providers import opencode --name My.Lab --as lab   # under another name
orkestra providers remove myapi                      # and its consent
orkestra providers enable myapi
```

`import opencode` reads `@ai-sdk/openai-compatible` entries (`baseURL`, `models`). An
`apiKey` of the form `{env:VAR}` gives the variable name; a key written in the file is not
copied, and Orkestra says which variable to put it in. A value given as the key variable
must be a variable name, so a pasted key is refused and never shown. A model's `limit.context`
becomes its context window. `init --plain` offers the same as
"another OpenAI-compatible service". `--tier` (default 2), `--context-window` and `--project`
work for `add` and `import`.

Errors point at the exact field, in the selected language:

```text
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
