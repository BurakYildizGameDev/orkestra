# Orkestra

Budget-aware CLI that dispatches tasks to multiple AIs (Ollama, OpenAI-compatible APIs,
Codex / Antigravity CLI) under one chief model, with automatic verification and escalation.

> Status: early development (Phase 0 – project skeleton). See [`docs/PROGRESS.md`](docs/PROGRESS.md).

```bash
uv sync
uv run orkestra --help
uv run orkestra --lang tr --help
```

## Documentation

- `docs/PROJE_DOKUMANTASYONU.md`, `docs/YAPILIS_PLANI.md` – architecture and build plan (Turkish, local working copies, not tracked in git)
- [`docs/PROGRESS.md`](docs/PROGRESS.md) – what is done
- [`docs/DECISIONS.md`](docs/DECISIONS.md) – deviations from the plan
- [`AGENTS.md`](AGENTS.md) – rules for coding agents

The package is published as `orkestra-cli`; the command is `orkestra`.

## License

MIT
