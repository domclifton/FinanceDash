# InvestHome v2.6.4 Release Notes

## Trading 212 credentials in Settings

This release adds a settings-page workflow for Trading 212 API credentials. Users can now enter their Trading 212 API key and secret directly in **Settings → Trading 212 Connection** rather than editing `.env` manually.

### Added
- API key and API secret inputs in the Trading 212 settings panel.
- Local database storage for saved Trading 212 credentials.
- Credential status/source display showing whether credentials come from Settings, `.env`, or are missing.
- Clear-saved-credentials checkbox.
- `.env` fallback support for existing self-hosted installs.

### Security note
Credentials are hidden after saving and are not written to sync logs. This remains a self-hosted, single-user style workflow; protect the app and database file appropriately.
