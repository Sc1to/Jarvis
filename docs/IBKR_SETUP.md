# IBKR_SETUP.md
# Interactive Brokers — TWS + IBC + ib_insync Setup Guide
# ELI5 guide for connecting the trading system to Interactive Brokers.
# Written for someone who has never used IBKR's API before.
# Read TRADING_ARCHITECTURE.md first for context on how IBKR fits into the system.

---

## OVERVIEW

Interactive Brokers provides multiple ways for software to control your account.
We use **Trader Workstation (TWS)** — the full IBKR desktop application — combined
with **IBC** (a tool that automates TWS login) and **ib_insync** (a Python library
that talks to TWS over a persistent socket connection).

This approach was chosen over the Client Portal Gateway (CPG) REST API because:
- **No daily re-authentication.** CPG sessions expire every ~24 hours and require manual
  renewal — fatal for an autonomous overnight system. IBC handles TWS login automatically.
- **Persistent connection.** TWS maintains a live socket connection. No polling or
  session tokens to manage.
- **Better market data.** TWS gives access to real-time streaming data; CPG uses snapshots.

The setup has three stages:
1. Create your IBKR account and enable API access
2. Install TWS and IBC on the mini PC (headless, managed by systemd)
3. Configure the trading system to connect via ib_insync

**Paper trading first — always.**
IBKR provides a paper trading account that behaves identically to a live account
but uses fake money. All development, testing, and validation happens against
paper trading. You make the explicit decision to switch to live — the system
never does this automatically.

---

## STAGE 1 — IBKR ACCOUNT SETUP

### Step 1 — Create an IBKR account

1. Go to https://www.interactivebrokers.com
2. Click **Open Account**
3. Follow the application process — this takes 1-3 business days to approve
4. You will need to provide identity verification documents

**Account type recommendation:**
- Individual account
- Choose the account tier that suits your trading volume

### Step 2 — Enable paper trading

Paper trading is IBKR's simulated environment. It uses real market data but
fake money. This is where you will test the system before going live.

1. Log in to IBKR Client Portal at https://clientportal.ibkr.com
2. Go to **Settings** → **Paper Trading**
3. Click **Create Paper Trading Account**
4. Note your paper trading username and password — they are different from your
   live account credentials

### Step 3 — Enable API access in TWS

This step is done inside TWS once it is running (Step 8 below).
For now, note that you will need to:
- Go to TWS → **Edit** → **Global Configuration** → **API** → **Settings**
- Check **Enable ActiveX and Socket Clients**
- Set **Socket port:** 7497 (paper) or 7496 (live)
- Check **Allow connections from localhost only**
- Uncheck **Read-Only API**

---

## STAGE 2 — TWS + IBC SETUP ON MINI PC

TWS is IBKR's full desktop application. We run it headless (no display) using
**Xvfb** (a virtual display), and **IBC** automates the login so it restarts
without human intervention.

### Step 4 — Install Xvfb (virtual display)

TWS is a GUI application. Xvfb provides a virtual display so it can run
without a monitor.

```bash
sudo apt install -y xvfb
```

### Step 5 — Install Java

TWS requires Java 11 or later:

```bash
sudo apt install -y openjdk-17-jre
java -version
```

You should see `openjdk version "17.x.x"` — that is correct.

### Step 6 — Download and install TWS

Download the TWS offline installer for Linux:

```bash
cd /tmp
curl -O https://download2.interactivebrokers.com/installers/tws/latest-standalone/tws-latest-standalone-linux-x64.sh
chmod +x tws-latest-standalone-linux-x64.sh
```

Run the installer (this launches a GUI wizard — run it on the mini PC with a monitor connected for the initial setup, or use the headless install option):

```bash
sudo ./tws-latest-standalone-linux-x64.sh
```

Install to: `/opt/ibkr/tws/` (or the default location the installer suggests).

### Step 7 — Download and install IBC

IBC automates the TWS login so TWS can restart without human intervention.

