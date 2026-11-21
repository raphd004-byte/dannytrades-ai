"""
Position sizing and account-level risk controls.
"""

import logging
from datetime import datetime, timezone

import config

logger = logging.getLogger("risk_manager")


class RiskManager:
    def __init__(self, connector):
        self.connector = connector
        self._day = datetime.now(timezone.utc).date()
        self._equity_at_day_start = None

    def _refresh_day(self, equity: float):
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self._equity_at_day_start = equity
        if self._equity_at_day_start is None:
            self._equity_at_day_start = equity

    def daily_loss_limit_hit(self) -> bool:
        acc = self.connector.account_info()
        if acc is None:
            return False
        self._refresh_day(acc.equity)
        drawdown_pct = (self._equity_at_day_start - acc.equity) / self._equity_at_day_start * 100
        if drawdown_pct >= config.MAX_DAILY_LOSS_PCT:
            logger.warning("Daily loss limit hit: %.2f%% drawdown", drawdown_pct)
            return True
        return False

    def max_positions_reached(self) -> bool:
        open_positions = self.connector.open_positions()
        return len(open_positions) >= config.MAX_OPEN_POSITIONS

    def _clamp_to_broker_limits(self, info, lots: float) -> float:
        step = info.volume_step or 0.01
        lots = max(info.volume_min, min(info.volume_max, round(lots / step) * step))
        return round(lots, 2)

    def _apply_leverage_cap(self, acc, info, entry: float, lots: float) -> float:
        """If LEVERAGE_CAP is set, shrink lots so required notional never exceeds
        equity * LEVERAGE_CAP, independent of what the broker would otherwise allow."""
        if not config.LEVERAGE_CAP:
            return lots
        contract_size = getattr(info, "trade_contract_size", 100000) or 100000
        notional = lots * contract_size * entry
        max_notional = acc.equity * config.LEVERAGE_CAP
        if notional > max_notional and notional > 0:
            scale = max_notional / notional
            lots = lots * scale
        return lots

    def calc_position_size(self, symbol: str, entry: float, stop_loss: float) -> float:
        """
        Position size (lots). In "auto" mode, sized so a stop-out risks
        RISK_PER_TRADE_PCT of equity. In "fixed" mode, always FIXED_LOT_SIZE.
        Either way, clamped by broker volume limits and, if set, LEVERAGE_CAP.
        """
        acc = self.connector.account_info()
        info = self.connector.get_symbol_info(symbol)
        if acc is None or info is None:
            return 0.0

        if config.LOT_SIZE_MODE == "fixed":
            lots = config.FIXED_LOT_SIZE
        else:
            risk_amount = acc.equity * (config.RISK_PER_TRADE_PCT / 100)
            price_distance = abs(entry - stop_loss)
            if price_distance <= 0:
                return 0.0

            tick_size = info.trade_tick_size or info.point
            tick_value = info.trade_tick_value or 1.0
            ticks = price_distance / tick_size
            loss_per_lot = ticks * tick_value
            if loss_per_lot <= 0:
                return 0.0

            lots = risk_amount / loss_per_lot

        lots = self._apply_leverage_cap(acc, info, entry, lots)
        return self._clamp_to_broker_limits(info, lots)
