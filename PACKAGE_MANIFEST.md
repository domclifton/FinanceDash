# InvestHome v3.0.0-rc.1 Package Manifest

This release package is intentionally cleaner than the beta packages.

## Included

- Core app files: `app.py`, `config.py`, `db.py`, `utils.py`
- Route modules: `routes/`
- Service modules: `services/`
- Templates: `templates/`
- Static assets: `static/`
- Runtime folder placeholder: `data/.gitkeep`
- Install/runtime files: `requirements.txt`, `.env.example`, scripts and systemd unit
- Smoke tests: `tests/` and `requirements-dev.txt`
- Current docs: `README.md`, `CHANGELOG.txt`, `INSTALL_FOR_FRIEND.txt`, `AI_PROJECT_FRAMEWORK.md`, `docs/`

## Excluded from the release ZIP

- `finance.db`
- `.env`
- Database backups
- Database undo files
- `__pycache__/`
- `.pytest_cache/`
- Historical per-version release note files from old beta/alpha releases

## Runtime data location

The live SQLite database is expected at:

```text
data/finance.db
```

If an older root-level `finance.db` exists, the app migration/storage helper moves it into the `data/` folder.
