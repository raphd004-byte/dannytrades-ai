# SMC/ICT MT5 Bot (FBS)

An algorithmic trading bot for MetaTrader 5 implementing Smart Money Concepts /
ICT-style logic: market structure (BOS/CHoCH), order blocks, Fair Value Gaps,
liquidity pools, and liquidity sweeps — with an optional news/sentiment veto
layer.

## Before you do anything else

- **This is a framework, not an edge.** No combination of SMC/ICT rules is
  guaranteed to be profitable. Past chart patterns "working" in backtests
  does not mean they'll work going forward. Treat this as a starting point
  you refine, backtest, and validate — not a plug-and-play money maker.
- **Run on a DEMO account first.** `config.py` has `DRY_RUN = True` by
  default, which logs intended trades without sending real orders. Even
  after switching `DRY_RUN = False`, point `MT5_SERVER` at your FBS **demo**
  server until you've watched it operate for weeks and understand exactly
  what it's doing.
- **Leverage and automation compound risk.** FX/CFDs are leveraged
  instruments; automated systems can lose money quickly if a bug, bad fill,
  or connectivity issue occurs. Never risk money you can't afford to lose,
  and keep `MAX_DAILY_LOSS_PCT` conservative.
- I'm not a financial advisor and this isn't financial advice — it's a
  software framework you're responsible for testing and operating.

## How to Set Up Trading Logins

### Get your FBS trading account details

