# Contributing

Thank you for your interest in contributing to MemPalace Autopilot.

## Getting Started

1. Fork the repository and create a feature branch.
2. Install development dependencies:

   ```bash
   pip install pytest ruff
   ```

3. Make your changes. If you add new logic, add corresponding tests in `tests/`.

## Running Tests

```bash
python3 -m pytest tests/ -v
```

All 103 tests must pass before submitting a pull request. The test suite requires no network access and no MemPalace installation — everything is mocked.

## Code Style

This project uses [Ruff](https://docs.astral.sh/ruff/) for linting:

```bash
ruff check .
```

Key conventions:
- Line length: 100 characters
- Python 3.10+ syntax (`str | None`, `match`, etc.)
- No bare `except:` clauses — always catch specific exceptions or `Exception`
- Silent failures in hook handlers (hooks must never block Claude Code)

## Shared Utilities

If you add a new secret pattern or utility used by more than one module, add it to `shared/utils.py` rather than duplicating it.

## Pull Request Checklist

- [ ] All existing tests pass
- [ ] New functionality has test coverage
- [ ] No hardcoded paths or usernames
- [ ] Secrets are scrubbed before any external call
- [ ] `ruff check .` passes
