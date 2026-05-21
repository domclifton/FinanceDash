# InvestHome v2.7.5

## Type

Bug fix / UI rollback

## Summary

This release removes the broad CSS auto-scaling change that was introduced in v2.7.3 because it affected more parts of the UI than intended.

## Changes

- Removed the v2.7.3 broad card/box text auto-scaling block from `static/style.css`.
- Kept the targeted v2.7.4 Budget page readability styling for Total Assigned and Floating Left.
- Updated the release folder name to `investhome-v2.7.5`.
- Updated `APP_VERSION`, `VERSION.txt`, README, install notes, changelog, AI framework, and release notes.

## Test

```bash
python3 -m py_compile app.py
```
