"""
Backtesting harness for the SMC/ICT strategy in smc_ict.py.

This replays historical candles bar-by-bar through the SAME analysis and
trade-idea logic the live bot uses, simulates fills/stop-outs, and reports
win rate, average R, and an equity curve. Use this BEFORE running the bot
live to sanity-check whether the current rules have any edge on your
symbols/timeframes.

Data input: two CSV files (one per timeframe) exported from MT5.
In MT5: right-click a chart -> "Save As" / or use the Strategy Tester's
History Center "Export" button. Expected columns (header row required):
    time,open,high,low,close
`time` can be an MT5-style "YYYY.MM.DD HH:MM" string or a unix timestamp.

Usage:
    python backtest.py --symbol EURUSD --htf-csv eurusd_h4.csv --ltf-csv eurusd_m15.csv

Optional:
    --initial-balance 1000
    --max-bars 3000        (limits runtime; 0 = use all available bars)
    --window 300            (bars of history fed into the analyzer each step)
"""

import argparse
import csv
import logging
from datetime import datetime

import config
import smc_ict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backtest")


def _parse_time(raw: str):
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    for fmt in ("%Y.%m.%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.strptime(raw, fmt).timestamp())
        except ValueError:
            continue
    raise ValueError(f"Unrecognized time format: {raw}")


def load_csv(path: str):
    candles = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        # normalize header names (MT5 exports sometimes use <DATE>,<TIME>,<OPEN>... etc.)
        fieldmap = {k.lower().strip("<>"): k for k in reader.fieldnames}
        for row in reader:
            try:
                if "time" in fieldmap:
                    t = _parse_time(row[fieldmap["time"]])
                elif "date" in fieldmap and "time" in fieldmap:
                    t = _parse_time(f"{row[fieldmap['date']]} {row[fieldmap['time']]}")
                else:
                    raise KeyError("no time/date column found")
                candles.append({
                    "time": t,
                    "open": float(row[fieldmap["open"]]),
                    "high": float(row[fieldmap["high"]]),
                    "low": float(row[fieldmap["low"]]),
                    "close": float(row[fieldmap["close"]]),
                })
            except Exception as e:
                logger.debug("Skipping row (%s): %s", e, row)
    candles.sort(key=lambda c: c["time"])
    return candles


def htf_slice_up_to(htf_candles, cutoff_time, window):
    """Return the last `window` HTF candles with time <= cutoff_time."""
    eligible = [c for c in htf_candles if c["time"] <= cutoff_time]
    return eligible[-window:]


class SimPosition:
    def __init__(self, symbol, direction, entry, sl, tp, risk_amount):
        self.symbol = symbol
        self.direction = direction  # "buy" / "sell"
        self.entry = entry
        self.sl = sl
        self.tp = tp
        self.risk_amount = risk_amount
        self.open_index = None

    def check_exit(self, candle):
        """Returns ('tp'|'sl', price) if this candle closes the trade, else None."""
        if self.direction == "buy":
            if candle["low"] <= self.sl:
                return "sl", self.sl
            if candle["high"] >= self.tp:
                return "tp", self.tp
        else:
            if candle["high"] >= self.sl:
                return "sl", self.sl
            if candle["low"] <= self.tp:
                return "tp", self.tp
        return None


def run_backtest(symbol, htf_candles, ltf_candles, initial_balance, max_bars, window):
    equity = initial_balance
    equity_curve = [(ltf_candles[window]["time"], equity)] if len(ltf_candles) > window else []
    trades = []
    open_pos = None

    start = window
    end = len(ltf_candles) if max_bars == 0 else min(len(ltf_candles), start + max_bars)

    for i in range(start, end):
        candle = ltf_candles[i]

        # manage open position first
        if open_pos is not None:
            outcome = open_pos.check_exit(candle)
            if outcome is not None:
                kind, _price = outcome
                r_multiple = config.MIN_RR_RATIO if kind == "tp" else -1.0
                pnl = open_pos.risk_amount * r_multiple
                equity += pnl
                trades.append({
                    "symbol": symbol, "direction": open_pos.direction,
                    "entry": open_pos.entry, "exit_kind": kind,
                    "r_multiple": r_multiple, "pnl": pnl, "equity_after": equity,
                    "time": candle["time"],
                })
                equity_curve.append((candle["time"], equity))
                open_pos = None
            continue  # don't look for a new setup on the same bar we're managing one

        # look for a new setup
        ltf_window = ltf_candles[max(0, i - window):i + 1]
        htf_window = htf_slice_up_to(htf_candles, candle["time"], window)
        if len(ltf_window) < 50 or len(htf_window) < 50:
            continue

        htf_analysis = smc_ict.analyze(htf_window, symbol)
        ltf_analysis = smc_ict.analyze(ltf_window, symbol)
        idea = smc_ict.build_trade_idea(htf_analysis, ltf_analysis, candle["close"], symbol)
        if idea is None:
            continue

        risk_amount = equity * (config.RISK_PER_TRADE_PCT / 100)
        open_pos = SimPosition(symbol, idea["direction"], idea["entry"], idea["stop_loss"], idea["take_profit"], risk_amount)
        open_pos.open_index = i

        if (i - start) % 200 == 0:
            logger.info("Progress: bar %d/%d, equity=%.2f", i - start, end - start, equity)

    return trades, equity_curve


def summarize(trades, equity_curve, initial_balance):
    if not trades:
        print("\nNo trades were generated by the strategy over this period.")
        print("Try a longer date range, a different symbol, or loosen SMC parameters in config.py.")
        return

    wins = [t for t in trades if t["r_multiple"] > 0]
    losses = [t for t in trades if t["r_multiple"] <= 0]
    win_rate = len(wins) / len(trades) * 100
    avg_r = sum(t["r_multiple"] for t in trades) / len(trades)
    final_equity = equity_curve[-1][1] if equity_curve else initial_balance
    total_return_pct = (final_equity - initial_balance) / initial_balance * 100

    peak = initial_balance
    max_dd_pct = 0.0
    for _, eq in equity_curve:
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100
        max_dd_pct = max(max_dd_pct, dd)

    print("\n" + "=" * 50)
    print("BACKTEST SUMMARY")
    print("=" * 50)
    print(f"Total trades:      {len(trades)}")
    print(f"Wins / Losses:     {len(wins)} / {len(losses)}")
    print(f"Win rate:          {win_rate:.1f}%")
    print(f"Average R:         {avg_r:.2f}")
    print(f"Starting balance:  {initial_balance:.2f}")
    print(f"Final equity:      {final_equity:.2f}")
    print(f"Total return:      {total_return_pct:.1f}%")
    print(f"Max drawdown:      {max_dd_pct:.1f}%")
    print("=" * 50)
    print("\nReminder: this is a simplified simulator (no spread/slippage/commission,")
    print("fixed R:R exit only, no partial closes). Treat results as a rough filter,")
    print("not a profit guarantee. Always confirm on a demo account before going live.")


def save_trade_log(trades, path="backtest_trades.csv"):
    if not trades:
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
        writer.writeheader()
        writer.writerows(trades)
    print(f"\nTrade log saved to {path}")


def main():
    parser = argparse.ArgumentParser(description="Backtest the SMC/ICT strategy")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--htf-csv", required=True, help="CSV of higher-timeframe candles (e.g. H4)")
    parser.add_argument("--ltf-csv", required=True, help="CSV of lower-timeframe candles (e.g. M15)")
    parser.add_argument("--initial-balance", type=float, default=1000.0)
    parser.add_argument("--max-bars", type=int, default=3000, help="0 = use all available bars")
    parser.add_argument("--window", type=int, default=300, help="bars of history fed to the analyzer each step")
    args = parser.parse_args()

    logger.info("Loading candles...")
    htf_candles = load_csv(args.htf_csv)
    ltf_candles = load_csv(args.ltf_csv)
    logger.info("Loaded %d HTF candles, %d LTF candles", len(htf_candles), len(ltf_candles))

    if len(htf_candles) < 50 or len(ltf_candles) < 50:
        print("Not enough data. Export more history from MT5 and try again.")
        return

    trades, equity_curve = run_backtest(
        args.symbol, htf_candles, ltf_candles, args.initial_balance, args.max_bars, args.window
    )
    summarize(trades, equity_curve, args.initial_balance)
    save_trade_log(trades)


if __name__ == "__main__":
    main()
