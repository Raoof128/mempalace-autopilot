# MemPalace Autopilot

Automatic memory capture and context injection for [MemPalace](https://github.com/MemPalace/mempalace). Replaces claude-mem with semantic search, knowledge graph, and zero-friction auto-recording.

## Prerequisites

1. Install MemPalace: `pip install mempalace` (or `pipx install mempalace`)
2. Initialize: `mempalace init`
3. Create identity: Write `~/.mempalace/identity.txt` with your personal context
4. Verify: `mempalace status`

## Install

```bash
claude plugin add ./mempalace-autopilot
```

## Migrating from claude-mem

```bash
python3 mempalace-autopilot/scripts/migrate_claude_mem.py
# Verify: mempalace status && mempalace search "some known topic"
# Then: claude plugin remove claude-mem
```

## How It Works

- **SessionStart:** Injects ~800 tokens of relevant memory (project-scoped or global)
- **Stop:** Every ~15 messages, auto-captures conversation delta into MemPalace
- **PreCompact:** Emergency save before context compression
- **SessionEnd:** Captures final conversation delta

## Wing Detection

- In a git repo: wing = repo name (e.g., "Nexus")
- Not in a git repo: wing = "general"
- Room: auto-detected by MemPalace keyword scoring (technical/decisions/problems/milestones/general)

## Architecture

```
hooks/hook_runner.py     → single Python entry point for all lifecycle events
scripts/context_generator.py → smart budget ~800 token context builder
scripts/migrate_claude_mem.py → one-shot bulk import from claude-mem
```

All MemPalace interaction via `subprocess.run(["mempalace", ...])` — no direct Python imports, so it works regardless of how MemPalace is installed (pip, pipx, venv).
