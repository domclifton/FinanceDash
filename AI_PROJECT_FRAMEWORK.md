# InvestHome AI Project Framework

Version: v3.0.0-rc.1  
Edition: Single-User Self-Hosted

## Purpose

Use this file when importing the project into ChatGPT or another AI coding assistant. It gives the assistant enough continuity to make changes without drifting into the wrong architecture.

## Latest v3.0.0-rc.1 Notes

- v3.0.0-rc.1 is the release candidate for extended testing before final v3.0.0. It is package-cleanup focused and has no intended behaviour changes from the last stable beta.
- This is a small UI/layout polish release only; backup, restore, import and undo behaviour is unchanged.
- GoldAPI cached pricing and manual sync behaviour from v3.0.0-beta.7.1 remains unchanged.
- Trading 212 remains manual-sync only while the API is still in beta.

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
- Update `APP_VERSION` in `config.py`
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
- Keep the Take Snapshot button in the sidebar below the All data is synced card.
- Keep the visible version number at the bottom-left of the sidebar.
- If adding update notices, place them under the `Welcome back` text.
- Prefer CSS-only fixes for spacing and responsive layout where possible.

## Current v2.9.2 Notes

This clean self-hosted package includes:

- Dashboard Type cards should show the accounts that make up each bucket, for example Emergency = Premium Bonds, Emergency Fund.
- Manual account names can be edited inline on Account Balances.
- Auto-managed provider account names remain provider-controlled/read-only.
- Snapshot control now lives in the sidebar under the sync-status card.
- Version label now sits at the bottom-left of the sidebar.
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

- Progress page exists as the first draft of the savings gamification idea.
- Progress page should include score cards, Financial Levels, UK Benchmarks, Monthly Challenge, and Badges on the same page.
- UK benchmark values are static/configurable in this draft; do not add live ONS ingestion unless requested as a later feature.
- Badges are calculated from current local data rather than stored as permanent history in v2.9.0.

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

## v3.0.0 Backend Refactor Direction

- v3.0.0 is a major backend refactor and the intended long-term self-hosted foundation.
- Keep frontend behaviour stable unless the user explicitly requests UI changes.
- Step 1 is complete in v3.0.0-alpha.1: configuration constants were extracted to `config.py`.
- Step 2 is complete in v3.0.0-alpha.2.1: backup/import/restore/undo/database storage helpers were extracted to `services/backups.py`.
- Step 3 is complete in v3.0.0-alpha.3: pytest smoke tests were added under `tests/`.
- Step 4 is complete in v3.0.0-alpha.4: Trading 212 API/cache/account-sync logic was extracted to `services/trading212.py`.
- Step 5 is complete in v3.0.0-alpha.5: performance/chart logic was extracted to `services/performance.py`.
- Step 6 is complete in v3.0.0-beta.1.1: database connection, settings helpers and schema migrations were extracted to `db.py`.
- Next intended step: begin route blueprint extraction, starting with a low-risk page such as Settings.
- One extraction per release. Each release should be easy to test and should avoid behaviour changes.

## v2.8.3 Trading 212 Consistency Rule

The Trading 212 page, Account Balances, Dashboard, and Compound Interest must all use the same Trading 212 portfolio value. If a previous API sync exists in `trading212_settings`, reconcile that cached total into the `Trading 212 ISA (Auto)` account before rendering key pages. Old manual Trading212 ISA rows should be converted or archived to avoid duplicate counting.


## v2.8.3 Trading 212 Rule

Trading 212 uses a provider-managed account row named `Trading 212 ISA (Auto)`. Once Trading 212 has cached sync data, the app must recreate/update this row automatically even if an old manual Trading212 account was deleted or archived. Do not depend on category matching such as `Stocks and Shares ISA`, and do not require the legacy auto-update toggle for this provider-managed row.


## v2.8.4 Ignore / Net Worth Direction

- `TERM_TYPES` includes `Ignore`.
- Ignore keeps accounts visible on Accounts but excludes them from dashboard statistics and dashboard charts.
- Property settings include `include_in_net_worth`; when disabled, property equity stays visible on Property but is excluded from dashboard total net worth and allocation.

## v2.9.2 Debt and Progress Notes

- Debts are tracked separately from asset accounts on the Debts page.
- Included debts reduce dashboard net worth; ignored debts remain visible but do not affect net worth/statistics.
- Property mortgage remains handled on the Property page because it is tied to property equity.
- Progress Settings include helper text and the playful honesty reminder: "Honesty mode: ON. Fudging the numbers only unlocks imaginary badges 😉".
- Keep badges on the Progress page for now; do not split them into a separate page yet.

## v2.9.4 Architecture / Quality Notes

- Current app remains a single Flask file for compatibility in this patch release.
- Planned split:
  - `app.py` for app factory, config and blueprint registration.
  - `routes/` for dashboard, accounts, budget, debts, performance, progress, settings and integrations pages.
  - `models/` or `services/` for database helpers and domain logic such as bullion, Trading 212, property, debts, backups and progress calculations.
- Do the split incrementally after tests exist; do not combine it with feature work.
- Backup retention target: newest 30 files in `data/backups`.
- Undo retention target: newest 5 files in `data/undo`.

## v3.0.0-beta.6.1 Refactor Note

The v3 backend refactor has now extracted these route blueprints: Settings, Debts, Progress, Property, Budget, Accounts and Trading 212. Dashboard, Bullion, Performance/Pension, Compound Interest, Snapshot and CSV export routes remain in `app.py` for a later release candidate cleanup/testing pass.



## v3.0.0-beta.7.2 Trading 212 manual sync note

Settings → Trading 212 includes a note that auto sync is not enabled because the Trading 212 API is still in beta. Trading 212 remains manual-sync via Sync Now.
