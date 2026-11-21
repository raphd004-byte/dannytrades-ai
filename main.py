"""
Main loop for the SMC/ICT MT5 bot.

Flow per cycle, per symbol:
  1. Pull HTF + LTF candles from MT5.
  2. Run SMC/ICT analysis on both timeframes.
  3. Build a trade idea (HTF bias + LTF liquidity sweep + order block/FVG entry).
  4. Apply session filter, sentiment veto, and risk checks.
  5. Size the position and send the order (or log it, if DRY_RUN).

Run with:  python main.py
Stop with: Ctrl+C
"""

import logging
import time
from datetime import datetime, timezone

import config
import smc_ict
import sentiment
from mt5_connector import MT5Connector
from risk_manager import RiskManager
from track_record import TrackRecord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler(config.LOG_FILE), logging.StreamHandler()],
)
logger = logging.getLogger("main")


def in_trading_session() -> bool:
    if not config.ONLY_TRADE_IN_SESSIONS:
        return True
    now = datetime.now(timezone.utc).strftime("%H:%M")
    for _, (start, end) in config.TRADE_SESSIONS.items():
        if start <= now <= end:
            return True
    return False


def already_in_symbol(connector: MT5Connector, symbol: str) -> bool:
    return len(connector.open_positions(symbol)) > 0


def process_symbol(connector: MT5Connector, risk: RiskManager, symbol: str):
    htf_rates = connector.get_rates(symbol, config.HTF_TIMEFRAME, 300)
    ltf_rates = connector.get_rates(symbol, config.LTF_TIMEFRAME, 300)
    if htf_rates is None or ltf_rates is None or len(htf_rates) < 50 or len(ltf_rates) < 50:
        logger.warning("Insufficient data for %s, skipping", symbol)
        return

    htf_analysis = smc_ict.analyze(htf_rates, symbol)
    ltf_analysis = smc_ict.analyze(ltf_rates, symbol)

    tick = connector.get_symbol_info(symbol)
    if tick is None:
        return
    current_price = (tick.bid + tick.ask) / 2

    idea = smc_ict.build_trade_idea(htf_analysis, ltf_analysis, current_price, symbol)
    if idea is None:
        logger.info("%s: no valid SMC/ICT setup this cycle", symbol)
        return

    logger.info("%s: candidate setup -> %s", symbol, idea)

    if already_in_symbol(connector, symbol):
        logger.info("%s: already have an open position, skipping", symbol)
        return

    if risk.max_positions_reached():
        logger.info("Max open positions reached, skipping %s", symbol)
        return

    if risk.daily_loss_limit_hit():
        logger.warning("Daily loss limit hit, halting new entries")
        return

    if not sentiment.sentiment_allows_trade(symbol, idea["direction"]):
        logger.info("%s: sentiment veto blocked the %s setup", symbol, idea["direction"])
        return

    lots = risk.calc_position_size(symbol, idea["entry"], idea["stop_loss"])
    if lots <= 0:
        logger.warning("%s: computed lot size is 0, skipping", symbol)
        return

    result = connector.send_market_order(
        symbol=symbol,
        direction=idea["direction"],
        volume=lots,
        sl=idea["stop_loss"],
        tp=idea["take_profit"],
        comment=idea["reason"][:60],
    )
    logger.info("%s: order result -> %s", symbol, result)


def main():
    connector = MT5Connector()
    if not connector.connect():
        logger.error("Could not connect to MT5. Check config.py credentials/server/terminal path.")
        return

    track = TrackRecord(save_path="track_record.json", logger=logger)
    risk = RiskManager(connector)
    logger.info("Bot started. DRY_RUN=%s", config.DRY_RUN)

    try:
        while True:
            if not in_trading_session():
                logger.info("Outside configured trading sessions, idling...")
                time.sleep(config.LOOP_INTERVAL_SECONDS)
                continue

            for symbol in config.SYMBOLS:
                try:
                    process_symbol(connector, risk, symbol)
                except Exception:
                    logger.exception("Error processing %s", symbol)

            time.sleep(config.LOOP_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("Shutting down (Ctrl+C)")
    finally:
        connector.disconnect()


if __name__ == "__main__":
    main()
