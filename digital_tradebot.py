"""
Interactive entry point for the SMC/ICT MT5 bot.

BURST MODE: this build is restricted to XAUUSD, BTCUSD, and GBPJPY only.
The moment you type "run", it schedules 1-3 trades (never more than one per
symbol, so every trade in the burst is a different pair) fired at random
times inside a 5-10 minute window from that moment. Each trade first tries
to use a real SMC/ICT setup; if no valid setup has appeared for that symbol
by the time its slot comes up, it places a fallback-parameter trade so the
burst still hits its target count. Leverage used for sizing is fixed at
1:3000 and is not user-adjustable.

Run this instead of main.py. It will:
  1. Ask you for risk management settings (risk % per trade OR fixed lot size,
     max daily loss, max open positions, and the fallback stop/target
     distances used if a slot has to fire without a real setup) before
     touching the account.
  2. Connect to MT5 / FBS and show your account info for confirmation.
  3. Sit at a command prompt. The bot NEVER places a trade until you type
     "run", and immediately cancels any not-yet-fired trades in the current
     burst the moment you type "stop". Existing open positions are left
     alone by "stop" — use "closeall" if you want it to flatten everything
     immediately.

Commands once running:
    run        - start scanning symbols and executing setups
    stop       - pause new trade entries (open positions are left alone)
    status     - show account equity, open positions, and current settings
    closeall   - close all positions opened by this bot (matches magic number)
    help       - show this command list
    exit       - stop, disconnect, and quit

Usage:
    python interactive_bot.py
"""

import logging
import random
import sys
import threading
import time

import config
import smc_ict
import sentiment
from mt5_connector import MT5Connector
from risk_manager import RiskManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(config.LOG_FILE), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("interactive_bot")


