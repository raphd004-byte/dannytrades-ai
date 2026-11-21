"""
Smart Money Concepts / ICT detection engine.

Implements, from OHLC candle arrays:
  - Swing highs/lows (fractals)
  - Market structure: Break of Structure (BOS) and Change of Character (CHoCH)
  - Order blocks (last opposing candle before an impulsive BOS)
  - Fair Value Gaps (FVG) / imbalances
  - Equal highs/lows (liquidity pools)
  - Liquidity sweeps (stop hunts: wick through a liquidity pool that closes back inside range)

Input candle format: a list/array of dicts or numpy structured array with
fields: time, open, high, low, close (matches MetaTrader5.copy_rates_from_pos output).

This is pattern-detection logic, not a guaranteed profitable strategy.
Backtest and validate before trusting it with real capital.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import config


class Direction(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NONE = "none"


@dataclass
class Swing:
    index: int
    price: float
    kind: str  # "high" or "low"


@dataclass
class OrderBlock:
    index: int
    high: float
    low: float
    direction: Direction
    mitigated: bool = False


@dataclass
class FairValueGap:
    start_index: int
    end_index: int
    top: float
    bottom: float
    direction: Direction
    mitigated: bool = False


@dataclass
class LiquidityPool:
    price: float
    kind: str  # "equal_highs" or "equal_lows"
    indices: List[int] = field(default_factory=list)
    swept: bool = False


@dataclass
class MarketStructureEvent:
    index: int
    kind: str  # "BOS" or "CHoCH"
    direction: Direction
    price: float


@dataclass
class Analysis:
    bias: Direction
    swings: List[Swing]
    structure_events: List[MarketStructureEvent]
    order_blocks: List[OrderBlock]
    fvgs: List[FairValueGap]
    liquidity_pools: List[LiquidityPool]
    last_sweep: Optional[LiquidityPool]


def _pip_size(symbol: str) -> float:
    # Rough heuristic; JPY pairs and metals have different pip conventions.
    if "JPY" in symbol:
        return 0.01
    if symbol.startswith("XAU"):
        return 0.1
    return 0.0001


def find_swings(candles, lookback: int = config.SWING_LOOKBACK) -> List[Swing]:
    """Fractal-based swing high/low detection."""
    swings = []
    n = len(candles)
    for i in range(lookback, n - lookback):
        window = candles[i - lookback:i + lookback + 1]
        high = candles[i]["high"]
        low = candles[i]["low"]
        if high == max(c["high"] for c in window):
            swings.append(Swing(index=i, price=high, kind="high"))
        if low == min(c["low"] for c in window):
            swings.append(Swing(index=i, price=low, kind="low"))
    return swings


def detect_structure(candles, swings: List[Swing]) -> List[MarketStructureEvent]:
    """
    Detect Break of Structure (continuation) and Change of Character (reversal)
    by tracking sequences of higher-highs/higher-lows vs lower-highs/lower-lows.
    """
    events = []
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return events

    trend = Direction.NONE
    last_high = highs[0]
    last_low = lows[0]

    ordered = sorted(swings, key=lambda s: s.index)
    for s in ordered:
        close = candles[s.index]["close"]
        if s.kind == "high":
            if close > last_high.price and trend != Direction.BULLISH:
                kind = "CHoCH" if trend == Direction.BEARISH else "BOS"
                events.append(MarketStructureEvent(s.index, kind, Direction.BULLISH, close))
                trend = Direction.BULLISH
            last_high = s
        else:
            if close < last_low.price and trend != Direction.BEARISH:
                kind = "CHoCH" if trend == Direction.BULLISH else "BOS"
                events.append(MarketStructureEvent(s.index, kind, Direction.BEARISH, close))
                trend = Direction.BEARISH
            last_low = s
    return events


def find_order_blocks(candles, structure_events: List[MarketStructureEvent]) -> List[OrderBlock]:
    """
    For each bullish structure break, the order block is the last down-close candle
    before the impulsive move. For bearish breaks, the last up-close candle.
    """
    obs = []
    for event in structure_events:
        start = max(0, event.index - config.ORDER_BLOCK_LOOKBACK)
        segment = candles[start:event.index]
        for i in range(len(segment) - 1, -1, -1):
            c = segment[i]
            is_down = c["close"] < c["open"]
            is_up = c["close"] > c["open"]
            if event.direction == Direction.BULLISH and is_down:
                obs.append(OrderBlock(
                    index=start + i, high=c["high"], low=c["low"], direction=Direction.BULLISH
                ))
                break
            if event.direction == Direction.BEARISH and is_up:
                obs.append(OrderBlock(
                    index=start + i, high=c["high"], low=c["low"], direction=Direction.BEARISH
                ))
                break
    return obs


def find_fvgs(candles, symbol: str) -> List[FairValueGap]:
    """
    Three-candle Fair Value Gap: gap between candle[i-1].high and candle[i+1].low (bullish)
    or candle[i-1].low and candle[i+1].high (bearish), where candle i is the impulsive middle bar.
    """
    fvgs = []
    pip = _pip_size(symbol)
    min_size = config.FVG_MIN_SIZE_PIPS * pip
    for i in range(1, len(candles) - 1):
        prev_c, next_c = candles[i - 1], candles[i + 1]
        # bullish FVG
        if next_c["low"] > prev_c["high"] and (next_c["low"] - prev_c["high"]) >= min_size:
            fvgs.append(FairValueGap(i - 1, i + 1, next_c["low"], prev_c["high"], Direction.BULLISH))
        # bearish FVG
        if prev_c["low"] > next_c["high"] and (prev_c["low"] - next_c["high"]) >= min_size:
            fvgs.append(FairValueGap(i - 1, i + 1, prev_c["low"], next_c["high"], Direction.BEARISH))
    return fvgs


def find_liquidity_pools(candles, swings: List[Swing], symbol: str) -> List[LiquidityPool]:
    """Cluster swing highs/lows that sit at approximately the same price = resting liquidity."""
    pip = _pip_size(symbol)
    tolerance = config.EQUAL_HL_TOLERANCE_PIPS * pip
    pools = []

    for kind, key in (("equal_highs", "high"), ("equal_lows", "low")):
        candidates = sorted([s for s in swings if s.kind == key.replace("high", "high").replace("low", "low")
                              or (kind == "equal_highs" and s.kind == "high")
                              or (kind == "equal_lows" and s.kind == "low")],
                             key=lambda s: s.price)
        used = set()
        for s in candidates:
            if s.index in used:
                continue
            cluster = [c for c in candidates if abs(c.price - s.price) <= tolerance]
            if len(cluster) >= 2:
                for c in cluster:
                    used.add(c.index)
                avg_price = sum(c.price for c in cluster) / len(cluster)
                pools.append(LiquidityPool(price=avg_price, kind=kind, indices=[c.index for c in cluster]))
    return pools


def detect_sweep(candles, pools: List[LiquidityPool]) -> Optional[LiquidityPool]:
    """
    A liquidity sweep = price wicks through a pool level then closes back on the
    other side within the same or next candle (stop hunt before reversal).
    Checks only the most recent candles for a fresh sweep.
    """
    if not candles or not pools:
        return None
    last = candles[-1]
    rng = last["high"] - last["low"]
    if rng <= 0:
        return None

    for pool in pools:
        if pool.kind == "equal_highs" and last["high"] > pool.price and last["close"] < pool.price:
            wick = last["high"] - max(last["open"], last["close"])
            if wick / rng >= config.LIQUIDITY_SWEEP_WICK_RATIO:
                pool.swept = True
                return pool
        if pool.kind == "equal_lows" and last["low"] < pool.price and last["close"] > pool.price:
            wick = min(last["open"], last["close"]) - last["low"]
            if wick / rng >= config.LIQUIDITY_SWEEP_WICK_RATIO:
                pool.swept = True
                return pool
    return None


def analyze(candles, symbol: str) -> Analysis:
    """Run the full SMC/ICT analysis pipeline on a candle array for one timeframe."""
    candles = [
        {"time": c["time"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
        for c in candles
    ]
    swings = find_swings(candles)
    structure_events = detect_structure(candles, swings)
    order_blocks = find_order_blocks(candles, structure_events)
    fvgs = find_fvgs(candles, symbol)
    pools = find_liquidity_pools(candles, swings, symbol)
    sweep = detect_sweep(candles, pools)

    bias = Direction.NONE
    if structure_events:
        bias = structure_events[-1].direction

    return Analysis(
        bias=bias,
        swings=swings,
        structure_events=structure_events,
        order_blocks=order_blocks,
        fvgs=fvgs,
        liquidity_pools=pools,
        last_sweep=sweep,
    )


def build_trade_idea(htf_analysis: Analysis, ltf_analysis: Analysis, current_price: float, symbol: str):
    """
    Core ICT-style confluence rule used by this bot:
      1. HTF bias sets allowed direction (only trade with HTF structure).
      2. LTF must show a liquidity sweep in the direction that would trap
         counter-trend traders (i.e. sweep of lows in a bullish HTF bias).
      3. Price must be at/near an unmitigated order block or FVG in the LTF,
         aligned with HTF bias, for entry.

    Returns a dict describing the trade idea, or None if no valid setup.
    """
    if htf_analysis.bias == Direction.NONE:
        return None

    direction = htf_analysis.bias
    sweep = ltf_analysis.last_sweep
    if sweep is None:
        return None
    if direction == Direction.BULLISH and sweep.kind != "equal_lows":
        return None
    if direction == Direction.BEARISH and sweep.kind != "equal_highs":
        return None

    # find nearest unmitigated order block or FVG aligned with direction
    zones = [ob for ob in ltf_analysis.order_blocks if ob.direction == direction and not ob.mitigated]
    zones += [f for f in ltf_analysis.fvgs if f.direction == direction and not f.mitigated]
    if not zones:
        return None

    def zone_bounds(z):
        if isinstance(z, OrderBlock):
            return z.low, z.high
        return z.bottom, z.top

    nearest = min(zones, key=lambda z: abs(current_price - sum(zone_bounds(z)) / 2))
    low, high = zone_bounds(nearest)

    if direction == Direction.BULLISH:
        entry = high
        stop = low - (config.SL_BUFFER_PIPS * _pip_size(symbol))
    else:
        entry = low
        stop = high + (config.SL_BUFFER_PIPS * _pip_size(symbol))

    risk = abs(entry - stop)
    target = entry + risk * config.MIN_RR_RATIO if direction == Direction.BULLISH else entry - risk * config.MIN_RR_RATIO

    return {
        "symbol": symbol,
        "direction": "buy" if direction == Direction.BULLISH else "sell",
        "entry": entry,
        "stop_loss": stop,
        "take_profit": target,
        "rr": config.MIN_RR_RATIO,
        "reason": f"HTF bias={direction.value}, LTF liquidity sweep={sweep.kind}, zone={type(nearest).__name__}",
    }