```bash
cd /opt
sudo mkdir ibkr-ibc
cd ibkr-ibc
sudo curl -L -O https://github.com/IbcAlpha/IBC/releases/latest/download/IBCLinux.zip
sudo unzip IBCLinux.zip
sudo rm IBCLinux.zip
sudo chmod +x *.sh scripts/*.sh
```

### Step 8 — Configure IBC

Edit the IBC config file:

```bash
sudo nano /opt/ibkr-ibc/config.ini
```

Set these values (replace placeholders with your actual credentials):

```ini
[TWS]
# Your paper trading credentials
IbLoginId=YOUR_PAPER_USERNAME
IbPassword=YOUR_PAPER_PASSWORD

# Set to 'paper' or 'live'
TradingMode=paper

# TWS setting to accept incoming connections
AcceptIncomingConnectionAction=accept

# Automatically dismiss warning dialogs
DismissPasswordExpiryWarning=yes
DismissNSEComplianceNotice=yes
```

**Important:** This file contains your IBKR password in plain text.
Secure it:
```bash
sudo chmod 600 /opt/ibkr-ibc/config.ini
sudo chown jarvis:jarvis /opt/ibkr-ibc/config.ini
```

### Step 9 — Create a TWS startup script

```bash
sudo nano /opt/ibkr-ibc/start-tws.sh
```

Contents:

```bash
#!/bin/bash
export DISPLAY=:99
Xvfb :99 -screen 0 1024x768x24 &
sleep 2
cd /opt/ibkr-ibc
./twsstart.sh
```

Make it executable:

```bash
sudo chmod +x /opt/ibkr-ibc/start-tws.sh
```

### Step 10 — Create a systemd service for TWS

```bash
sudo nano /etc/systemd/system/platform-ibkr-tws.service
```

Contents:

```ini
[Unit]
Description=IBKR Trader Workstation (IBC managed)
After=network.target

[Service]
Type=simple
User=jarvis
ExecStart=/opt/ibkr-ibc/start-tws.sh
Restart=always
RestartSec=60
Environment=DISPLAY=:99

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable platform-ibkr-tws
sudo systemctl start platform-ibkr-tws
```

### Step 11 — Verify TWS is running and accepting connections

Wait 60-90 seconds for TWS to start (it is slow to initialize). Then test
that the trading system can connect:

```bash
python3 -c "
import asyncio
from ib_insync import IB, util
util.patchAsyncio()

async def test():
    ib = IB()
    await ib.connectAsync('127.0.0.1', 7497, clientId=99)
    print('Connected:', ib.isConnected())
    accounts = ib.managedAccounts()
    print('Accounts:', accounts)
    ib.disconnect()

asyncio.run(test())
"
```

Expected output:
```
Connected: True
Accounts: ['DU1234567']   ← your paper account number
```

If you see an error, check the TWS logs:
```bash
sudo journalctl -u platform-ibkr-tws -n 50
```

---

## STAGE 3 — CONFIGURE THE TRADING SYSTEM

### Step 12 — Store credentials in platform config

Never store credentials in code or config files. The account IDs (not passwords —
IBC handles the password) go in the SQLite config table:

```bash
sqlite3 /opt/platform/data/platform.db
```

Then run:

```sql
INSERT INTO trading_config (key, value) VALUES
  ('ibkr_account_id', 'DU1234567'),
  ('trading_mode', 'paper');
```

Replace `DU1234567` with your actual paper account number (shown in Step 11 output).

Exit SQLite:
```sql
.quit
```

### Step 13 — Verify the trading system health check

With the trading service running:

```bash
curl http://localhost:8030/health
```

Expected output includes:
```json
{
  "status": "ok",
  "trading_mode": "paper",
  "dependencies": {
    "ibkr_tws": "ok",
    "coinbase": "ok"
  }
}
```

If `ibkr_tws` shows `"down"`, check that TWS is running and the port (7497) is accessible.

---

## SWITCHING FROM PAPER TO LIVE

This is a manual, deliberate process. The system cannot do this automatically.
Minimum 3-6 months of successful paper trading before considering this step.

When you are ready:

1. Stop the trading service:
   ```bash
   sudo systemctl stop platform-trading
   ```