# ---------------------------------------------------------------------------
# Interactive setup
# ---------------------------------------------------------------------------
def ask(prompt: str, default: str = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val if val else default


def ask_float(prompt: str, default: float) -> float:
    while True:
        raw = ask(prompt, str(default))
        try:
            return float(raw)
        except ValueError:
            print("  Please enter a number.")


def ask_int(prompt: str, default: int) -> int:
    while True:
        raw = ask(prompt, str(default))
        try:
            return int(raw)
        except ValueError:
            print("  Please enter a whole number.")


def ask_yes_no(prompt: str, default: bool) -> bool:
    d = "y" if default else "n"
    while True:
        raw = ask(f"{prompt} (y/n)", d).lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please answer y or n.")


def run_setup_wizard():
    print("=" * 70)
    print(" SMC/ICT MT5 Bot — Risk Setup (BURST MODE)")
    print(" Nothing executes until you connect AND type 'run' at the prompt.")
    print(" Typing 'run' schedules 1-3 trades (one per symbol max) over the")
    print(" next 5-10 minutes, across XAUUSD / BTCUSD / GBPJPY only.")
    print("=" * 70)

    # Fixed trading universe — do not expand beyond these three symbols,
    # since burst mode relies on "1 trade per symbol max" to guarantee
    # every trade in a burst is a different pair.
    config.SYMBOLS = ["XAUUSD", "BTCUSD", "GBPJPY"]
    print(f"\nTrading universe is fixed for this build: {', '.join(config.SYMBOLS)}")

    print("\n-- Lot sizing --")
    use_fixed = ask_yes_no(
        "Use a FIXED lot size for every trade instead of risk-based auto sizing?",
        default=False,
    )
    if use_fixed:
        config.LOT_SIZE_MODE = "fixed"
        config.FIXED_LOT_SIZE = ask_float("  Fixed lot size (e.g. 0.01, 0.10, 1.00)", 0.01)
    else:
        config.LOT_SIZE_MODE = "auto"
        config.RISK_PER_TRADE_PCT = ask_float(
            "  Risk per trade, as % of account equity (e.g. 0.5 = 0.5%)",
            config.RISK_PER_TRADE_PCT,
        )

    print("\n-- Leverage --")
    print("  Your FBS account has its own leverage (set by FBS, e.g. 1:100, 1:500).")
    print("  This bot does NOT change your account leverage — it only uses a cap")
    print("  to limit how much notional it will open relative to your equity.")
    print("  Set a cap to limit effective leverage, or set it to 0 to disable.")
    connector = MT5Connector()
    connector.connect()
    acc = connector.account_info()
    broker_leverage = acc.leverage if acc else None
    connector.disconnect()
    if broker_leverage:
        print(f"  Your FBS account leverage: 1:{broker_leverage}")
    default_cap = broker_leverage if broker_leverage else 0
    while True:
        raw = ask("  Max effective leverage cap (0 = no cap, uses broker leverage)", str(default_cap))
        if raw.strip() == '0' or raw.strip() == '':
            config.LEVERAGE_CAP = None
            break
        try:
            val = int(raw)
            if val > 0:
                config.LEVERAGE_CAP = val
                break
            print("  Please enter 0 or a positive number.")
        except ValueError:
            print("  Please enter a number.")

    print("\n-- Account-level risk controls --")
    config.MAX_DAILY_LOSS_PCT = ask_float(
        "  Max daily loss before the bot halts new entries (% of equity)",
        config.MAX_DAILY_LOSS_PCT,
    )
    config.MAX_OPEN_POSITIONS = ask_int(
        "  Max number of open positions at once",
        config.MAX_OPEN_POSITIONS,
    )
    config.MIN_RR_RATIO = ask_float(
        "  Minimum reward:risk ratio required to take a setup",
        config.MIN_RR_RATIO,
    )

    print("\n-- Burst trading window --")
    print("  Once you type 'run', the bot targets 1-3 trades total, at most")
    print("  one per symbol, fired at random moments inside a window you set")
    print("  here (must be between 5 and 10 minutes).")
    while True:
        config.BURST_WINDOW_MINUTES = ask_float(
            "  Burst window length in minutes (5-10)", 7.0
        )
        if 5.0 <= config.BURST_WINDOW_MINUTES <= 10.0:
            break
        print("  Please enter a value between 5 and 10.")

    print("\n-- Fallback stop/target (used only if a symbol's slot fires")
    print("   before a real SMC/ICT setup has appeared for it) --")
    config.FALLBACK_SL_POINTS = ask_float(
        "  Fallback stop-loss distance, in points/pips", 200.0
    )
    config.FALLBACK_RR_RATIO = ask_float(
        "  Fallback reward:risk ratio for the take-profit distance",
        config.MIN_RR_RATIO if config.MIN_RR_RATIO else 1.5,
    )

    print("\n-- Execution mode --")
    dry = ask_yes_no(
        "DRY RUN mode (log intended trades but never send real orders)?",
        default=config.DRY_RUN,
    )
    config.DRY_RUN = dry
    if not dry:
        print("  *** LIVE ORDER SENDING IS ON. Confirm this is a DEMO account first. ***")
        confirm = ask_yes_no("  Type y to confirm you understand real orders may be sent", False)
        if not confirm:
            print("  Falling back to DRY_RUN for safety.")
            config.DRY_RUN = True

    print("\nSettings locked in:")
    print(f"  Lot sizing:        {config.LOT_SIZE_MODE} "
          f"({config.FIXED_LOT_SIZE if config.LOT_SIZE_MODE=='fixed' else str(config.RISK_PER_TRADE_PCT)+'% risk/trade'})")
    print(f"  Leverage (fixed):  1:{config.LEVERAGE_CAP}")
    print(f"  Max daily loss:    {config.MAX_DAILY_LOSS_PCT}%")
    print(f"  Max open trades:   {config.MAX_OPEN_POSITIONS}")
    print(f"  Min R:R:           {config.MIN_RR_RATIO}")
    print(f"  Burst window:      {config.BURST_WINDOW_MINUTES} min, 1-3 trades, symbols: {', '.join(config.SYMBOLS)}")
    print(f"  Fallback SL/RR:    {config.FALLBACK_SL_POINTS} pts / {config.FALLBACK_RR_RATIO}:1")
    print(f"  Dry run:           {config.DRY_RUN}")
    print()


# ---------------------------------------------------------------------------
# Trading engine (background thread) — identical logic to main.py's loop,
# gated by the `state["running"]` flag which only your commands can flip.
# ---------------------------------------------------------------------------
class BotEngine:
    def __init__(self, connector: MT5Connector, risk: RiskManager):
        self.connector = connector
        self.risk = risk
        self.running = threading.Event()      # set while a burst is active/scheduled
        self.stop_requested = threading.Event()          # program exit
        self.burst_cancel = threading.Event()             # cancels remaining un-fired trades
        self.thread = None
        self._burst_lock = threading.Lock()

    def start_thread(self):
        # No standing background thread in burst mode — threads are spun up
        # per-burst by start_burst(). Kept for interface compatibility with
        # main().
        pass

    def already_in_symbol(self, symbol: str) -> bool:
        return len(self.connector.open_positions(symbol)) > 0

    def build_idea_for_symbol(self, symbol: str):
        """Try to get a real SMC/ICT setup for this symbol right now.
        Returns an idea dict or None."""
        htf_rates = self.connector.get_rates(symbol, config.HTF_TIMEFRAME, 300)
        ltf_rates = self.connector.get_rates(symbol, config.LTF_TIMEFRAME, 300)
        if htf_rates is None or ltf_rates is None or len(htf_rates) < 50 or len(ltf_rates) < 50:
            logger.warning("Insufficient data for %s", symbol)
            return None

        htf_analysis = smc_ict.analyze(htf_rates, symbol)
        ltf_analysis = smc_ict.analyze(ltf_rates, symbol)

        tick_info = self.connector.get_symbol_info(symbol)
        if tick_info is None:
            return None
        current_price = (tick_info.bid + tick_info.ask) / 2

        return smc_ict.build_trade_idea(htf_analysis, ltf_analysis, current_price, symbol)

    def build_fallback_idea(self, symbol: str):
        """Used only when a scheduled slot arrives and no real setup has been
        found for this symbol yet. Guarantees the burst still hits its target
        trade count. Direction defaults to 'buy' unless smc_ict exposes a
        directional bias on the HTF analysis — ASSUMPTION: adjust the
        `getattr(..., "trend", None)` lookups below if your smc_ict module
        names this field differently."""
        tick_info = self.connector.get_symbol_info(symbol)
        if tick_info is None:
            return None
        current_price = (tick_info.bid + tick_info.ask) / 2

        direction = "buy"
        try:
            htf_rates = self.connector.get_rates(symbol, config.HTF_TIMEFRAME, 300)
            if htf_rates is not None and len(htf_rates) >= 50:
                htf_analysis = smc_ict.analyze(htf_rates, symbol)
                trend = getattr(htf_analysis, "trend", None) or (
                    htf_analysis.get("trend") if isinstance(htf_analysis, dict) else None
                )
                if trend in ("bearish", "down", "sell"):
                    direction = "sell"
        except Exception:
            logger.exception("%s: fallback trend lookup failed, defaulting to buy", symbol)

        point = getattr(tick_info, "point", 0.0001)
        sl_distance = config.FALLBACK_SL_POINTS * point
        tp_distance = sl_distance * config.FALLBACK_RR_RATIO

        if direction == "buy":
            stop_loss = current_price - sl_distance
            take_profit = current_price + tp_distance
        else:
            stop_loss = current_price + sl_distance
            take_profit = current_price - tp_distance

        return {
            "direction": direction,
            "entry": current_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reason": "burst-mode fallback (no confirmed SMC/ICT setup at fire time)",
        }

    def fire_trade(self, symbol: str) -> bool:
        """Attempt one trade on `symbol`. Tries a real setup first, falls
        back to build_fallback_idea() so the burst still hits its target
        count. Returns True if an order was sent (or would be, in dry run)."""
        if self.already_in_symbol(symbol):
            logger.info("%s: already have an open position, skipping", symbol)
            return False
        if self.risk.max_positions_reached():
            logger.info("Max open positions reached, skipping %s", symbol)
            return False
        if self.risk.daily_loss_limit_hit():
            logger.warning("Daily loss limit hit, halting new entries")
            return False

        try:
            idea = self.build_idea_for_symbol(symbol)
        except Exception:
            logger.exception("%s: error building real setup", symbol)
            idea = None

        used_fallback = False
        if idea is None:
            logger.info("%s: no confirmed setup at fire time, using fallback parameters", symbol)
            try:
                idea = self.build_fallback_idea(symbol)
            except Exception:
                logger.exception("%s: fallback idea build failed", symbol)
                idea = None
            used_fallback = True

        if idea is None:
            logger.warning("%s: could not build any trade idea, skipping", symbol)
            return False

        if not sentiment.sentiment_allows_trade(symbol, idea["direction"]):
            logger.info("%s: sentiment veto blocked the %s setup", symbol, idea["direction"])
            return False

        lots = self.risk.calc_position_size(symbol, idea["entry"], idea["stop_loss"])
        if lots <= 0:
            logger.warning("%s: computed lot size is 0, skipping", symbol)
            return False

        logger.info("%s: firing %s%s -> %s", symbol, idea["direction"],
                    " [FALLBACK]" if used_fallback else "", idea)
        try:
            result = self.connector.send_market_order(
                symbol=symbol,
                direction=idea["direction"],
                volume=lots,
                sl=idea["stop_loss"],
                tp=idea["take_profit"],
                comment=idea["reason"][:60],
            )
        except Exception:
            logger.exception("%s: send_market_order raised, treating as failed", symbol)
            return False

        if result is None:
            logger.error("%s: send_market_order returned no result (likely a connector/"
                         "terminal issue), treating as failed", symbol)
            return False

        if not result.success:
            logger.error("%s: order rejected -> %s", symbol, result.message)
            return False

        logger.info("%s: order filled -> ticket=%s %s", symbol, result.ticket, result.message)
        return True

    def start_burst(self):
        """Schedule 1-3 trades (max one per symbol) at random times inside
        the configured window, starting now."""
        with self._burst_lock:
            if self.running.is_set():
                return False
            self.burst_cancel.clear()
            self.running.set()
            self.thread = threading.Thread(target=self._run_burst, daemon=True)
            self.thread.start()
            return True

    def cancel_burst(self):
        """Cancels any not-yet-fired trades in the current burst. Trades
        already sent are left alone — this only stops future ones."""
        self.burst_cancel.set()

    def _run_burst(self):
        window_seconds = config.BURST_WINDOW_MINUTES * 60
        trade_count = random.randint(1, min(3, len(config.SYMBOLS)))
        symbols = random.sample(config.SYMBOLS, trade_count)  # distinct pairs, guaranteed
        fire_times = sorted(random.uniform(0, window_seconds) for _ in range(trade_count))

        logger.info(
            "Burst scheduled: %d trade(s) on %s over the next %.1f minutes",
            trade_count, symbols, config.BURST_WINDOW_MINUTES,
        )

        start = time.monotonic()
        for symbol, fire_at in zip(symbols, fire_times):
            while True:
                if self.stop_requested.is_set() or self.burst_cancel.is_set():
                    logger.info("Burst cancelled before firing %s", symbol)
                    self.running.clear()
                    return
                elapsed = time.monotonic() - start
                if elapsed >= fire_at:
                    break
                time.sleep(min(1.0, fire_at - elapsed))
            try:
                self.fire_trade(symbol)
            except Exception:
                logger.exception("Error firing trade on %s", symbol)

        logger.info("Burst complete.")
        self.running.clear()

    def close_all_bot_positions(self):
        closed = 0
        for symbol in config.SYMBOLS:
            for pos in self.connector.open_positions(symbol):
                if pos.magic == config.MAGIC_NUMBER:
                    result = self.connector.close_position(pos)
                    logger.info("Closed position %s on %s -> %s", pos.ticket, symbol, result)
                    if result.success:
                        closed += 1
        print(f"Closed {closed} position(s).")


# ---------------------------------------------------------------------------
# Command prompt (foreground) — you are always in control here.
# ---------------------------------------------------------------------------
HELP_TEXT = """
Commands:
  run        - fire a new burst: 1-3 trades, one per symbol max, on
               XAUUSD/BTCUSD/GBPJPY, at random times over the next
               5-10 minutes (blocked if a burst is already in progress)
  stop       - cancel any not-yet-fired trades in the current burst
               (does NOT close already-open positions)
  status     - show account equity, open positions, current settings
  closeall   - immediately close every position this bot opened
  help       - show this list again
  exit       - stop, disconnect from MT5, and quit
"""


def print_status(connector: MT5Connector, engine: BotEngine):
    acc = connector.account_info()
    positions = connector.open_positions()
    bot_positions = [p for p in positions if p.magic == config.MAGIC_NUMBER]
    print("-" * 50)
    if acc:
        print(f"Account:        {acc.login} @ {config.MT5_SERVER}")
        print(f"Balance:        {acc.balance:.2f}")
        print(f"Equity:         {acc.equity:.2f}")
        print(f"Leverage:       1:{acc.leverage}")
    print(f"Bot state:      {'BURST IN PROGRESS' if engine.running.is_set() else 'IDLE'}")
    print(f"Dry run:        {config.DRY_RUN}")
    print(f"Lot sizing:     {config.LOT_SIZE_MODE}")
    print(f"Leverage:       {config.LEVERAGE_CAP if config.LEVERAGE_CAP else 'no cap (broker leverage)'}")
    print(f"Burst window:   {config.BURST_WINDOW_MINUTES} min, 1-3 trades, symbols: {', '.join(config.SYMBOLS)}")
    print(f"Open positions (this bot): {len(bot_positions)}")
    for p in bot_positions:
        print(f"  #{p.ticket} {p.symbol} vol={p.volume} profit={p.profit:.2f}")
    print("-" * 50)


def command_loop(connector: MT5Connector, engine: BotEngine):
    print(HELP_TEXT)
    while True:
        try:
            cmd = input("bot> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            cmd = "exit"

        if cmd == "run":
            if engine.running.is_set():
                print("A burst is already in progress. Use 'stop' to cancel remaining trades first.")
            else:
                started = engine.start_burst()
                if started:
                    print(f"Burst started: 1-3 trades, one per symbol, over the next "
                          f"{config.BURST_WINDOW_MINUTES} minutes. Type 'status' to check progress.")
        elif cmd == "stop":
            if not engine.running.is_set():
                print("No burst in progress.")
            else:
                engine.cancel_burst()
                print("Cancelling any not-yet-fired trades in this burst. Existing positions untouched.")
        elif cmd == "status":
            print_status(connector, engine)
        elif cmd == "closeall":
            confirm = ask_yes_no("Close ALL bot-managed positions now?", False)
            if confirm:
                engine.close_all_bot_positions()
        elif cmd == "help":
            print(HELP_TEXT)
        elif cmd == "exit":
            print("Stopping and disconnecting...")
            engine.stop_requested.set()
            engine.cancel_burst()
            if engine.thread is not None:
                engine.thread.join(timeout=5)
            connector.disconnect()
            print("Goodbye.")
            break
        elif cmd == "":
            continue
        else:
            print(f"Unknown command '{cmd}'. Type 'help' for options.")


def main():
    run_setup_wizard()

    connector = MT5Connector()
    print("Connecting to MT5...")
    if not connector.connect():
        print("Could not connect to MT5. Check config.py / environment variables "
              "(MT5_LOGIN, MT5_PASSWORD, MT5_SERVER) and MT5_TERMINAL_PATH.")
        return

    acc = connector.account_info()
    if acc is None:
        print("Connected, but account_info() returned no data. Aborting startup — "
              "check the MT5 terminal is logged in and try again.")
        connector.disconnect()
        return
    print(f"\nConnected: account {acc.login} on {config.MT5_SERVER} "
          f"| balance={acc.balance:.2f} equity={acc.equity:.2f} leverage=1:{acc.leverage}\n")

    risk = RiskManager(connector)
    engine = BotEngine(connector, risk)

    try:
        command_loop(connector, engine)
    except Exception:
        logger.exception("Fatal error in command loop")
        engine.stop_requested.set()
        engine.cancel_burst()
        connector.disconnect()


if __name__ == "__main__":
    main()
