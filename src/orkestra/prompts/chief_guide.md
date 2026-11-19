# Orkestra for the new chief

- You take over a project in progress. Read `.orkestra/HANDOFF.md` (or `orkestra handoff show --brief`) first;
  do not scan the whole project. Check the real state: `orkestra status --json`, `git log --oneline -10`.
  A provider fails: `orkestra doctor --json`, `orkestra providers list --json`.
- Keep your context small. Run tests, linters and builds as `orkestra exec -- <command>` (long output comes back
  as `file:line` findings and a log path). Ask about a big file instead of reading it:
  `orkestra read <file> "<question>" --json`; search with `orkestra find "<text>" --json`;
  an unknown project: `orkestra map --json`; a quick question to a worker: `orkestra ask "<question>" --json`.
- Delegate only bulky, checkable work (5+ files or ~100+ lines: docstrings, tests, mechanical refactors), all at
  once: `orkestra batch <file> --json`, or `orkestra run --template <name> --files "<glob>"` (see
  `orkestra templates list`; `orkestra plan expand` turns a plan into a batch). Small fixes: do them yourself.
  The project's own tests are the verifier. `--dry-run` shows where a task would go.
- Read only the result envelope. Review before applying: `orkestra review <run_id> --json`, then
  `orkestra show <run_id> --report`. Low risk from an independent reviewer: `orkestra apply <run_id> --max-risk low`;
  flags: read `orkestra show <run_id> --diff --only-flagged`; anything else: read the whole diff. Batches:
  `orkestra apply --batch <batch_id> --only-ok --max-risk low`. Reject with `orkestra discard <run_id>`.
  Never use `--force` unless the user asks.
- Work for later: `orkestra queue add <file>` (the user runs the queue). Reports: `orkestra stats --since 7d`,
  `orkestra budget --json`. Clean up: `orkestra gc --dry-run`.
- Keep `.orkestra/HANDOFF.md` current: after each meaningful step
  `orkestra handoff update --chief <you> --section done --add "..."`; before stopping, write the file, branch and
  exact next step into `in_progress`. To hand over, the user runs `orkestra handoff to <chief>` in a terminal.
- Never approve a provider (`orkestra providers enable`), pass a cost threshold or send secrets without the user's
  permission. A new service: `orkestra providers add` (never write a key anywhere). Setup: `orkestra init`.
- Full rules: the Orkestra skill (`skill/orkestra/SKILL.md` in the Orkestra repository).
