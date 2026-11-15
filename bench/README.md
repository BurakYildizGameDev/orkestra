# Benchmark

Does handing work to cheap or local workers save the chief's tokens without losing quality?
This folder measures it. Results go to `results/`; the main README shows the latest table,
including the bad results.

## Modes

| Mode | Who works | How |
|---|---|---|
| A – Claude only | Claude Code | `claude -p "<task>" --output-format json`, no skills (`--disable-slash-commands`), no MCP servers (`--strict-mcp-config`) |
| B – Claude + Orkestra skill | Claude Code as chief, Orkestra workers | the same, with the Orkestra skill in the workspace (`.claude/skills/orkestra/SKILL.md`), permission to run `orkestra`, and a short hint to delegate when it fits, put before the task text |
| C – Orkestra only (cheap) | Orkestra, no chief | `orkestra run <task> --profile cheap --json`; a passing run is applied with `orkestra apply` |

A and B use `--setting-sources project`, so personal settings, hooks and memory do not take
part, and the same tool permissions: read, edit, write, search, `python`, `pytest`, `git`
(B also `orkestra`). The task text goes to Claude on **stdin** and the permissions in a
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
tier-2 model; only mode B can use it, when Claude asks for tier 2: mode C runs the `cheap`
profile, tier 1), `--claude-model`, `--timeout` (per run, default 900 s), `--work-dir`,
`--out`. If the leak guard trips, the whole benchmark stops (exit code 3): it is never counted
as a model failure.

Modes A and B use your Claude Code quota: a full run is 120 Claude sessions, more than one
5-hour window. So a run can be split:

```bash
uv run python bench/run_bench.py --mode all --repeat 1 --max-claude-runs 10   # this window
uv run python bench/run_bench.py --resume bench/results/<date>.json --max-claude-runs 10
uv run python bench/run_bench.py --resume bench/results/<date>.json --repeat 3  # add repeats
```

- `--max-claude-runs N` starts at most N Claude sessions in this call, then stops cleanly.
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

Not run yet (Faz 13b). Each results file records the date, machine, Python, Claude Code
version and model, Ollama models and the Orkestra version. Ollama results depend on the
hardware.
