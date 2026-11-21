"""
MT5 connection and order execution wrapper for FBS (or any MT5 broker).

Requires the MetaTrader5 package and a locally installed MT5 terminal —
this only works on Windows (or Wine on Linux), because the MT5 Python API
talks to a running terminal process, not a remote server directly.

    pip install MetaTrader5
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # allows the rest of the codebase to be imported/tested on non-Windows

import config

logger = logging.getLogger("mt5_connector")

def record_trade_exit(ticket, exit_price, profit_loss):
    """Record a trade exit in the track record (see track_record.py)."""
    try:
        from track_record import TrackRecord
        if not hasattr(record_trade_exit, "_instance"):
            record_trade_exit._instance = TrackRecord(save_path="track_record.json", logger=logger)
        record_trade_exit._instance.record_exit(ticket=ticket, exit_price=exit_price, profit_loss=profit_loss)
    except Exception:
        logger.exception("Failed to record trade exit")


def record_trade_entry(ticket, symbol, direction, entry_price, lot_size, strategy_type, magic_number, comment):
    """Record a trade entry in the track record (see track_record.py)."""
    try:
        from track_record import TrackRecord
        if not hasattr(record_trade_entry, "_instance"):
            record_trade_entry._instance = TrackRecord(save_path="track_record.json", logger=logger)
        record_trade_entry._instance.record_entry(
            ticket=ticket, symbol=symbol, direction=direction,
            entry_price=entry_price, lot_size=lot_size,
            strategy_type=strategy_type, magic_number=magic_number, comment=comment,
        )
    except Exception:
        logger.exception("Failed to record trade entry")


@dataclass
class TradeResult:
    success: bool
    ticket: Optional[int] = None
    message: str = ""


class MT5Connector:
    def __init__(self):
        self.connected = False

    def connect(self) -> bool:
        if mt5 is None:
            raise RuntimeError(
                "MetaTrader5 package not available. This module must run on Windows "
                "with the MT5 terminal installed, or under Wine."
            )

        init_kwargs = {}
        if config.MT5_TERMINAL_PATH:
            init_kwargs["path"] = config.MT5_TERMINAL_PATH

        if not mt5.initialize(**init_kwargs):
            logger.error("initialize() failed: %s", mt5.last_error())
            return False

        authorized = mt5.login(
            login=config.MT5_LOGIN,
            password=config.MT5_PASSWORD,
            server=config.MT5_SERVER,
        )
        if not authorized:
            logger.error("login() failed: %s", mt5.last_error())
            mt5.shutdown()
            return False

        self.connected = True
        acc = mt5.account_info()
        if acc is None:
            logger.warning("Connected to %s but account_info() returned None: %s",
                           config.MT5_SERVER, mt5.last_error())
        else:
            logger.info(
                "Connected to %s | account=%s balance=%.2f equity=%.2f leverage=1:%s",
                config.MT5_SERVER, acc.login, acc.balance, acc.equity, acc.leverage,
            )
        return True

    def disconnect(self):
        if mt5 is not None:
            mt5.shutdown()
        self.connected = False

    def account_info(self):
        return mt5.account_info()

    def get_symbol_info(self, symbol: str):
        info = mt5.symbol_info(symbol)
        if info is None:
            logger.warning("Symbol %s not found, attempting to select it", symbol)
            mt5.symbol_select(symbol, True)
            info = mt5.symbol_info(symbol)
        return info

    def get_rates(self, symbol: str, timeframe: str, count: int = 300):
        tf_map = {
            "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
        }
        tf = tf_map[timeframe]
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None:
            logger.error("copy_rates_from_pos failed for %s %s: %s", symbol, timeframe, mt5.last_error())
        return rates

    def open_positions(self, symbol: Optional[str] = None):
        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        return positions or []

    def send_market_order(
        self,
        symbol: str,
        direction: str,     # "buy" or "sell"
        volume: float,
        sl: float,
        tp: float,
        comment: str = "smc-ict-bot",
    ) -> TradeResult:
        if not self.connected:
            return TradeResult(False, message="Not connected to MT5 terminal")

        info = self.get_symbol_info(symbol)
        if info is None:
            return TradeResult(False, message=f"Symbol {symbol} unavailable")

        # A valid symbol_info() doesn't guarantee the symbol is active in
        # Market Watch on this broker; some brokers still reject orders (or
        # return no tick) on symbols that aren't selected/visible.
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                err = mt5.last_error()
                logger.error("symbol_select failed for %s: %s", symbol, err)
                return TradeResult(False, message=f"symbol_select failed: {err}")

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            err = mt5.last_error()
            logger.error("symbol_info_tick returned None for %s: %s", symbol, err)
            return TradeResult(False, message=f"no tick for {symbol}: {err}")

        price = tick.ask if direction == "buy" else tick.bid
        order_type = mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": config.MAGIC_NUMBER,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        if config.DRY_RUN:
            logger.info("[DRY_RUN] Would send order: %s", request)
            return TradeResult(True, ticket=-1, message="dry_run")

        result = mt5.order_send(request)

        if result is None:
            err = mt5.last_error()
            logger.error("order_send returned None for %s: last_error=%s request=%s", symbol, err, request)
            return TradeResult(False, message=f"order_send returned None, last_error={err}")

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error("order_send failed: retcode=%s comment=%s", result.retcode, result.comment)
            return TradeResult(False, message=f"retcode={result.retcode} {result.comment}")

        logger.info("Order filled: ticket=%s %s %s vol=%s @ %s SL=%s TP=%s",
                     result.order, direction, symbol, volume, price, sl, tp)

        # Auto-register trade entry
        try:
            record_trade_entry(result.order, symbol, direction, price, volume,
                               "smc_ict", config.MAGIC_NUMBER, comment)
        except Exception:
            logger.exception("Failed to record trade entry in track record")

        return TradeResult(True, ticket=result.order)

    def close_position(self, position) -> TradeResult:
        if not self.connected:
            return TradeResult(False, message="Not connected to MT5 terminal")

        symbol = position.symbol
        volume = position.volume
        direction = "sell" if position.type == mt5.POSITION_TYPE_BUY else "buy"
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            err = mt5.last_error()
            logger.error("symbol_info_tick returned None for %s: %s", symbol, err)
            return TradeResult(False, message=f"no tick for {symbol}: {err}")
        price = tick.bid if direction == "sell" else tick.ask
        order_type = mt5.ORDER_TYPE_SELL if direction == "sell" else mt5.ORDER_TYPE_BUY

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "position": position.ticket,
            "price": price,
            "deviation": 20,
            "magic": config.MAGIC_NUMBER,
            "comment": "smc-ict-bot-close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        if config.DRY_RUN:
            logger.info("[DRY_RUN] Would close position: %s", position.ticket)
            return TradeResult(True, ticket=position.ticket, message="dry_run")

        result = mt5.order_send(request)

        if result is None:
            err = mt5.last_error()
            logger.error("order_send (close) returned None for %s: last_error=%s", symbol, err)
            return TradeResult(False, message=f"order_send returned None, last_error={err}")

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return TradeResult(False, message=f"retcode={result.retcode} {result.comment}")

        # Record exit and profit/loss
        try:
            profit = position.profit if hasattr(position, "profit") else 0.0
            record_trade_exit(position.ticket, price, profit)
        except Exception:
            logger.exception("Failed to record trade exit in track record")

        return TradeResult(True, ticket=result.order)
