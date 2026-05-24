# InvestHome v3.0.0-rc.1

Release candidate for the long-term single-user self-hosted InvestHome v3 release.

## Purpose

This package is intended for extended testing on a clean Proxmox/PVE container before the final v3.0.0 release.

## What changed from v3.0.0-beta.7.3

- Bumped application version to `3.0.0-rc.1`.
- Cleaned the release package by removing historical per-version release-note files from `docs/`.
- Added a clean-install RC test plan for a fresh PVE/LXC deployment.
- No intended UI, database schema, route, calculation, backup, GoldAPI, Trading 212, or account-behaviour changes.

## Stable features carried forward

- v3 backend refactor structure: `config.py`, `db.py`, `services/`, and `routes/`.
- Settings, Debts, Progress, Accounts, Budget, Property and Trading 212 blueprints.
- GoldAPI key management from Settings with `.env` fallback.
- GoldAPI cached pricing with manual/12-hour/daily refresh options.
- Trading 212 manual sync with auto-managed account row.
- Database backups, restore, import and 5-point undo buffer.
- Scrollable Settings backup list.

## Testing target

Run this release for a while on a fresh container and validate real-world usage:

- Dashboard loads and values look correct.
- Accounts add/update/archive works.
- Budget pages work.
- Debts add/update/archive works.
- Progress settings save correctly.
- Property settings save correctly.
- Bullion add/delete and metal-price sync work.
- Trading 212 manual sync works.
- Database backup, restore, import and undo work.
- Snapshot button works.
- Smoke tests pass in the app virtual environment.

## Suggested commit

```bash
git add .
git commit -m "Prepare v3.0.0 release candidate"
```