1. Log in to your FBS account at [fbs.com](https://www.fbs.com)
2. Go to **My Business** → **Trading accounts**
3. Note down:
   - **Login (Account Number)** — e.g. `5056666279`
   - **Password** — the MT5 password, NOT your FBS website password
   - **Server** — e.g. `FBS-Demo` or `FBS-Real`

### Configure `config.py`

Edit `config.py` with your details:

```python
MT5_LOGIN = 5056666279          # your FBS account number
MT5_PASSWORD = "your-mt5-password"   # the password from MT5, not FBS website
MT5_SERVER = "FBS-Demo"         # or "FBS-Real"
MT5_TERMINAL_PATH = r"C:\Program Files\FBS MetaTrader 5\terminal64.exe"
```

### Or use environment variables (no password in config)

**Windows (PowerShell):**
```powershell
$env:MT5_LOGIN = "5056666279"
$env:MT5_PASSWORD = "your-mt5-password"
$env:MT5_SERVER = "FBS-Demo"
```

**Windows (CMD):**
```cmd
set MT5_LOGIN=5056666279
set MT5_PASSWORD=your-mt5-password
set MT5_SERVER=FBS-Demo
```

### Enter credentials in the MT5 terminal

1. Open `C:\Program Files\FBS MetaTrader 5\terminal64.exe`
2. The terminal opens to a login screen — enter your **Login**, **Password**, and **Server**
3. Click **Login**
4. Wait for your account to load (balance, chart, market watch)

> **Tip:** The MT5 terminal login screen and `config.py` must match. The terminal is the source of truth — if the terminal can't log in, the bot won't work.

### Run the bot

```bash
python interactive_bot.py
```

The setup wizard will ask for:
- Risk per trade (%)
- Max daily loss (%)
- Max open positions
- Burst window (5–10 min)
- Fallback SL/RR
- Dry run confirmation (always start on `y` for DRY_RUN)

Then type `run` to start trading.

1. Pulls H4 (bias) and M15 (entry trigger) candles from MT5 for each symbol.
2. Detects market structure shifts (BOS/CHoCH), order blocks, Fair Value Gaps,
   and equal-high/equal-low liquidity pools.
3. Looks for the classic ICT confluence: higher-timeframe bias + a liquidity
   sweep on the lower timeframe (stop hunt) + price returning into an
   unmitigated order block or FVG in the direction of bias.
4. Optionally checks a news/sentiment score for the symbol's macro theme
   (rate decisions, central bank commentary, geopolitical headlines) and
   **vetoes** (blocks) trades that go strongly against current sentiment —
   it never generates trades from sentiment alone.
5. Sizes the position from your equity and `RISK_PER_TRADE_PCT`, and sends
   the order via the MT5 Python API (or just logs it in `DRY_RUN` mode).

## About the "tweets from Trump / market makers / banks" request

I built the sentiment layer as a **pluggable veto**, not a live Twitter
firehose, because:
- Reliable real-time tracking of specific accounts requires a paid X API
  tier (`X_BEARER_TOKEN` in `config.py` — the "recent search" endpoint is
  the hook, and you can add a `from:username` filter to `SYMBOL_KEYWORDS`
  matching to follow specific accounts).
- `sentiment.py` also supports NewsAPI and Alpha Vantage's `NEWS_SENTIMENT`
  endpoint (which covers Fed/ECB commentary and macro headlines) as more
  reliable alternatives to scraping social media.
- The included keyword-scoring function is intentionally simple — a
  starting point. For anything serious, swap in a real financial-news
  sentiment model.

## Setup

1. Install FBS's MetaTrader 5 terminal on Windows and log into your
   demo (or live) account manually once, so it's cached.
2. `pip install -r requirements.txt`
3. Set environment variables (recommended over editing `config.py` directly):
   ```
   set MT5_LOGIN=12345678
   set MT5_PASSWORD=yourpassword
   set MT5_SERVER=FBS-Demo
   set NEWSAPI_KEY=...          (optional)
   set ALPHAVANTAGE_KEY=...     (optional)
   set X_BEARER_TOKEN=...       (optional)
   ```
4. Confirm `MT5_TERMINAL_PATH` in `config.py` matches where FBS's terminal
   is installed.
5. **Backtest first** (see below) before running anything live.
6. Run: `python interactive_bot.py` — this is the entry point you actually
   run day to day. `main.py` still exists as a non-interactive reference
   loop, but `interactive_bot.py` is the one that asks for your risk
   settings and puts you in control of start/stop.

**Platform note**: the MT5 Python API only works where a real MT5 terminal
is running (Windows, or Wine on Linux/Mac) — it cannot connect to FBS's
servers directly from a headless Linux box without a terminal instance.

## Running it interactively (`interactive_bot.py`)

On launch it asks you, in order:
1. **Lot sizing** — either risk-based auto sizing (you give a % of equity
   to risk per trade) or a fixed lot size you specify yourself.
2. **Leverage cap** — an optional ceiling on the *effective* leverage the
   bot will use when sizing a position, independent of whatever leverage
   FBS has assigned your account. This is a safety limit, not a leverage
   *setter* — your account's actual leverage is configured with your
   broker, not by this script.
3. **Max daily loss %**, **max open positions**, **minimum R:R**.
4. Whether to run in **DRY_RUN** (log-only) mode — recommended until you
   trust the setup.

It then connects to MT5 and shows you your account balance/equity/leverage
before doing anything else. Nothing trades until you type a command:

```
bot> run        # start scanning & executing setups
bot> stop       # pause new entries — open positions are left alone
bot> status     # show equity, open positions, current settings
bot> closeall   # immediately close every position this bot opened (asks to confirm)
bot> exit       # stop, disconnect, quit
```

`stop` pauses *new* trade entries only — it does not touch positions
already open, since force-closing on every pause could itself cause
unwanted losses (e.g. closing into an unfavorable spread). Use `closeall`
if you specifically want everything flattened immediately.

## Backtesting (`backtest.py`)

Before running live, validate the strategy against history:

1. In MT5, export candle history to CSV for your symbol at both your HTF
   and LTF timeframes (e.g. via Strategy Tester's History Center, or
   right-click a chart → export). You need a `time,open,high,low,close`
   header (MT5's native `<DATE>,<TIME>,<OPEN>,...` export format is also
   auto-detected).
2. Run:
   ```
   python backtest.py --symbol EURUSD --htf-csv eurusd_h4.csv --ltf-csv eurusd_m15.csv
   ```
3. It replays the same `smc_ict.py` logic the live bot uses bar-by-bar,
   simulates fills/stop-outs at your configured `MIN_RR_RATIO`, and prints
   win rate, average R, total return, and max drawdown, plus saves a full
   trade log to `backtest_trades.csv`.

**Backtest limitations to keep in mind**: no spread, slippage, or
commission modeling; exits are a simple fixed R:R (no partials, no
break-even management); and past performance on historical bars is not a
guarantee of future results. Treat it as a first-pass filter — if a setup
loses money badly in backtest, don't run it live; if it looks decent,
that's still not a green light to skip demo testing.

## Files

| File | Purpose |
|---|---|
| `config.py` | All settings: credentials, risk, SMC parameters, sessions |
| `mt5_connector.py` | MT5 terminal connection, data pulls, order execution |
| `smc_ict.py` | Structure/order block/FVG/liquidity detection engine |
| `sentiment.py` | Pluggable news/sentiment veto layer |
| `risk_manager.py` | Position sizing (auto or fixed lot), daily loss limit, leverage cap |
| `interactive_bot.py` | **Main entry point.** Interactive risk setup + run/stop command console |
| `main.py` | Simpler non-interactive reference loop (no prompts, runs continuously) |
| `backtest.py` | Bar-by-bar backtest harness using historical CSV data |

## Suggested next steps

- **Backtest** `smc_ict.py`'s logic against historical data before trusting
  it live — I did not include a backtesting harness here; consider
  `backtesting.py` or a custom bar-replay script using MT5 history.
- Tune `SWING_LOOKBACK`, `EQUAL_HL_TOLERANCE_PIPS`, `FVG_MIN_SIZE_PIPS`, and
  `LIQUIDITY_SWEEP_WICK_RATIO` per instrument — gold and JPY pairs behave
  differently from EUR/GBP majors.
- Add a proper economic calendar integration (e.g. ForexFactory calendar
  scrape or a paid calendar API) to strengthen `NEWS_BLACKOUT_MINUTES_*`,
  which is currently defined in config but not yet wired into `main.py`.
- Consider partial take-profits and break-even stop management once in a
  trade — the current version is a single fixed SL/TP per position.
