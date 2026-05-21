# InvestHome v2.8.4 Release Notes

## Type
Bug fix / small UX release for the single-user self-hosted edition.

## Changes

- Trading 212 `Auto` badge now uses normal non-italic text.
- `Trading 212 ISA (Auto)` now has the same Type dropdown as other accounts.
- Trading 212 sync still controls the synced account value, but no longer overwrites the locally selected Type once set.
- Added new account Type option: `Ignore`.
- Accounts marked as `Ignore` remain visible on the Accounts page but are excluded from dashboard statistics, allocation and net-worth chart calculations.
- Property page now has a net worth treatment selector:
  - Include in total net worth
  - Ignore from total net worth
- Ignored property equity remains visible on the Property page but is excluded from dashboard total net worth and allocation.

## Expected behaviour

```text
Trading 212 ISA (Auto):
- Value updates from Trading 212 sync
- Add/remove and manual value update remain disabled
- Type dropdown can be changed to Mid Term, Long Term, Ignore, etc.

Ignore account Type:
- Account remains visible in Account Balances
- Account is excluded from dashboard totals/statistics

Property Ignore option:
- Property page still stores home value, mortgage left and equity
- Dashboard total net worth excludes property equity when ignored
```
