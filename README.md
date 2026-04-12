# MemPalace Autopilot

A Claude Code plugin that gives every session persistent, project-aware memory. At session start it injects the most relevant memories into context; throughout the session it automatically captures conversation deltas into [MemPalace](https://github.com/MemPalace/mempalace) on a configurable interval and on every context compaction. Nothing leaks — secrets are scrubbed before anything is stored.

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| Claude Code | latest |
| MemPalace | `pip install mempalace` (or `pipx install mempalace`) |

After installing MemPalace:

```bash
mempalace init
mempalace status        # verify it's working
# Optionally write ~/.mempalace/identity.txt with a short personal bio
```

## Install

```bash
claude plugin add ./mempalace-autopilot
```

## Migrating from claude-mem

If you have existing memories in claude-mem, bulk-import them before uninstalling:

```bash
python3 scripts/migrate_claude_mem.py --dry-run   # preview what will be imported
python3 scripts/migrate_claude_mem.py             # run the actual import
mempalace status && mempalace search "some known topic"
claude plugin remove claude-mem
```

## How It Works

| Hook | Trigger | Action |
|---|---|---|
| `SessionStart` | Every new chat | Injects ~800 tokens of project-scoped or global memories |
| `Stop` | After each assistant turn | Every 15 human messages, captures conversation delta |
| `PreCompact` | Before context compression | Emergency save; blocks until MemPalace finishes |
| `SessionEnd` | Session close | Captures final delta; cleans up session state |

## Architecture

```
mempalace-autopilot/
├── hooks/
│   ├── hook_runner.py          # Single Python entry point for all lifecycle events
│   └── hooks.json              # Claude Code hook configuration
├── scripts/
│   ├── context_generator.py    # Assembles ~800-token memory block at session start
│   └── migrate_claude_mem.py   # One-shot bulk import from claude-mem SQLite DB
├── shared/
│   └── utils.py                # Canonical detect_wing(), scrub_secrets(), SCRUB_PATTERNS
└── tests/                      # 103 unit tests — no network, no MemPalace required
```

All MemPalace interaction uses `subprocess.run(["mempalace", ...])` — the plugin never imports MemPalace directly, so it works regardless of how MemPalace is installed (pip, pipx, venv, system).

### Wing Detection

The plugin uses the git repository name as the "wing" (namespace) for stored memories:

- Inside a git repo: wing = repo basename (e.g. `mempalace-autopilot`)
- Outside any git repo: wing = `general`

This means memories from different projects are automatically separated and the most relevant ones are surfaced first at session start.

## Security

All content is scrubbed for secrets before being sent to MemPalace. The scrubber targets:

- AWS access key IDs (`AKIA...`)
- OpenAI / Stripe secret keys (`sk-...`)
- GitHub tokens (`ghp_`, `gho_`, `github_pat_`)
- Bearer tokens
- Slack tokens (`xoxb-`, `xoxp-`, `xoxs-`)
- Generic `api_key=`, `secret=`, `token=`, `password=` patterns

Any match is replaced with `[REDACTED]` before the text leaves the plugin. See [SECURITY.md](SECURITY.md) for details on reporting vulnerabilities.

## Development

```bash
# Run tests (no external services needed)
python3 -m pytest tests/ -v

# Lint
pip install ruff
ruff check .
```

All tests use `unittest.mock` — MemPalace and git are fully mocked. The suite runs in under a second.

## License

MIT — see [LICENSE](LICENSE).
