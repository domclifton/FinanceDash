# InvestHome v2.6.5

## Trading 212 settings UX refinement

This release simplifies the Trading 212 credentials form in Settings.

### Changes
- Removed the clear-saved-credentials checkbox from Trading 212 Connection settings.
- Saving credentials now overwrites the existing saved app-database credentials.
- Blank API key/API secret fields keep the current saved value or continue using the `.env` fallback.

### Notes
- Existing `.env` support is unchanged.
- No portfolio, account, or transaction data is modified by this change.
