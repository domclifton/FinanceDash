# InvestHome Finance Tracker v2.8.4

> **AI SLOP WARNING**  
> Built by a Network Engineer who has no business pretending to be a full-stack developer.

InvestHome is a self-hosted personal finance dashboard built with **Python**, **Flask** and **SQLite**. It is designed for homelab-style deployments where you want to own your own data and track the bits that most personal finance apps do not handle cleanly.


## What it tracks

- Total net worth across accessible assets, pension and property equity
- Emergency, liquid, short-term, mid-term, long-term and ignored account buckets
- Stocks and Shares ISA performance
- Lifetime ISA performance, with provider bonus/value changes treated as growth once they actually appear
- Pension tracking on a separate long-term view
- Physical bullion with optional live gold/silver pricing
- Property value, mortgage remaining and equity
- Budget calculator with Solo/Couple modes
- Compound interest projections
- Trading 212 read-only holdings sync, including GBX-to-GBP handling

## Current version

```text
v2.8.4
```

Highlights in this version:

- Runtime database moved from the project root to `data/finance.db`
- Existing root-level `finance.db` files are migrated automatically on first launch
- Settings now includes a Database subsection for backup, import, restore and undo-last-action
- Database backups are stored in `data/backups` with date-stamped filenames
- Undo support stores a pre-action copy in `data/undo` before user POST actions
- Packaged folder is versioned as `investhome-v2.8.4`
- Modern light InvestHome UI
- Safe page prefetching for faster navigation
- Trading 212 sync remains manual to avoid API rate limits
- Trading 212 sync now creates/updates `Trading 212 ISA (Auto)` instead of targeting manual account rows
- API-managed account values are read-only on the Accounts page and contribute to dashboard/net-worth totals unless their Type is set to `Ignore`
- Accounts can be marked with Type `Ignore` to keep them visible in Account Balances while excluding them from dashboard statistics
- Trading 212 ISA (Auto) keeps its synced value read-only, but its dashboard Type can now be changed using the same dropdown as manual accounts
- Property page now has Include/Ignore control for whether property equity appears in total net worth
- Version number displayed under the snapshot button
- `CHANGELOG.txt` included for release history

## Quick install

```bash
git clone https://github.com/domclifton/InvestHome.git
cd InvestHome
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

## Easier install script

```bash
chmod +x scripts/install.sh
./scripts/install.sh
```

Then start the app:

```bash
./scripts/start.sh
```

## Environment variables

Copy the example file:

```bash
cp .env.example .env
```

Optional values:

```env
GOLDAPI_KEY=
FLASK_SECRET_KEY=change-me
```

Trading 212 credentials are only needed if you want the read-only Trading 212 sync section. Enter them in Settings → Trading 212 Connection after launching the app. When synced, the app creates/updates `Trading 212 ISA (Auto)` in Account Balances.

## Updating an existing install

Keep these files:

```text
data/finance.db
.env
```

For older installs, if `finance.db` still exists in the project root, v2.8.4 will move it to `data/finance.db` automatically on first launch.

Then pull/copy the new app files over the top and restart Flask.

Before updating, back up your database:

```bash
./scripts/backup_db.sh
```

You can also create and restore dated backups from Settings → Database.

## Running as a service

A sample systemd unit is included here:

```text
systemd/investhome.service
```

Typical install path:

```text
/opt/investhome
```

Example:

```bash
sudo cp systemd/investhome.service /etc/systemd/system/investhome.service
sudo systemctl daemon-reload
sudo systemctl enable investhome
sudo systemctl start investhome
sudo systemctl status investhome
```

Edit the paths inside the service file if your install path is different.

## Production note

`python3 app.py` runs Flask's development server. That is fine for homelab testing, but for a more production-like setup use a WSGI server such as Gunicorn behind Nginx, Caddy or Traefik.

See:

```text
docs/DEPLOYMENT.md
```

## Data safety

Do not commit these files:

```text
.env
data/finance.db
data/backups/*.db
data/undo/*.db
```

They are ignored in `.gitignore`.

## Disclaimer

This is a personal finance tracker, not financial advice. Check calculations before relying on them for anything important.
