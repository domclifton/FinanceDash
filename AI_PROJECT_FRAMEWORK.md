# InvestHome AI Project Framework

Version: v2.8.4  
Edition: Single-User Self-Hosted

## Purpose

Use this file when importing the project into ChatGPT or another AI coding assistant. It gives the assistant enough continuity to make changes without drifting into the wrong architecture.

## Project Boundary

This repository/package is for the **single-user self-hosted InvestHome edition**.

Build for:

- One self-hosted owner/user or one household
- Local/homelab deployment
- Flask app structure
- SQLite as used by the current package unless the user explicitly requests a database migration
- Optional production-style deployment with Gunicorn and a reverse proxy
- Simple backups and restore-friendly files

Do **not** turn this edition into:

- A SaaS app
- A multi-tenant app
- A public registration platform
- An invite-code/user-management platform
- A billing/subscription product
- A workspace/organisation-based system

The separate multi-user/hosted edition is developed elsewhere.

## Current Packaging Rules

Every packaged update should:

- Use a folder named `investhome-vX.Y.Z`
- Update `APP_VERSION` in `app.py`
- Update `VERSION.txt`
- Update `README.md`
- Update `CHANGELOG.txt`
- Add or update a release note in `docs/`
- Keep unnecessary release clutter out of the ZIP

Avoid including:

- `__pycache__/`
- `.pytest_cache/`
- Virtual environments
- Local databases such as `data/finance.db`
- `.env`
- Screenshots unless specifically requested
- Old release-note history unless needed
- Temporary patch/build files

## Versioning Rules

Use semantic-style versioning:

- Bug fix: patch bump, for example `2.7.3` → `2.7.6`
- Minor feature/UI improvement: minor bump, for example `2.7.6` → `2.8.0`
- Major architecture change: major bump, for example `2.8.0` → `3.0.0`

If the user does not specify the update type, make the smallest sensible bump and explain it.

## UI Preferences

- Keep the current modern, clean, rounded-card UI style.
- Keep the centered login design mostly unchanged.
- Show the version number under the snapshot button.
- If adding update notices, place them under the `Welcome back` text.
- Prefer CSS-only fixes for spacing and responsive layout where possible.

## Current v2.8.4 Notes

This clean self-hosted package includes:

- Account Type now includes `Ignore`; ignored accounts remain visible in Account Balances but are excluded from dashboard statistics
- Trading 212 ISA (Auto) remains value-managed by the API, but the Type dropdown is user-editable and should not be overwritten by sync
- Property page has Include/Ignore control for whether property equity counts in total net worth
- Trading 212 Auto badge should render as normal non-italic text
- Lifetime ISA deposits no longer auto-add the 25% government bonus
- The LISA bonus should be recorded only when it actually appears in the provider account
- Use Update Total Value to record the real account value when the bonus lands
- LISA value updates remain growth/value changes rather than user contributions
- Reduced ZIP clutter
- `AI_PROJECT_FRAMEWORK.md` for continuity
- Larger Budget page `Total Assigned` and `Floating Left` values
- Previous v2.7.3 Accounts page notes-field removal
- Broad v2.7.3 card/box text auto-scaling was removed in v2.7.5

## Important Historical Fixes

Previous issue context:

- Couple budget names should display saved person names, not generic `Person 1` / `Person 2`, except as fallback values.
- Dashboard investment growth should not treat opening/imported balances as profit.
- Accounts page Add/Remove and Update Total Value forms should not show notes/reason fields.

## Before Returning a Package

Run at least:

```bash
python3 -m py_compile app.py
```

Also inspect the ZIP contents before handoff to make sure it does not include clutter.


## v2.8.0 Data Organisation Direction

- Runtime SQLite database path is `data/finance.db`.
- Keep runtime data and database backups out of the main project root.
- Settings -> Database includes backup, import, restore and undo-last-action tools.
- Backup filenames should include a date/time stamp.
- The app should create a database undo point before user POST actions where possible.
- Do not reintroduce root-level `finance.db` as the active database path.

## v2.8.4 Trading 212 Account Direction

- Trading 212 should not sync into a user-selected manual account.
- Trading 212 sync should create/update `Trading 212 ISA (Auto)`.
- Trading 212 sync owns the account value/name/category/provider metadata, but should preserve the user-selected Type dropdown once set.
- `Trading 212 ISA (Auto)` uses category `Stocks and Shares ISA`, default type `Mid Term`, `source_provider = trading212` and `is_auto_managed = 1`.
- Auto-managed rows remain visible in Account Balances so dashboard/net-worth totals include them unless Type is set to `Ignore`.
- Auto-managed rows must be value read-only: no add/remove, no update total value and no delete button. The Type dropdown is a local dashboard preference and is editable.
- Do not use broad category matching such as `Stocks and Shares ISA` as a sync target, because that can overwrite unrelated manual investment accounts.

## v2.8.3 Trading 212 Consistency Rule

The Trading 212 page, Account Balances, Dashboard, and Compound Interest must all use the same Trading 212 portfolio value. If a previous API sync exists in `trading212_settings`, reconcile that cached total into the `Trading 212 ISA (Auto)` account before rendering key pages. Old manual Trading212 ISA rows should be converted or archived to avoid duplicate counting.


## v2.8.3 Trading 212 Rule

Trading 212 uses a provider-managed account row named `Trading 212 ISA (Auto)`. Once Trading 212 has cached sync data, the app must recreate/update this row automatically even if an old manual Trading212 account was deleted or archived. Do not depend on category matching such as `Stocks and Shares ISA`, and do not require the legacy auto-update toggle for this provider-managed row.


## v2.8.4 Ignore / Net Worth Direction

- `TERM_TYPES` includes `Ignore`.
- Ignore keeps accounts visible on Accounts but excludes them from dashboard statistics and dashboard charts.
- Property settings include `include_in_net_worth`; when disabled, property equity stays visible on Property but is excluded from dashboard total net worth and allocation.
