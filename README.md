# InvestHome Finance Tracker v2.6.0 - AI SLOP WANRING

Self-hosted Flask + SQLite finance tracker with the major modern UI redesign and the Trading 212 fork features.

## Included
- Modern InvestHome light UI redesign
- Dashboard with total net worth including cash/assets, pension and property equity
- Accounts, transactions, performance, pension, property, bullion, budgets and compound interest
- Trading 212 read-only sync page
- Trading 212 GBX-to-GBP conversion fix
- Automatic once-per-day snapshot plus manual snapshot button
- VERSION.txt and CHANGELOG.txt

## Quick install

```bash
unzip finance_tracker_v2.6.0_trading212_modern_ui.zip
cd finance_tracker_v2.6.0_trading212_modern_ui
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

## Updating an existing install

Copy these files/folders over your existing app but keep your existing `finance.db` and `.env`:

```text
app.py
templates/
static/
requirements.txt
VERSION.txt
CHANGELOG.txt
```

Then restart Flask:

```bash
pkill -f "python3 app.py"
cd /root/weath
source venv/bin/activate
python3 app.py
```


Version v2.6.0 note:
- Navigation pages preload on hover/touch for faster perceived page loads.
- Trading 212 syncing is still manual to avoid API rate limits.
