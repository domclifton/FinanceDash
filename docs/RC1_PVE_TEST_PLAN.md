# InvestHome v3.0.0-rc.1 PVE Test Plan

Use this checklist when testing the release candidate on a brand-new Proxmox/PVE LXC container.

## 1. Fresh install

```bash
apt update
apt install -y python3 python3-venv python3-pip git unzip
unzip investhome-v3.0.0-rc.1.zip
cd investhome-v3.0.0-rc.1
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 app.py
```

Open:

```text
http://SERVER-IP:5000
```

## 2. Optional smoke tests

```bash
source venv/bin/activate
pip install -r requirements-dev.txt
python3 -m pytest
```

## 3. Manual page checks

Load each page:

- Dashboard
- Accounts
- Performance
- Pension
- Bullion
- Property
- Budget
- Debts
- Compound Interest
- Trading 212
- Progress
- Settings

## 4. Database safety checks

In Settings → Database:

- Create a manual backup.
- Confirm it appears in the scrollable Available Backups list.
- Download the backup.
- Use an undo point after a test POST action.
- Confirm the app still loads after restore/undo.

## 5. GoldAPI checks

In Settings → Metal Pricing:

- Add or confirm a GoldAPI key if available.
- Set refresh mode to Manual only, Every 12 hours, or Daily.
- Click Sync Metal Prices Now.
- Confirm Bullion values update or fall back gracefully.

## 6. Trading 212 checks

In Settings → Trading 212:

- Confirm the note explains manual sync is used because the API is still beta.
- Add credentials if available.
- Use Sync Now.
- Confirm `Trading 212 ISA (Auto)` appears in Accounts and is read-only.

## 7. Long-running checks

Over a few days:

- Confirm daily snapshots work.
- Confirm GoldAPI does not hammer the API on normal page loads.
- Confirm backup retention keeps the list manageable.
- Confirm no unexpected 500 errors appear in Flask/Gunicorn logs.

## 8. Before final v3.0.0

Capture any issues found during testing and fix them as RC hotfixes, for example:

```text
v3.0.0-rc.1.1
v3.0.0-rc.1.2
```

Only promote to final `v3.0.0` after this release candidate has been stable in normal use.
