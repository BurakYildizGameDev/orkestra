# Orkestra for the new chief

- You are taking over a project in progress. Read `.orkestra/HANDOFF.md` first; it is the
  project's memory (goal, status, decisions, what is half done).
- Check the real state before trusting it: `orkestra status --json` (unapplied runs, budget,
  paused providers) and `git log --oneline -10` / `git status --short`.
- Delegate mechanical work to Orkestra (`orkestra run <task.yaml> --json`, `orkestra batch`).
  Read only the result envelope; open the diff (`orkestra show <run_id> --diff`) before
  `orkestra apply <run_id>`.
- Keep `.orkestra/HANDOFF.md` current: after each meaningful step,
  `orkestra handoff update --chief <you> --section done --add "..."`; before stopping, write
  the file, branch and the exact next step into `in_progress`.
- Never approve a provider or exceed a cost threshold without the user's permission.
