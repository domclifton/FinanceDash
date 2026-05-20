# InvestHome v2.6.2 Release Notes

## Summary
This release adds dark mode support and moves the theme control into Settings > Appearance.

## Changes
- Added light/dark theme selection in Settings.
- Saved the selected theme locally in the browser with localStorage.
- Used the system colour scheme as the default when no theme preference exists.
- Added dark mode styling for the main layout, sidebar, panels, cards, tables, forms, alerts, charts, and dashboard widgets.
- Added stylesheet cache-busting using the app version so upgraded CSS loads correctly.

## Upgrade notes
After updating, refresh the browser once. If an old stylesheet is still cached, perform a hard refresh.
