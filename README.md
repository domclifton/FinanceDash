# Self-hosted Finance Tracker

A small Flask + SQLite finance dashboard for tracking:

- Emergency Fund
- Cash ISA
- Stocks and Shares ISA
- Premium Bonds
- Physical Bullion

Includes:

- Dark Investbrain-inspired dashboard
- Add/remove transactions
- Daily snapshots
- Net worth chart
- Category allocation chart
- Physical bullion inventory
- Live GoldAPI support with manual fallback prices
- CSV export

## Install on Debian/Ubuntu LXC

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git

mkdir -p ~/finance-tracker
cd ~/finance-tracker

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

## Optional GoldAPI

Edit `.env`:

```bash
GOLDAPI_KEY=your_key_here
```

If no API key is set, go to **Settings** and set manual gold/silver GBP per gram fallback prices.

## Systemd service

Create:

```bash
sudo nano /etc/systemd/system/finance-tracker.service
```

Paste, changing `/root/finance-tracker` if needed:

```ini
[Unit]
Description=Finance Tracker Flask App
After=network.target

[Service]
User=root
WorkingDirectory=/root/finance-tracker
Environment="PATH=/root/finance-tracker/venv/bin"
ExecStart=/root/finance-tracker/venv/bin/python /root/finance-tracker/app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now finance-tracker
sudo systemctl status finance-tracker
```

## Notes

- `finance.db` is created automatically on first run.
- Bullion value is automatically reflected in the Physical Bullion account.
- Use **Take Snapshot** to write today's net worth/category balances for charts.

## Latest UI / Bullion update

This version uses a lighter modern UI.

Bullion purchase cost is optional:
- Fill in name, metal, weight, purity and quantity.
- Leave cost blank if you do not know what you paid.
- The app will calculate the starting cost using the current GoldAPI price or your manual fallback price from Settings.

If updating an existing install, copy the new files over your current app folder and restart Flask. Your existing `finance.db` can stay in place.

## Performance Tracking Upgrade

This version adds:

- A new Performance page
- Contributions vs growth/change tracking
- Monthly contributions vs valuation-change chart
- Ability to update an account's total value without counting it as a new contribution

### How to use it

Use **Add/Remove** when money actually enters or leaves an account.

Use **Update Total Value** when the account balance has changed because of market movement, interest, fund price changes, or a manual valuation update.

Example:

- Add £250 to S&S ISA = contribution
- Later update S&S ISA total from £250 to £264 = £14 growth/change

Physical Bullion remains calculated from bullion holdings and metal prices, so update bullion from the Bullion page rather than the account value form.


## Pension tracker

A basic `Pension` account type is included. Add your pension as an account, then use **Update Total Value** whenever you get a new pension valuation. Contributions/add-remove transactions are tracked separately from market/value updates on the Performance page.

## Budget Calculator

This build includes a Budget page:

- Set average monthly income
- Add manual budget topics
- Edit/delete each topic
- Shows total assigned and floating left

The app will auto-create the budget tables when it starts.


Lifetime ISA bonus handling
---------------------------
When you add money to a Lifetime ISA account, the app automatically adds a 25% government bonus as a value update. This means your own payment counts as contribution/money in, while the 25% bonus counts as growth/value change on the Performance page.