2. Update IBC config to use live credentials and live mode:
   ```bash
   sudo nano /opt/ibkr-ibc/config.ini
   ```
   Change:
   ```ini
   IbLoginId=YOUR_LIVE_USERNAME
   IbPassword=YOUR_LIVE_PASSWORD
   TradingMode=live
   ```

3. Update the SQLite config:
   ```bash
   sqlite3 /opt/platform/data/platform.db
   ```
   ```sql
   UPDATE trading_config SET value='live' WHERE key='trading_mode';
   UPDATE trading_config SET value='YOUR_LIVE_ACCOUNT_ID' WHERE key='ibkr_account_id';
   .quit
   ```

4. Restart TWS (it will log in with live credentials):
   ```bash
   sudo systemctl restart platform-ibkr-tws
   ```

5. Wait 90 seconds for TWS to initialize, then restart the trading service:
   ```bash
   sudo systemctl start platform-trading
   ```

6. Verify via health check and trading app dashboard.

**What changes:**
- IBC logs in to live account instead of paper
- TWS connects on port 7496 instead of 7497
- Everything else: identical — same code, same logic, same rules

**What does not change:**
- All risk rules remain in full effect
- Compliance auditor continues running
- Pool ceilings remain as configured
- All hard stops remain in place

---

## IBC AUTO-RECONNECT

IBC monitors TWS and restarts it if it crashes. The systemd service ensures
IBC itself restarts if it stops. Together they give you ~24/7 operation without
manual intervention.

**What IBC handles automatically:**
- Daily TWS session restart (IBKR restarts TWS servers overnight — IBC reconnects)
- TWS crash recovery
- Password expiry warnings (dismissed automatically)
- Market data farm reconnection

**What requires user attention:**
- IBC password change (update config.ini if IBKR forces a password reset)
- IBKR account deactivation or API permission changes
- TWS major version update requiring reinstall

Monitor the systemd service to catch any repeated restarts:
```bash
sudo journalctl -u platform-ibkr-tws -f
```

---

## TROUBLESHOOTING

### TWS won't start

Check logs:
```bash
sudo journalctl -u platform-ibkr-tws -n 50
```

Check if Xvfb is running:
```bash
ps aux | grep Xvfb
```

Check if port 7497 is listening:
```bash
sudo ss -tlnp | grep 7497
```

### Connection refused on port 7497

TWS takes 60-90 seconds to initialize on start. Wait and retry.

If TWS has started but still refused:
- Open TWS API settings (requires VNC or physical monitor): Edit → Global Configuration → API → Settings
- Ensure **Enable ActiveX and Socket Clients** is checked
- Ensure port is set to 7497 (paper) or 7496 (live)

### IBC login fails

- Check credentials in `/opt/ibkr-ibc/config.ini`
- Make sure `TradingMode` matches the account type (`paper` or `live`)
- IBKR may have forced a password change — update config.ini

### Market data returns empty

- IBKR requires market data subscriptions for real-time data
- Paper accounts have delayed data by default
- Subscribe in IBKR Client Portal under Market Data
- ib_insync falls back to bid/ask if last price is unavailable — this is normal

### Orders rejected by TWS

Common reasons:
- Paper account not funded (add virtual funds in IBKR Client Portal → Paper Trading)
- Asset not permitted for your account type
- Order outside market hours
- Position would exceed IBKR account limits (separate from our pool limits)

---

## SECURITY NOTES

- TWS and IBC run on localhost — never exposed to the internet directly
- Tailscale provides the secure tunnel for remote management
- `config.ini` is chmod 600 — readable only by the `jarvis` system user
- Account IDs in SQLite, never in code or committed files
- The live/paper switch requires explicit action — never automatic
- All orders pass through the Risk Gate before reaching TWS

---

## REFERENCE

**IBC project (open source):**
https://github.com/IbcAlpha/IBC

**ib_insync documentation:**
https://ib-insync.readthedocs.io

**IBKR TWS API reference:**
https://interactivebrokers.github.io/tws-api/

**TWS download:**
https://www.interactivebrokers.com/en/trading/tws.php

**Paper trading management:**
https://clientportal.ibkr.com → Settings → Paper Trading
