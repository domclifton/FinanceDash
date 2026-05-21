# InvestHome v2.8.3 Release Notes

## Type
Bug fix release for the single-user self-hosted edition.

## Fixes

- Trading 212 Account Balances row is now always recreated from cached Trading 212 sync data.
- Removed reliance on the legacy Auto-update account value toggle.
- If a manual `Trading212 ISA` row was deleted/archived, the app will create a fresh `Trading 212 ISA (Auto)` row on Accounts, Dashboard, Compound Interest, or a new Trading 212 sync.
- Fresh Trading 212 syncs now always update the read-only auto-managed account row.
- Settings wording now explains that the Trading 212 row is provider-managed and recreated automatically.

## Expected behaviour

After a Trading 212 sync exists:

```text
Trading 212 page:        cached synced total
Account Balances:        Trading 212 ISA (Auto), read-only, same value
Compound Interest:       Trading 212 ISA (Auto), same value
Dashboard/net worth:     includes the same auto-managed value
```

## Notes

The old `auto_update_account` database column remains for compatibility, but the app forces it on for Trading 212 because this integration now owns its own read-only Account Balances row.
