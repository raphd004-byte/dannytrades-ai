"""
Track record system for the SMC/ICT MT5 bot.

Records every trade (entry + exit), calculates dynamic profitability metrics,
persists to a JSON file, and exports to CSV.

Built-in metrics:
  - Net profit / Gross profit / Gross loss
  - Win rate / Profit factor / Expectancy
  - Number of trades / Average R:R / Max drawdown
  - Best / worst trade / Trade count by symbol/direction

Usage:
    from track_record import TrackRecord

    tr = TrackRecord(save_path="track_record.json")
    tr.record_entry(ticket, symbol, direction, entry_price, lot_size, strategy, magic, comment)
    tr.record_exit(ticket, exit_price, profit_loss)
    metrics = tr.get_metrics()
    print(tr.export_csv("track_record.csv"))
"""

import csv
import json
import logging
import os
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone

logger = logging.getLogger("track_record")


@dataclass
class TradeRecord:
    """A single trade record: entry + exit together."""
    ticket: int
    symbol: str
    direction: str          # "buy" or "sell"
    entry_price: float
    exit_price: float
    lot_size: float
    profit_loss: float      # positive = win, negative = loss
    entry_time: str         # ISO timestamp
    exit_time: str          # ISO timestamp (same as entry_time if still open)
    strategy_type: str      # " smc_ict", "burst_fallback", "breakout", etc.
    magic_number: int
    comment: str
    closed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class TrackRecord:
    """
    Manages trade records and calculates dynamic profitability metrics.

    Loads existing records from disk on construction, so the track record
    survives bot restarts. Accepts a lock for thread-safe access.
    """

    def __init__(self, save_path: str = "track_record.json", logger=None):
        self.save_path = save_path
        self.logger = logger or logging.getLogger("track_record")
        self.trades: list[TradeRecord] = []
        self._lock = threading.Lock()
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not os.path.exists(self.save_path):
            self.trades = []
            return
        try:
            with open(self.save_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.trades = [TradeRecord(**t) for t in data]
            self.logger.info("Loaded %d trade record(s) from %s", len(self.trades), self.save_path)
        except Exception as exc:
            self.logger.error("Failed to load track record from %s: %s", self.save_path, exc)
            self.trades = []

    def _save(self) -> None:
        try:
            tmp = self.save_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump([t.to_dict() for t in self.trades], f, indent=2, default=str)
            os.replace(tmp, self.save_path)
        except Exception as exc:
            self.logger.error("Failed to save track record to %s: %s", self.save_path, exc)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record_entry(
        self,
        ticket: int,
        symbol: str,
        direction: str,
        entry_price: float,
        lot_size: float,
        strategy_type: str,
        magic_number: int = 0,
        comment: str = "",
    ) -> None:
        """Record a trade entry. A record is held open until record_exit() is called."""
        with self._lock:
            # Remove any existing open record for this ticket (idempotent)
            self.trades = [t for t in self.trades if not (t.ticket == ticket and not t.closed)]
            entry_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            record = TradeRecord(
                ticket=ticket,
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                exit_price=0.0,
                lot_size=lot_size,
                profit_loss=0.0,
                entry_time=entry_time,
                exit_time=entry_time,
                strategy_type=strategy_type,
                magic_number=magic_number,
                comment=comment,
                closed=False,
            )
            self.trades.append(record)
            self._save()
            self.logger.info("Recorded trade entry #%d on %s (%s)", ticket, symbol, direction)

    def record_exit(self, ticket: int, exit_price: float, profit_loss: float) -> TradeRecord | None:
        """Close a trade record and set its final profit/loss. Returns the record or None if not found."""
        with self._lock:
            for record in self.trades:
                if record.ticket == ticket and not record.closed:
                    record.exit_price = exit_price
                    record.profit_loss = profit_loss
                    record.exit_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    record.closed = True
                    self._save()
                    self.logger.info("Recorded exit for ticket #%d: profit=%+.2f", ticket, profit_loss)
                    return record
            self.logger.warning("No open record found for ticket #%d", ticket)
            return None

    # ------------------------------------------------------------------
    # Metrics (dynamic — recalculated on every call)
    # ------------------------------------------------------------------
    def get_metrics(self) -> dict:
        """Calculate and return all profitability metrics from the full trade history."""
        with self._lock:
            closed = [t for t in self.trades if t.closed]
            open_trades = [t for t in self.trades if not t.closed]

        if not closed:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "net_profit": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "avg_profit_per_trade": 0.0,
                "avg_winning_trade": 0.0,
                "avg_losing_trade": 0.0,
                "max_drawdown": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
                "avg_win_rate": 0.0,
                "open_trades": len(open_trades),
                "avg_rr": 0.0,
                "trades_by_symbol": {},
                "trades_by_direction": {},
            }

        net_profit = sum(t.profit_loss for t in closed)
        gross_profit = sum(t.profit_loss for t in closed if t.profit_loss > 0)
        gross_loss = abs(sum(t.profit_loss for t in closed if t.profit_loss < 0))
        winning = [t for t in closed if t.profit_loss > 0]
        losing = [t for t in closed if t.profit_loss < 0]

        win_rate = len(winning) / len(closed) * 100
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        expectancy = (net_profit / len(closed)) if closed else 0.0

        avg_winning = sum(t.profit_loss for t in winning) / len(winning) if winning else 0.0
        avg_losing = sum(t.profit_loss for t in losing) / len(losing) if losing else 0.0
        avg_rr_trades = [t for t in closed if t.profit_loss != 0]
        avg_rr = sum(t.profit_loss for t in avg_rr_trades) / len(avg_rr_trades) if avg_rr_trades else 0.0

        # Max drawdown from running equity (assuming starting balance of 0)
        running = 0.0
        max_equity = 0.0
        max_drawdown = 0.0
        for t in sorted(closed, key=lambda x: x.entry_time):
            running += t.profit_loss
            max_equity = max(max_equity, running)
            max_drawdown = min(max_drawdown, running - max_equity)

        trades_by_symbol = {}
        trades_by_direction = {}
        for t in closed:
            trades_by_symbol[t.symbol] = trades_by_symbol.get(t.symbol, 0) + 1
            trades_by_direction[t.direction] = trades_by_direction.get(t.direction, 0) + 1

        return {
            "total_trades": len(closed),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "net_profit": round(net_profit, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
            "expectancy": round(expectancy, 2),
            "avg_profit_per_trade": round(net_profit / len(closed), 2),
            "avg_winning_trade": round(avg_winning, 2),
            "avg_losing_trade": round(avg_losing, 2),
            "max_drawdown": round(max_drawdown, 2),
            "best_trade": round(max(t.profit_loss for t in closed), 2),
            "worst_trade": round(min(t.profit_loss for t in closed), 2),
            "avg_rr": round(avg_rr, 2),
            "open_trades": len(open_trades),
            "trades_by_symbol": trades_by_symbol,
            "trades_by_direction": trades_by_direction,
        }

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    def get_trade_by_ticket(self, ticket: int) -> TradeRecord | None:
        with self._lock:
            for t in self.trades:
                if t.ticket == ticket:
                    return t
        return None

    def get_all_trades(self) -> list[TradeRecord]:
        with self._lock:
            return list(self.trades)

    def export_csv(self, path: str = "track_record.csv") -> str:
        """Export all trades to a CSV file. Returns the path written."""
        with self._lock:
            rows = [asdict(t) for t in self.trades]
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                if rows:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
            self.logger.info("Exported %d trade record(s) to %s", len(rows), path)
            return path
        except Exception as exc:
            self.logger.error("Failed to export CSV: %s", exc)
            return ""

    def get_open_trades(self) -> list[TradeRecord]:
        with self._lock:
            return [t for t in self.trades if not t.closed]
