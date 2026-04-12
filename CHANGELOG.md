# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-04-12

### Added
- `SessionStart` hook: injects ~800 tokens of project-scoped or global memories at session start
- `Stop` hook: captures conversation delta every 15 human messages
- `PreCompact` hook: emergency save before context compaction; blocks until MemPalace finishes
- `SessionEnd` hook: captures final conversation delta and cleans up session state
- `scripts/context_generator.py`: smart context builder with identity file support and fallback to global memories
- `scripts/migrate_claude_mem.py`: one-shot bulk import from claude-mem SQLite database with dry-run mode
- `shared/utils.py`: canonical `detect_wing()`, `scrub_secrets()`, and `SCRUB_PATTERNS` shared across modules
- Secret scrubbing for AWS, OpenAI, GitHub, Slack, Bearer, and generic key/value patterns
- Wing detection via git repository basename
- 103 unit tests with full mock coverage (no network or MemPalace required)
- MIT license

### Security
- All conversation content is scrubbed for secrets before reaching MemPalace
- Hooks use only `CLAUDE_PLUGIN_ROOT` — no hardcoded user paths
- DB copy uses `tempfile.mkstemp()` instead of a fixed `/tmp` path
