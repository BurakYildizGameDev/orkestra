# Benchmark

Does handing work to cheap or local workers save the chief's tokens without losing quality?
This folder measures it. Results go to `results/`; the main README shows the latest table,
including the bad results.

## Modes

| Mode | Who works | How |
|---|---|---|
| A – Claude only | Claude Code | `claude -p "<task>" --output-format json`, no skills (`--disable-slash-commands`), no MCP servers (`--strict-mcp-config`) |
| B – Claude + Orkestra skill | Claude Code as chief, Orkestra workers | the same, with the Orkestra skill in the workspace (`.claude/skills/orkestra/`: `SKILL.md` and `reference.md`; each window records the skill's hash), permission to run `orkestra`, and a short hint to delegate when it fits, put before the task text |
| C – Orkestra only (cheap) | Orkestra, no chief | `orkestra run <task> --profile cheap --json`; a passing run is applied with `orkestra apply` |
| D – Claude + Orkestra, delegation asked | Claude Code as chief, Orkestra workers | like B, but the hint asks Claude to hand the work to an Orkestra worker and do it itself only when Orkestra cannot; not part of `--mode all`: choose it with `--mode d` or a list such as `--mode a,d` |
| E – agy chief + Orkestra | Antigravity (`agy`) as chief, Orkestra workers | `agy --print` with the hint, Orkestra's chief guide (`prompts/chief_guide.md`, what `handoff to agy` gives) and the task in a prompt file; no `--sandbox` (in print mode it refuses every shell command, D-048); not part of `--mode all`. agy reports its own tokens (input, output, thinking), shown in their own line: they are not comparable 1:1 with Claude's. Without a sandbox agy could read other folders, so no hidden test stays on disk after its evaluation (any mode), and a trace (agy's log or output) that names the hidden tests or the task folder stops the benchmark like the leak guard. Uses agy's quota, none of Claude's; agy's quota message stops the run like Claude's limit |
| F – Claude + context filter (Faz 13g) | Claude Code alone, Orkestra as a filter | like B, but the hint asks Claude to run long commands with `orkestra exec` and read big files and logs with `orkestra read`/`find`, and to hand no work to workers; not part of `--mode all` |
| G – Claude + filter + bulk delegation + cross review (Faz 13g) | Claude Code as chief, Orkestra workers | F plus: hand the bulky, checkable parts to workers in one batch, have another provider review them (`--reviewer`), read `show --report` instead of the diff, apply low-risk results with `--max-risk low`; not part of `--mode all` |

A, B and D use `--setting-sources project`, so personal settings, hooks and memory do not
take part, and the same tool permissions: read, edit, write, search, `python`, `pytest`, `git`
(B and D also `orkestra`), in both the Bash and the PowerShell tool, plus read-only commands under
the names people type (`cd`, `ls`, `dir`, `cat`, `type`, `pwd`, `Get-Content`,
`Get-ChildItem`, `Select-String`, `Set-Location`, `Get-Location`): on Windows Claude Code uses
both shells, and every refused call costs turns. Nothing that can write a file through a
redirect (`echo`, `Write-Output`) is allowed. Each results file records the list it was
measured with (`meta.claude_tools`). The task text goes to Claude on **stdin** and the permissions in a
`--settings` file: on Windows `claude` is an npm `claude.CMD`, and cmd.exe would cut a
multi-line argument or mangle its quotes. B and C use an Orkestra home made for the run: local Ollama only, the
answer cache off (the same task runs several times) and adaptive routing off (every repeat
routes the same way).

## Tasks

20 tasks written for this benchmark (not copied from existing sets), in `tasks/<id>/`:

| Difficulty | Tasks |
|---|---|
| easy (8) | docstrings, type hints, a dataclass, a rename across two files, four small functions to implement |
| medium (8) | three bug fixes, a refactor, an LRU cache, a CSV field parser, a command line option, writing tests |
| hard (4) | changes across a package: a plugin registry, a safe money transfer with rollback, renaming a class with a deprecated alias, a cache with invalidation |

Each task has:

- `task.yaml`: the prompt every mode gets, the files it is about, an optional visible check
  (`check:`, e.g. the project's own tests), whether new files are allowed.
- `project/`: the starting code (rough on purpose; ruff and pyright skip `bench/tasks`).
- `hidden/`: the tests that decide pass/fail.
- `solution/`: a reference solution.

The test suite checks every task: the hidden tests **fail** on `project/` and **pass** on
`project/` + `solution/`, and the visible check passes on both. For the test-writing task the
hidden tests run the worker's tests against the real code (must pass) and seven broken
versions (each must fail).

### The big suite (Faz 13g, D-115)

`--suite big` runs `tasks_big/` instead: one realistic task, `g01-ledger`, on a ~1,200-line
package with 33 tests and a 1,774-line (160 KB) import log. One prompt asks for seven things:
find an amount-parsing bug from the log, two new modules (budgets with rollover, recurring
transactions), a CSV export, a CLI command, docstrings on every public name of two modules and
two new test files. 36 hidden tests check each part. It answers 13g's question: on a big job
that is mostly reading, does splitting the work cut Claude's tokens by at least 25 %?

```bash
uv run python bench/run_bench.py --suite big --mode a,f,g --repeat 2 --worker agy     --reviewer ollama --timeout 2700
```

`--reviewer ollama|agy` adds a second provider at tier 2 that reviews the worker's runs
(`review.by`); it must differ from `--worker`. The suite and the reviewer are recorded in the
results file and kept by `--resume`.

## Hidden tests never reach a worker

- A run works in a fresh git repository with only `project/` in it.
- Before a run starts, `check_no_leak` stops it if any file in the workspace is a hidden test
  (by name or content) or a solution file, or if the prompt quotes a hidden test.
  `check_orkestra_task` also stops mode C if a context path or glob could leave the
  workspace.
- Hidden tests are copied only into a separate evaluation folder, after the run, next to a
  copy of the result.

Limit: in modes A and B, Claude Code could in principle read files outside the workspace by
absolute path; the hidden tests live in this repository, not in the workspace, and nothing
points Claude to them.

## Running

```bash
uv run python bench/run_bench.py --dry-run                      # checks every task; starts nothing
uv run python bench/run_bench.py --mode c --tasks 01,09 --repeat 1
uv run python bench/run_bench.py --mode all --repeat 3          # 180 runs
```

Options: `--ollama-model` (default `qwen2.5-coder:14b`), `--ollama-model-2` (an optional
tier-2 model; only modes B and D can use it, when Claude asks for tier 2: mode C runs the `cheap`
profile, tier 1), `--claude-model`, `--timeout` (per run, default 900 s), `--work-dir`,
`--out`. If the leak guard trips, the whole benchmark stops (exit code 3): it is never counted
as a model failure.

Modes A and B use your Claude Code quota: a full run is 120 Claude sessions, more than one
5-hour window. So a run can be split:

```bash
uv run python bench/run_bench.py --mode all --repeat 1 --max-claude-runs 0    # mode C only, no quota
uv run python bench/run_bench.py --resume bench/results/<date>.json --max-claude-runs 10   # next window
uv run python bench/run_bench.py --resume bench/results/<date>.json --repeat 3  # add repeats
```

- `--max-claude-runs N` starts at most N Claude sessions in this call. The runs that need no
  Claude (mode C) still run; the Claude sessions past the limit wait for `--resume` (D-110).
- When Claude's usage limit (or an overload) stops a session, the benchmark stops with exit
  code 4 and that run is **not** recorded as a failure; resume after the limit resets.
- `--resume <file>` skips the runs already in that file and appends to it. Tasks, modes,
  models and the timeout come from the file; giving a different one is refused, `--repeat`
  may grow. The Claude Code and Orkestra versions are recorded per window (an update between
  windows is printed and kept in the report header).
- A repeat cut short by a stop is not scored (it would look like a low score); the table
  says how many runs were left out as partial.

Ollama must be running for B and C. Every run is written to `results/<date>.json` as it ends
(a crash keeps what was done) and the tables to `results/<date>.md`.

## Measures

- **Passed:** hidden tests pass. Every task runs `--repeat` times (models are not
  deterministic); the table shows the mean number of passed tasks and the min–max over the
  repeats.
- **Claude tokens per task:** input + output + cache creation from Claude Code's JSON;
  cache reads are kept apart. The primary measure: on a subscription the dollar figure is not
  what you pay. A run that reported no usage (a timeout, a crash) is left out of the token
  means, not counted as zero; their number is `runs_without_usage`.
- **Worker cost, runs, savings estimate:** from Orkestra's own records (`orkestra stats`) in
  the bench home, for the time of each run. The savings estimate (worker output tokens minus
  the envelope the chief read) is compared with the real difference in Claude tokens (A − B),
  which shows how far the `stats` counter can be trusted.

## Results

Each results file records the date, machine, Python, Claude Code version and model, Ollama
models and the Orkestra version. Ollama results depend on the hardware.

Measured 2026-11-20/21 on Windows 11, Intel i9-13900HX, 32 GB RAM, RTX 5070 Ti Laptop 12 GB;
Claude Code 2.1.329 (default model, Opus 5.5), agy 1.5.13, Ollama `qwen2.5-coder:14b`, short
skill (`b2d2eba2a206`, D-113).

| File | Modes | Passed | Claude tokens / task | Claude cost / task |
|---|---|---|---|---|
| `2026-11-20-0326` (13d, round 1, long skill) | A / B / C | 20 / 20 / 9 of 20 | 9.3k / 11.3k / – | – |
| `2026-11-20-2333` (13e, rounds 2–3) | A / B / C | 20 / 20 / 7.5 (7–8) of 20 | 9.1k / 11.4k / – | $0.117 / $0.136 / – |
| `2026-11-21-0013` (13e, `--worker agy`, 1 round) | D | 20 of 20 | 15.7k | $0.197 |
| `2026-11-20-2346` (13g, `--suite big`, 2 rounds) | A / F / G | 2 / 2 / 2 of 2 | 87.4k / 76.9k / 76.7k | $1.38 / $1.10 / $1.19 |

- B never delegated in any round: with the choice, Claude does small tasks itself, and the
  skill's fixed cost makes it ~25% dearer than A.
- D (told to delegate to agy) passes everything but costs Claude ~70% more than A on small
  tasks.
- On the big task the context filter (F) cut Claude's cache reads by 46% and its cost by 20%;
  G delegated in one of two runs, and that run cost more than A. The 13g target (≥ 25% fewer
  Claude tokens) was not met.
- Limits: one machine, one Claude model, Windows only; D one round, the big suite one task with
  two rounds; LLM runs vary between repeats (see min–max in each `.md`).
