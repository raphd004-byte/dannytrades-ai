"""
Configuration for the SMC/ICT MT5 trading bot.
Edit these values before running. Do NOT commit real credentials to source control —
use environment variables in production (see README).
"""

import os

# ---------------------------------------------------------------------------
# MT5 / FBS ACCOUNT SETTINGS
# ---------------------------------------------------------------------------
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))          # your FBS MT5 account number
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")           # your MT5 password
MT5_SERVER = os.getenv("MT5_SERVER", "FBS-Demo")       # e.g. "FBS-Demo" or "FBS-Real"
MT5_TERMINAL_PATH = os.getenv(
    "MT5_TERMINAL_PATH", r"C:\Program Files\FBS MetaTrader 5\terminal64.exe"
)  # adjust to wherever your FBS MT5 terminal is installed

# ---------------------------------------------------------------------------
# TRADING UNIVERSE
# ---------------------------------------------------------------------------
SYMBOLS = ["EURUSD", "GBPUSD", "XAUUSD", "USDJPY"]

# Timeframes used for multi-timeframe SMC analysis
HTF_TIMEFRAME = "H4"      # higher timeframe: bias / major structure
LTF_TIMEFRAME = "M15"     # lower timeframe: entry trigger (order block / FVG mitigation)
ENTRY_TIMEFRAME = "M5"    # execution refinement

# ---------------------------------------------------------------------------
# RISK MANAGEMENT
# ---------------------------------------------------------------------------
RISK_PER_TRADE_PCT = 0.5       # % of account equity risked per trade
MAX_DAILY_LOSS_PCT = 3.0       # stop trading for the day if equity drawdown exceeds this
MAX_OPEN_POSITIONS = 3
MIN_RR_RATIO = 2.0             # minimum reward:risk to take a trade
SL_BUFFER_PIPS = 3             # extra pips beyond the swing point for stop loss
MAGIC_NUMBER = 990012

# Lot sizing: "auto" derives lot size from RISK_PER_TRADE_PCT + stop distance.
# "fixed" always uses FIXED_LOT_SIZE regardless of stop distance.
# interactive_bot.py sets these from your prompted answers at startup.
LOT_SIZE_MODE = "auto"         # "auto" or "fixed"
FIXED_LOT_SIZE = 0.01

# Optional extra safety cap: refuse to open a position whose required margin
# would exceed (equity * LEVERAGE_CAP) — i.e. an effective leverage ceiling
# independent of whatever leverage FBS has assigned your account.
# Set to None to disable and rely on RISK_PER_TRADE_PCT / broker limits only.
# Set to a number (e.g. 100) to cap effective leverage at that ratio.
LEVERAGE_CAP = None

# ---------------------------------------------------------------------------
# SMC / ICT PARAMETERS
# ---------------------------------------------------------------------------
SWING_LOOKBACK = 5             # bars each side to confirm a swing high/low (fractal)
EQUAL_HL_TOLERANCE_PIPS = 2    # tolerance for detecting equal highs/lows (liquidity pools)
FVG_MIN_SIZE_PIPS = 3          # minimum gap size to count as a valid Fair Value Gap
ORDER_BLOCK_LOOKBACK = 20      # bars searched back for the last opposing candle before a BOS
LIQUIDITY_SWEEP_WICK_RATIO = 0.6  # wick must be >= this fraction of candle range to count as a sweep

# Kill-zone session filters (server time, adjust to your broker's UTC offset)
TRADE_SESSIONS = {
    "london_open": ("07:00", "10:00"),
    "ny_open": ("12:30", "15:00"),
}
ONLY_TRADE_IN_SESSIONS = False

# ---------------------------------------------------------------------------
# NEWS / SENTIMENT FILTER
# ---------------------------------------------------------------------------
# Provide your own API keys. The bot degrades gracefully (sentiment filter disabled)
# if these are left blank.
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")             # https://newsapi.org
X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN", "")        # X/Twitter API v2 bearer token
ALPHAVANTAGE_KEY = os.getenv("ALPHAVANTAGE_KEY", "")     # https://www.alphavantage.co (has a NEWS_SENTIMENT endpoint)

SENTIMENT_ENABLED = True
# If sentiment score for a symbol's underlying macro theme is strongly against
# the trade direction, the bot will skip the trade rather than override price action.
SENTIMENT_VETO_THRESHOLD = -0.4   # score range is roughly -1 (very negative) to +1 (very positive)

# High-impact economic calendar avoidance (avoid entering X minutes around news)
NEWS_BLACKOUT_MINUTES_BEFORE = 15
NEWS_BLACKOUT_MINUTES_AFTER = 15

# ---------------------------------------------------------------------------
# EXECUTION
# ---------------------------------------------------------------------------
LOOP_INTERVAL_SECONDS = 30
DRY_RUN = True   # if True, logs intended trades but never sends real orders. Set False deliberately.
LOG_FILE = "bot.log"
