# MemPalace Autopilot

A Claude Code plugin that gives every session persistent, project-aware memory. At session start it injects the most relevant memories into context; throughout the session it captures conversation deltas into [MemPalace](https://github.com/MemPalace/mempalace) every 15 human messages and on every context compaction. Before anything is stored, the text goes through a pattern-based secret scrubber; [Security](#security) lists what it catches and what it cannot.

**Status:** version 1.0.0, written in April 2026 against MemPalace's command line (`mempalace wake-up`, `mempalace mine`). The automated tests mock MemPalace and git, so they show that the plugin's own logic works, not that it works with any particular MemPalace release.

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
git clone https://github.com/Raoof128/mempalace-autopilot.git
claude --plugin-dir ./mempalace-autopilot
```

`--plugin-dir` loads the plugin for that session. The repository has no marketplace manifest yet, so `claude plugin install` does not apply. `claude plugin validate ./mempalace-autopilot` checks the manifest and hooks.

The plugin also declares MemPalace's MCP server in `.mcp.json` as `python3 -m mempalace.mcp_server`. That needs `mempalace` to be importable by the `python3` on your `PATH`, which is not the case for a pipx install. The hooks do not depend on it: they call the `mempalace` command.

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
| `SessionStart` | Every new chat | Injects project-scoped or global memories, capped at 3,200 characters (about 800 tokens) |
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
└── tests/                      # 108 unit tests — no network, no MemPalace required
```

The hooks and scripts reach MemPalace only through `subprocess.run(["mempalace", ...])` and never import it, so they need the `mempalace` command on `PATH` and nothing else (pip, pipx, venv or system install).

### Wing Detection

The plugin uses the git repository name as the "wing" (namespace) for stored memories:

- Inside a git repo: wing = repo basename (e.g. `mempalace-autopilot`)
- Outside any git repo: wing = `general`

This means memories from different projects are automatically separated and the most relevant ones are surfaced first at session start.

## Security

Captured text is passed through a scrubber before it is sent to MemPalace. The scrubber is a list of regular expressions in `shared/utils.py`. It targets:

- AWS access key IDs (`AKIA...`)
- Anthropic keys (`sk-ant-...`) and OpenAI keys (`sk-...`, `sk-proj-...`)
- Stripe secret and restricted keys (`sk_live_`, `sk_test_`, `rk_live_`, `rk_test_`)
- GitHub tokens (`ghp_`, `gho_`, `github_pat_`)
- Bearer tokens
- Slack tokens (`xoxb-`, `xoxp-`, `xoxs-`)
- Generic `api_key=`, `secret=`, `secret_access_key=`, `token=`, `password=` assignments

Any match is replaced with `[REDACTED]` before the text leaves the plugin.

**Limits.** This is pattern matching, not a guarantee. A secret in a format that is not listed (a private key block, a database URL with a password, a token with an unusual prefix) is stored as it is. Treat the memory store as sensitive.

See [SECURITY.md](SECURITY.md) for how to report a vulnerability.

## Development

```bash
# Run tests (no external services needed)
python3 -m pytest tests/ -v

# Lint
pip install ruff
ruff check .
```

All tests use `unittest.mock`: MemPalace and git are mocked. The suite takes a few seconds, and CI runs it with `ruff check` on Python 3.10 and 3.12.

## License

MIT — see [LICENSE](LICENSE).
