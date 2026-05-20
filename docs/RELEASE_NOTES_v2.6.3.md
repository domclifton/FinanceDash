# InvestHome v2.6.3 Release Notes

## Summary
This release fixes a dark-mode dropdown rendering issue where repeated V-shaped chevrons could appear inside select boxes.

## Changes
- Removed Bootstrap/custom select SVG background images from dropdown fields.
- Added stronger select styling for light and dark themes.
- Updated app versioning to force browsers to fetch the corrected CSS.

## Testing Notes
- Verify Account Balances dropdowns in dark mode.
- Verify Settings dropdowns in dark mode.
- Hard-refresh the browser once after deployment if stale CSS is still visible.
