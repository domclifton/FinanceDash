# InvestHome Architecture Refactor Plan

InvestHome is still intentionally packaged as a simple single-user self-hosted Flask app, but `app.py` is now large enough that future development will be easier if it is split.

This file is a framework for a future refactor. It is not a requirement to complete the split in one release.

## Goals

- Make feature areas easier to test.
- Reduce risk when changing Trading 212, bullion, debts, budget, property or progress logic.
- Keep the single-user self-hosted edition simple.
- Avoid accidentally turning the project into the multi-user hosted edition.

## Target Structure

```text
investhome/
├── app.py                    # Flask app factory and blueprint registration only
├── config.py                 # Paths, app version, constants, environment loading
├── db.py                     # SQLite connection, init_db, migrations, indexes
├── routes/
│   ├── dashboard.py
│   ├── accounts.py
│   ├── performance.py
│   ├── pension.py
│   ├── bullion.py
│   ├── property.py
│   ├── budget.py
│   ├── debts.py
│   ├── progress.py
│   ├── trading212.py
│   └── settings.py
├── services/
│   ├── accounts.py
│   ├── backups.py
│   ├── bullion.py
│   ├── charts.py
│   ├── debts.py
│   ├── performance.py
│   ├── progress.py
│   ├── property.py
│   └── trading212.py
└── templates/
```

## Recommended Order

1. Add smoke tests around key calculations before moving files.
2. Extract database path/config constants into `config.py`.
3. Extract backup/import/restore/undo helpers into `services/backups.py`.
4. Extract Trading 212 API and account reconciliation into `services/trading212.py`.
5. Extract performance chart builders into `services/performance.py`.
6. Move one Flask page at a time into `routes/` blueprints.
7. Keep each release small enough to test manually.

## Do Not Mix With

- Major UI redesigns.
- Multi-user account logic.
- Tenant/org/workspace concepts.
- Database engine migration.

## Current Patch-Level Decision

For v3.0.0-alpha.2, the v3 backend refactor has started with a low-risk `config.py` extraction. The current release should have no frontend, route, template, database schema or user-behaviour changes. Continue with one extraction per release.


## Current v3 Alpha Status

- v3.0.0-alpha.2: `config.py` extraction completed.
- Next planned extraction: `services/backups.py`.
- Treat v3.0.0 as the long-term single-user self-hosted release target.


## v3.0.0-beta.1 Progress

- Database layer extracted to `db.py`.
- Existing route connection lifecycle intentionally preserved for the first beta.
- GoldAPI Settings-based credential storage is deferred as a separate behaviour change.

## v3.0.0-beta.3 Progress

- First route blueprint extracted.
- Added `routes/settings.py` and `routes/__init__.py`.
- `/settings` and Settings database-management routes now live in the Settings blueprint.
- URL paths are intentionally unchanged.
- App-level bullion sync, snapshot creation and database init callbacks are injected into the blueprint to avoid circular imports.
- Next planned route extraction should be another contained page such as Debts or Progress.

## v3.0.0-beta.4 Progress

- Extracted the Debts routes into `routes/debts.py`.
- Added `services/debts.py` for debt summary and debt type helper logic.
- Registered the Debts blueprint without changing public URL paths.
