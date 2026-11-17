# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- The secret scrubber missed three key formats: Anthropic keys (`sk-ant-...`) and OpenAI project keys (`sk-proj-...`), whose bodies contain `-` and `_`, and Stripe keys (`sk_live_...`, `sk_test_...`, `rk_...`), which use underscores. Outside a `key=value` form they were stored unredacted. An AWS secret access key next to its usual name (`aws_secret_access_key=...`) was missed too. Patterns and five tests added (108 tests).
- `hooks/hooks.json`: `${CLAUDE_PLUGIN_ROOT}` is now quoted, so a plugin path that contains a space no longer breaks the hook commands (`claude plugin validate` warning).
- `ruff check .` now passes: unused imports and variables removed, long lines wrapped. No behaviour change.

### Changed
- README: the install command is `claude --plugin-dir` (`claude plugin add` is not a command); the claim that "nothing leaks" is replaced with what the scrubber catches and its limits; the status section says what the mocked tests do and do not show; the bundled `.mcp.json` requirement is stated.
- `plugin.json` description no longer lists MemPalace's own features as the plugin's.

### Added
- GitHub Actions workflow: `ruff check` and the test suite on Python 3.10 and 3.12.

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
