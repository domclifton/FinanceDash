# InvestHome AI Project Framework

Version: v2.7.5  
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
- Local databases such as `finance.db`
- `.env`
- Screenshots unless specifically requested
- Old release-note history unless needed
- Temporary patch/build files

## Versioning Rules

Use semantic-style versioning:

- Bug fix: patch bump, for example `2.7.3` → `2.7.5`
- Minor feature/UI improvement: minor bump, for example `2.7.5` → `2.8.0`
- Major architecture change: major bump, for example `2.8.0` → `3.0.0`

If the user does not specify the update type, make the smallest sensible bump and explain it.

## UI Preferences

- Keep the current modern, clean, rounded-card UI style.
- Keep the centered login design mostly unchanged.
- Show the version number under the snapshot button.
- If adding update notices, place them under the `Welcome back` text.
- Prefer CSS-only fixes for spacing and responsive layout where possible.

## Current v2.7.5 Notes

This clean self-hosted package includes:

- Reduced ZIP clutter
- `AI_PROJECT_FRAMEWORK.md` for continuity
- Larger Budget page `Total Assigned` and `Floating Left` values
- Previous v2.7.3 Accounts page notes-field removal
- Previous v2.7.3 card/box text auto-scaling

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
