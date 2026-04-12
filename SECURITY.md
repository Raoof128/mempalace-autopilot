# Security Policy

## Secret Scrubbing

MemPalace Autopilot scrubs all conversation content before storing it in MemPalace. The following patterns are detected and replaced with `[REDACTED]`:

| Pattern | Example |
|---|---|
| AWS access key IDs | `AKIA[0-9A-Z]{16}` |
| OpenAI / Stripe keys | `sk-[A-Za-z0-9]{20,60}` |
| GitHub tokens | `ghp_`, `gho_`, `github_pat_` |
| Bearer tokens | `Bearer <token>` in headers or env vars |
| Slack tokens | `xoxb-`, `xoxp-`, `xoxs-` |
| Generic secrets | `api_key=`, `secret=`, `token=`, `password=`, `passwd=`, `pwd=` followed by a value |

The canonical patterns live in `shared/utils.py` and are shared across all plugin modules to ensure consistent coverage.

## Scope

The scrubber covers conversation transcripts captured by the `Stop`, `PreCompact`, and `SessionEnd` hooks, as well as all content migrated by `scripts/migrate_claude_mem.py`. It runs before any data reaches MemPalace.

## Reporting a Vulnerability

If you discover a secret-leakage vector or any other security issue, please open a private GitHub Security Advisory on this repository. Do not create a public issue. You can expect an initial response within 72 hours.
