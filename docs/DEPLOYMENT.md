# InvestHome Deployment Notes

## Basic LXC / VM install

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git

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

## Recommended folder layout

```text
/opt/investhome
├── app.py
├── data/finance.db
├── .env
├── templates/
├── static/
└── venv/
```

## Systemd service

A sample service file is included:

```text
systemd/investhome.service
```

Copy it:

```bash
sudo cp systemd/investhome.service /etc/systemd/system/investhome.service
sudo systemctl daemon-reload
sudo systemctl enable investhome
sudo systemctl start investhome
```

Check logs:

```bash
journalctl -u investhome -f
```

## Reverse proxy idea

You can put this behind Nginx, Caddy or Traefik.

Example upstream:

```text
http://127.0.0.1:5000
```

## Backup

The app stores its data in SQLite:

```text
data/finance.db
```

Back it up before updates:

```bash
./scripts/backup_db.sh
```

Backups are placed in:

```text
backups/
```

## Trading 212

Trading 212 sync is intentionally manual. The app should not call Trading 212 during page prefetch or ordinary page loads. This helps avoid rate limits. Sync updates the provider-managed `Trading 212 ISA (Auto)` account row rather than a manually selected account.
