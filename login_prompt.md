# 🔐 MT5 Netrader Terminal — Login Prompt

## Enter Your Trading Logins

### Step 1 — Launch the MT5 Terminal
Open the Netrader terminal:
```
C:\Program Files\Netrader MetaTrader 5\terminal64.exe
```
*(Update the path if your Netrader is installed elsewhere.)*

### Step 2 — Fill in the Login Screen
The terminal will open to a login window. Enter these fields:

| Field | What to Enter | Example |
|---|---|---|
| **Login** | Your FBS MT5 account number | `5056666279` |
| **Password** | Your FBS MT5 account password | `••••••••` |
| **Server** | Your account type | `FBS-Demo` or `FBS-Real` |

### Step 3 — Click Login
Click the **Login** button (or press Enter).

---

## ✅ You're Logged In When...

You see:
- ✅ Your account number at the top
- ✅ **Balance** (e.g. `$10,000.00`)
- ✅ **Equity** (e.g. `$10,025.50`)
- ✅ **Leverage** (e.g. `1:100` or `1:500`)
- ✅ **Market Watch** with symbols (EURUSD, GBPUSD, XAUUSD, etc.)
- ✅ **Terminal** with chart(s) open

---

## ⚠️ Common Login Errors

| Error | Cause | Fix |
|---|---|---|
| ❌ Invalid account | Wrong account number | Re-check the digits; no spaces |
| ❌ Wrong password | Incorrect password | Reset via FBS website → Trading accounts |
| ❌ Auth on FBS-Demo failed | Wrong server or demo/real mismatch | Confirm server matches your account |
| ❌ Terminal: Authorization failed | Terminal not launched, or not logged in | Launch terminal manually, log in, retry |
| ❌ No account info after login | Terminal still loading | Wait 10–15 seconds, then retry |

---

## 📝 Quick Checklist

- [ ] MT5 terminal installed
- [ ] FBS account number obtained
- [ ] MT5 password obtained (NOT your FBS website password)
- [ ] Server selected: FBS-Demo or FBS-Real
- [ ] Terminal opened and logged in
- [ ] Balance/equity visible
- [ ] Bot verified to connect to MT5

---

## 🚀 After Login

Once the terminal is logged in, the bot will connect automatically:

```bash
pip install MetaTrader5
python interactive_bot.py
```

Then type `run` to start a trading burst.

> **Security reminder:** Never share your password with anyone, including AI assistants. The bot reads credentials from `config.py` (or environment variables `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`).