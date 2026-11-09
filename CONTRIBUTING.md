# Contributing to PulseForge

PulseForge is a self-hosted service monitor. Changes should improve behavior, reliability, usability, or operability rather than add complexity for its own sake.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check app tests
```

Start the app with `uvicorn app.main:app --reload` and visit `http://localhost:8000`.

## Change workflow

1. Describe the problem and expected behavior before changing code.
2. Add or update regression tests. Use `TestClient` for the API and mock HTTP dependencies only in tests.
3. Keep persistence changes transactional; `initialize()` must work with databases created by earlier versions.
4. Think about security when changing URL validation, outbound HTTP behavior or exported data.
5. Run tests and lints, then confirm the behavior using the local demo service if relevant.
6. Explain the reasoning and any trade-offs in a pull request or short design note.

## Good next tasks

- Maintenance windows with alert suppression and boundary tests.
- Per-monitor 7-day and 30-day history with efficient aggregation.
- Change history for configuration updates.
- A database migration mechanism before introducing larger schema changes.

Avoid committing `.env`, local SQLite databases, access tokens or unrelated generated files. See [security](docs/security.md) and [roadmap](docs/roadmap.md).
