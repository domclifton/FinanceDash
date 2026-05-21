# InvestHome v2.7.4

Single-user self-hosted cleanup and Budget readability release.

## Changes

- Renamed package folder to `investhome-v2.7.4`.
- Removed unnecessary ZIP clutter to keep the release package easier to import, browse, and deploy.
- Added `AI_PROJECT_FRAMEWORK.md` so future AI-assisted imports have continuity and stay aligned with the single-user self-hosted edition.
- Added `.env.example` so the included install script works cleanly on a fresh install.
- Increased Budget page `Total Assigned` and `Floating Left` values in metric cards and table totals.
- Kept previous Accounts page notes-field removal and box text auto-scaling changes.

## Removed from release ZIP

- Screenshot files
- `__pycache__` / generated Python artefacts
- Old release-note history
- GitHub housekeeping files not needed for self-hosted install

## Test

```bash
python3 -m py_compile app.py
```
