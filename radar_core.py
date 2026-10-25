"""Ortak yardımcılar ve açıklanabilir aşama değerlendirmesi.

Bu modül otomatik alım-satım veya emir gönderimi içermez. A/B/C aşamaları
araştırma durumudur; bir işlem onayı veya kârlılık iddiası değildir.
"""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
import sys
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
REPORT_DIR = ROOT / "reports"
RUN_DIR = ROOT / "run"
for _folder in (DATA_DIR, LOG_DIR, REPORT_DIR, RUN_DIR):
    _folder.mkdir(parents=True, exist_ok=True)

APP_VERSION = "1A"

PHASE_ORDER = {"C": 3, "B": 2, "A": 1, None: 0}
TIMEFRAME_MS = {
    "1m": 60_000, "5m": 5 * 60_000, "15m": 15 * 60_000,
    "30m": 30 * 60_000, "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000, "1d": 24 * 60 * 60_000,
    "1w": 7 * 24 * 60 * 60_000,
}


def utc_now() -> str:
    # Keep sub-second precision: the UI compares state timestamps to the exact
    # process launch time to reject files left by a previous radar session.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def local_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def configure_utf8_console() -> None:
    """Make standalone console output safe for Turkish text on Windows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # Some embedded/redirected streams do not support reconfiguration.
            pass


def timeframe_bar_end_ms(timeframe: str, start_ms: int) -> int | None:
    """Return the true end timestamp for a UTC Binance bar, including calendar months."""
    start_ms = int(start_ms)
    if timeframe == "1M":
        start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        if start.day != 1 or any((start.hour, start.minute, start.second, start.microsecond)):
            return None
        if start.month == 12:
            end = datetime(start.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(start.year, start.month + 1, 1, tzinfo=timezone.utc)
        return int(end.timestamp() * 1000)
    interval_ms = TIMEFRAME_MS.get(timeframe)
    if interval_ms is None:
        return None
    return start_ms + interval_ms


def _timeframe_start_is_aligned(timeframe: str, start_ms: int) -> bool:
    start_ms = int(start_ms)
    if timeframe == "1M":
        start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        return (
            start.day == 1
            and start.hour == 0
            and start.minute == 0
            and start.second == 0
            and start.microsecond == 0
        )
    if timeframe == "1w":
        start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        return (
            start.weekday() == 0
            and start.hour == 0
            and start.minute == 0
            and start.second == 0
            and start.microsecond == 0
        )
    interval_ms = TIMEFRAME_MS.get(timeframe)
    return bool(interval_ms and start_ms % interval_ms == 0)


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Each write gets its own temporary file, so the independent radar processes
    # cannot overwrite each other's temporary output.
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())

        # On Windows, a short-lived reader (for example, the control panel or
        # endpoint protection software) can temporarily prevent replacement of
        # the destination file. Retry transient PermissionError instead of
        # failing the whole radar loop immediately.
        last_error: PermissionError | None = None
        # Windows readers/endpoint protection can hold the destination briefly.
        # Retry for up to roughly five seconds, with a bounded delay between attempts.
        for attempt in range(12):
            try:
                os.replace(temporary, path)
                return
            except PermissionError as exc:
                last_error = exc
                if attempt == 11:
                    raise
                time.sleep(min(0.10 * (attempt + 1), 0.50))
        if last_error is not None:
            raise last_error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def load_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def setup_logger(name: str, logfile: Path) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    for previous_handler in list(logger.handlers):
        try:
            previous_handler.close()
        except Exception:
            pass
    logger.handlers.clear()
    logfile.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    handler = RotatingFileHandler(logfile, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    logger.propagate = False
    return logger


def stop_requested(stop_file: str | Path) -> bool:
    return Path(stop_file).exists()


def normalize_bar(t: Any, o: Any, h: Any, l: Any, c: Any, v: Any,
                  q: Any = 0, n: Any = 0, closed: bool = True,
                  synthetic: bool = False) -> dict[str, Any]:
    if any(isinstance(value, bool) for value in (t, o, h, l, c, v, q, n)):
        raise ValueError("Mumun sayısal alanları boolean olamaz.")
    if not isinstance(closed, bool) or not isinstance(synthetic, bool):
        raise ValueError("Mumun closed ve synthetic alanları gerçek boolean olmalı.")
    bar = {
        "t": int(float(t)), "o": float(o), "h": float(h), "l": float(l),
        "c": float(c), "v": float(v or 0), "q": float(q or 0),
        "n": int(float(n or 0)), "closed": closed,
        "synthetic": synthetic,
    }
    if not all(math.isfinite(float(bar[key])) for key in ("t", "o", "h", "l", "c", "v", "q", "n")):
        raise ValueError("Mum verisinde NaN/sonsuz sayısal değer var; veri reddedildi.")
    return bar


def valid_bars(bars: list[dict[str, Any]], *, closed_only: bool = True,
               exclude_synthetic: bool = True) -> list[dict[str, Any]]:
    """Retain only finite, internally consistent OHLCV bars with usable timestamps."""
    output = []
    for bar in bars:
        try:
            # bool is a subclass of int in Python, but True/False are not valid
            # timestamps, prices, volumes, or trade counts in a market candle.
            if any(
                isinstance(bar.get(key), bool)
                for key in ("t", "o", "h", "l", "c", "v", "q", "n")
            ):
                continue
            open_, high, low, close = (float(bar[key]) for key in ("o", "h", "l", "c"))
            volume = float(bar.get("v", 0) or 0)
            quote_volume = float(bar.get("q", 0) or 0)
            timestamp = int(bar["t"])
            valid = all(math.isfinite(value) for value in (
                open_, high, low, close, volume, quote_volume,
            ))
            valid = valid and timestamp > 0
            valid = valid and min(open_, high, low, close) > 0
            valid = valid and high >= max(open_, low, close)
            valid = valid and low <= min(open_, high, close)
            valid = valid and volume >= 0 and quote_volume >= 0
            closed_flag = bar.get("closed", True)
            synthetic_flag = bar.get("synthetic", False)
            # These are schema flags, not values that can be safely truthiness-coerced:
            # e.g. bool("false") is True and could admit an unfinished candle.
            valid = valid and isinstance(closed_flag, bool) and isinstance(synthetic_flag, bool)
            if closed_only:
                valid = valid and closed_flag is True
            if exclude_synthetic:
                valid = valid and synthetic_flag is False
            if valid:
                output.append(bar)
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return sorted(output, key=lambda row: int(row["t"]))


def pct_change(bars: list[dict[str, Any]], lookback: int = 1,
               *, closed_only: bool = True) -> float | None:
    usable = valid_bars(bars, closed_only=closed_only)
    if len(usable) <= lookback:
        return None
    prior = float(usable[-lookback - 1]["c"])
    latest = float(usable[-1]["c"])
    if prior <= 0:
        return None
    return (latest / prior - 1.0) * 100.0


def percentile(values: list[float], q: float) -> float | None:
    sample = sorted(float(v) for v in values if math.isfinite(float(v)))
    if not sample:
        return None
    q = min(1.0, max(0.0, q))
    position = (len(sample) - 1) * q
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return sample[low]
    return sample[low] + (sample[high] - sample[low]) * (position - low)


def median(values: list[float]) -> float | None:
    cleaned = [float(v) for v in values if math.isfinite(float(v))]
    return statistics.median(cleaned) if cleaned else None


def true_ranges(bars: list[dict[str, Any]]) -> list[float]:
    result: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        high, low = float(bar["h"]), float(bar["l"])
        candidates = [high - low]
        if previous_close is not None:
            candidates.extend([abs(high - previous_close), abs(low - previous_close)])
        result.append(max(candidates))
        previous_close = float(bar["c"])
    return result


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    sample = values[-period:]
    return sum(sample) / period if all(math.isfinite(v) for v in sample) else None


def _positive_return_z(bars: list[dict[str, Any]], history_n: int = 40) -> float | None:
    """Son kapanmış mum getirisi / önceki getirilerin standart sapması.

    Son mum geçmiş dağılıma katılmaz. Bu, eşiklerin coin ve zaman dilimine göre
    ölçeklenmesine yardım eder; istatistiksel anlamlılık veya başarı olasılığı değildir.
    """
    closed = valid_bars(bars)
    if len(closed) < history_n + 2:
        return None
    closes = [float(b["c"]) for b in closed]
    returns = [(closes[i] / closes[i - 1] - 1.0) * 100.0
               for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(returns) < history_n + 1:
        return None
    historical = returns[-history_n-1:-1]
    sd = statistics.pstdev(historical) if len(historical) >= 2 else 0.0
    if sd <= 1e-12:
        return None
    return (returns[-1] - statistics.mean(historical)) / sd



def _ema_series(values: list[float], period: int) -> list[float | None]:
    """EMA with an SMA seed; None marks the warm-up window."""
    result: list[float | None] = [None] * len(values)
    if period < 1 or len(values) < period or not all(math.isfinite(v) for v in values):
        return result
    result[period - 1] = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)
    for index in range(period, len(values)):
        previous = result[index - 1]
        if previous is not None:
            result[index] = previous + alpha * (values[index] - previous)
    return result


def _wilder_series(values: list[float], period: int, start_index: int = 0) -> list[float | None]:
    """Wilder smoothing, used by RSI, ATR and ADX/DMI."""
    result: list[float | None] = [None] * len(values)
    if period < 1 or start_index < 0 or len(values) - start_index < period:
        return result
    seed_index = start_index + period - 1
    sample = values[start_index:seed_index + 1]
    if not all(math.isfinite(value) for value in sample):
        return result
    result[seed_index] = sum(sample) / period
    for index in range(seed_index + 1, len(values)):
        previous = result[index - 1]
        value = values[index]
        if previous is not None and math.isfinite(value):
            result[index] = (previous * (period - 1) + value) / period
    return result


def _rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder RSI, constrained to 0..100 and using only closed input bars."""
    result: list[float | None] = [None] * len(closes)
    if period < 2 or len(closes) <= period or not all(math.isfinite(v) for v in closes):
        return result
    changes = [0.0] + [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[1:period + 1]) / period
    average_loss = sum(losses[1:period + 1]) / period

    def value_from_averages(gain: float, loss: float) -> float:
        if gain <= 0 and loss <= 0:
            return 50.0
        if loss <= 0:
            return 100.0
        if gain <= 0:
            return 0.0
        relative_strength = gain / loss
        return 100.0 - (100.0 / (1.0 + relative_strength))

    result[period] = value_from_averages(average_gain, average_loss)
    for index in range(period + 1, len(closes)):
        average_gain = (average_gain * (period - 1) + gains[index]) / period
        average_loss = (average_loss * (period - 1) + losses[index]) / period
        result[index] = value_from_averages(average_gain, average_loss)
    return result


def _indicator_snapshot(bars: list[dict[str, Any]], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Transparent indicator readings for display; these do not form a hidden score."""
    cfg = settings or {}
    closes = [float(bar["c"]) for bar in bars]
    ema_fast_period = max(2, int(cfg.get("ema_fast_period", 12)))
    ema_slow_period = max(ema_fast_period + 1, int(cfg.get("ema_slow_period", 25)))
    macd_fast_period = max(2, int(cfg.get("macd_fast_period", 12)))
    macd_slow_period = max(macd_fast_period + 1, int(cfg.get("macd_slow_period", 26)))
    macd_signal_period = max(2, int(cfg.get("macd_signal_period", 9)))
    rsi_period = max(2, int(cfg.get("rsi_period", 14)))
    atr_period = max(2, int(cfg.get("atr_period", 14)))
    dmi_period = max(2, int(cfg.get("adx_period", 14)))

    ema_fast_series = _ema_series(closes, ema_fast_period)
    ema_slow_series = _ema_series(closes, ema_slow_period)
    ema_fast = ema_fast_series[-1] if ema_fast_series else None
    ema_slow = ema_slow_series[-1] if ema_slow_series else None
    ema_fast_prev = ema_fast_series[-2] if len(ema_fast_series) > 1 else None
    ema_slow_prev = ema_slow_series[-2] if len(ema_slow_series) > 1 else None
    latest_close = closes[-1] if closes else None
    ema_bullish = (ema_fast > ema_slow) if ema_fast is not None and ema_slow is not None else None
    ema_fast_slope_up = (
        ema_fast > ema_fast_prev
        if ema_fast is not None and ema_fast_prev is not None else None
    )
    ema_slow_slope_up = (
        ema_slow > ema_slow_prev
        if ema_slow is not None and ema_slow_prev is not None else None
    )
    price_above_ema_fast = (
        latest_close > ema_fast
        if latest_close is not None and ema_fast is not None else None
    )
    price_above_ema_slow = (
        latest_close > ema_slow
        if latest_close is not None and ema_slow is not None else None
    )
    ema_confirmation_inputs = (
        ema_bullish, ema_fast_slope_up, ema_slow_slope_up,
        price_above_ema_fast, price_above_ema_slow,
    )
    ema_confirmed_bullish = (
        all(value is True for value in ema_confirmation_inputs)
        if all(value is not None for value in ema_confirmation_inputs) else None
    )
    ema_cross_up = (
        ema_fast > ema_slow and ema_fast_prev <= ema_slow_prev
        if all(value is not None for value in (ema_fast, ema_slow, ema_fast_prev, ema_slow_prev))
        else None
    )

    macd_fast = _ema_series(closes, macd_fast_period)
    macd_slow = _ema_series(closes, macd_slow_period)
    macd_values = [
        fast - slow for fast, slow in zip(macd_fast, macd_slow)
        if fast is not None and slow is not None
    ]
    macd_signals = _ema_series(macd_values, macd_signal_period)
    macd_line = macd_values[-1] if macd_values else None
    macd_signal = macd_signals[-1] if macd_signals else None
    macd_histogram = (
        macd_line - macd_signal
        if macd_line is not None and macd_signal is not None else None
    )
    previous_histogram = (
        macd_values[-2] - macd_signals[-2]
        if len(macd_values) > 1 and len(macd_signals) > 1
        and macd_signals[-2] is not None else None
    )
    macd_histogram_rising = (
        macd_histogram > previous_histogram
        if macd_histogram is not None and previous_histogram is not None else None
    )

    rsi_values = _rsi_series(closes, rsi_period)
    rsi = rsi_values[-1] if rsi_values else None
    rsi_zone = (
        "GÜÇLÜ İVME (RSI ≥ 55)" if rsi is not None and rsi >= 55
        else "ZAYIF İVME (RSI ≤ 45)" if rsi is not None and rsi <= 45
        else "NÖTR" if rsi is not None else None
    )

    ranges = true_ranges(bars)
    atr_values = _wilder_series(ranges, atr_period, start_index=1)
    atr = atr_values[-1] if atr_values else None

    plus_dm = [0.0] * len(bars)
    minus_dm = [0.0] * len(bars)
    for index in range(1, len(bars)):
        upward = float(bars[index]["h"]) - float(bars[index - 1]["h"])
        downward = float(bars[index - 1]["l"]) - float(bars[index]["l"])
        plus_dm[index] = upward if upward > downward and upward > 0 else 0.0
        minus_dm[index] = downward if downward > upward and downward > 0 else 0.0
    smoothed_tr = _wilder_series(ranges, dmi_period, start_index=1)
    smoothed_plus = _wilder_series(plus_dm, dmi_period, start_index=1)
    smoothed_minus = _wilder_series(minus_dm, dmi_period, start_index=1)
    dx_values: list[float] = []
    plus_di = minus_di = None
    for tr, plus, minus in zip(smoothed_tr, smoothed_plus, smoothed_minus):
        if tr is None or plus is None or minus is None or tr <= 0:
            continue
        current_plus = 100.0 * plus / tr
        current_minus = 100.0 * minus / tr
        plus_di, minus_di = current_plus, current_minus
        denominator = current_plus + current_minus
        dx_values.append(100.0 * abs(current_plus - current_minus) / denominator if denominator > 0 else 0.0)
    adx_values = _wilder_series(dx_values, dmi_period)
    adx = adx_values[-1] if adx_values else None
    if plus_di is None or minus_di is None:
        dmi_direction = None
    elif plus_di > minus_di:
        dmi_direction = "YUKARI (+DI > −DI)"
    elif minus_di > plus_di:
        dmi_direction = "AŞAĞI (−DI > +DI)"
    else:
        dmi_direction = "NÖTR (+DI = −DI)"

    return {
        "ema_fast_period": ema_fast_period,
        "ema_slow_period": ema_slow_period,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "ema_bullish": ema_bullish,
        "ema_fast_slope_up": ema_fast_slope_up,
        "ema_slow_slope_up": ema_slow_slope_up,
        "price_above_ema_fast": price_above_ema_fast,
        "price_above_ema_slow": price_above_ema_slow,
        "ema_confirmed_bullish": ema_confirmed_bullish,
        "ema_cross_up": ema_cross_up,
        "macd_fast_period": macd_fast_period,
        "macd_slow_period": macd_slow_period,
        "macd_signal_period": macd_signal_period,
        "macd_line": macd_line,
        "macd_signal": macd_signal,
        "macd_histogram": macd_histogram,
        "macd_histogram_rising": macd_histogram_rising,
        "rsi_period": rsi_period,
        "rsi_14": rsi,
        "rsi_zone": rsi_zone,
        "atr_period": atr_period,
        "atr_14": atr,
        "adx_period": dmi_period,
        "plus_di_14": plus_di,
        "minus_di_14": minus_di,
        "adx_14": adx,
        "dmi_direction": dmi_direction,
    }



def _confirmed_pivot_points(
    bars: list[dict[str, Any]],
    timeframe: str,
    *,
    left: int = 2,
    right: int = 2,
) -> list[dict[str, Any]]:
    """Return only closed-candle pivots with two (by default) confirmed bars on each side."""
    if left < 1 or right < 1:
        return []
    closed = valid_bars(bars)
    if len(closed) < left + right + 1:
        return []
    if timeframe not in {*TIMEFRAME_MS.keys(), "1M"}:
        return []
    # Work only inside the newest contiguous aligned segment. Older gaps may exist
    # outside the analysis window, but a pivot must never straddle any gap.
    segment_start = len(closed) - 1
    if not _timeframe_start_is_aligned(timeframe, int(closed[segment_start]["t"])):
        return []
    for cursor in range(len(closed) - 1, 0, -1):
        previous = closed[cursor - 1]
        current = closed[cursor]
        if (
            not _timeframe_start_is_aligned(timeframe, int(previous["t"]))
            or timeframe_bar_end_ms(timeframe, int(previous["t"])) != int(current["t"])
        ):
            break
        segment_start = cursor - 1
    if len(closed) - segment_start < left + right + 1:
        return []

    pivots: list[dict[str, Any]] = []
    for index in range(segment_start + left, len(closed) - right):
        window = closed[index - left:index + right + 1]
        bar = closed[index]
        high = float(bar["h"])
        low = float(bar["l"])
        other_highs = [
            float(item["h"]) for pos, item in enumerate(window)
            if pos != left
        ]
        other_lows = [
            float(item["l"]) for pos, item in enumerate(window)
            if pos != left
        ]
        if all(high > value for value in other_highs):
            pivots.append({
                "kind": "high",
                "index": index,
                "timestamp_ms": int(bar["t"]),
                "price": high,
            })
        if all(low < value for value in other_lows):
            pivots.append({
                "kind": "low",
                "index": index,
                "timestamp_ms": int(bar["t"]),
                "price": low,
            })
    return sorted(pivots, key=lambda row: (row["index"], row["kind"]))


def _support_resistance_zones(
    bars: list[dict[str, Any]],
    timeframe: str,
    atr: float | None,
    pivots: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Group confirmed pivot prices into ATR-bounded zones; count only spaced reactions."""
    atr_value = _positive_finite(atr)
    if atr_value is None:
        return []
    confirmed = (
        _confirmed_pivot_points(bars, timeframe)
        if pivots is None else list(pivots)
    )
    zones: list[dict[str, Any]] = []
    for kind in ("high", "low"):
        typed = [
            point for point in confirmed
            if isinstance(point, dict)
            and point.get("kind") == kind
            and _positive_finite(point.get("price")) is not None
            and isinstance(point.get("index"), int)
            and isinstance(point.get("timestamp_ms"), int)
        ]
        typed.sort(key=lambda point: float(point["price"]))
        clusters: list[list[dict[str, Any]]] = []
        for point in typed:
            price = float(point["price"])
            if clusters:
                cluster_prices = [float(item["price"]) for item in clusters[-1]]
                center = sum(cluster_prices) / len(cluster_prices)
                if abs(price - center) <= 0.5 * atr_value:
                    clusters[-1].append(point)
                    continue
            clusters.append([point])

        for cluster in clusters:
            by_index: dict[int, dict[str, Any]] = {}
            for point in sorted(cluster, key=lambda item: int(item["index"])):
                index = int(point["index"])
                if by_index and index - max(by_index) < 3:
                    continue
                by_index[index] = point
            independent = list(by_index.values())
            prices = [float(point["price"]) for point in cluster]
            zone = {
                "kind": "resistance" if kind == "high" else "support",
                "center": round(sum(prices) / len(prices), 12),
                "lower": round(min(prices), 12),
                "upper": round(max(prices), 12),
                "touch_count": len(independent),
                "strong": len(independent) >= 2,
                "first_touch_ms": min(int(item["timestamp_ms"]) for item in cluster),
                "last_touch_ms": max(int(item["timestamp_ms"]) for item in cluster),
                "pivot_count": len(cluster),
                "timeframe": timeframe,
                "merge_tolerance": round(0.5 * atr_value, 12),
            }
            zones.append(zone)
    return sorted(zones, key=lambda row: (row["kind"], row["center"]))


def _linear_slope(points: list[dict[str, Any]]) -> float | None:
    """Least-squares price-per-bar slope for confirmed pivot points."""
    if len(points) < 2:
        return None
    xs = [float(point["index"]) for point in points]
    ys = [float(point["price"]) for point in points]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator <= 0:
        return None
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator
    return slope if math.isfinite(slope) else None


def _confirmed_channel(
    bars: list[dict[str, Any]],
    timeframe: str,
    atr: float | None,
    pivots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Describe a channel only when two confirmed pivot highs and lows support it."""
    atr_value = _positive_finite(atr)
    closed = valid_bars(bars)
    empty = {"status": "YETERLİ TEYİTLİ PİVOT YOK", "available": False}
    if atr_value is None or len(closed) < 5:
        return empty
    confirmed = (
        _confirmed_pivot_points(closed, timeframe)
        if pivots is None else list(pivots)
    )
    highs = [point for point in confirmed if point.get("kind") == "high"]
    lows = [point for point in confirmed if point.get("kind") == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return empty
    upper_slope = _linear_slope(highs)
    lower_slope = _linear_slope(lows)
    if upper_slope is None or lower_slope is None:
        return empty
    span_start = min(
        int(point["index"]) for point in (highs + lows)
        if isinstance(point.get("index"), int)
    )
    span_end = max(int(point["index"]) for point in (highs + lows))
    span = max(1, span_end - span_start)
    divergence = abs(upper_slope - lower_slope) * span
    if divergence > 0.5 * atr_value:
        return {
            "status": "PARALELLİK TEYİDİ YOK",
            "available": False,
            "upper_slope_per_bar": round(upper_slope, 12),
            "lower_slope_per_bar": round(lower_slope, 12),
            "slope_divergence_atr": round(divergence / atr_value, 6),
        }
    upper_intercept = sum(
        float(point["price"]) - upper_slope * int(point["index"])
        for point in highs
    ) / len(highs)
    lower_intercept = sum(
        float(point["price"]) - lower_slope * int(point["index"])
        for point in lows
    ) / len(lows)
    current_index = len(closed) - 1
    upper_now = upper_intercept + upper_slope * current_index
    lower_now = lower_intercept + lower_slope * current_index
    last_close = float(closed[-1]["c"])
    if not all(math.isfinite(value) for value in (upper_now, lower_now, last_close)):
        return empty
    if upper_now <= lower_now:
        return {"status": "KANAL SINIRLARI GEÇERSİZ", "available": False}
    position = (last_close - lower_now) / (upper_now - lower_now)
    direction = (
        "YÜKSELEN" if upper_slope > 0 and lower_slope > 0
        else "ALÇALAN" if upper_slope < 0 and lower_slope < 0
        else "YATAY"
    )
    return {
        "status": "TEYİTLİ KANAL",
        "available": True,
        "direction": direction,
        "upper_now": round(upper_now, 12),
        "lower_now": round(lower_now, 12),
        "upper_slope_per_bar": round(upper_slope, 12),
        "lower_slope_per_bar": round(lower_slope, 12),
        "position_0_to_1": round(position, 6),
        "pivot_high_count": len(highs),
        "pivot_low_count": len(lows),
        "slope_divergence_atr": round(divergence / atr_value, 6),
        "timeframe": timeframe,
    }


def _fibonacci_swing(
    bars: list[dict[str, Any]],
    timeframe: str,
    pivots: list[dict[str, Any]] | None = None,
    indicator_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate retracements/extensions from the last confirmed, directionally clear swing."""
    if timeframe not in {"4h", "1d", "1w", "1M"}:
        return {"status": "BU ZAMAN DİLİMİNDE KULLANILMIYOR", "available": False}
    closed = valid_bars(bars)
    confirmed = _confirmed_pivot_points(closed, timeframe) if pivots is None else list(pivots)
    snapshot = indicator_snapshot or {}
    ema_fast = _positive_finite(snapshot.get("ema_fast"))
    ema_slow = _positive_finite(snapshot.get("ema_slow"))
    latest_close = _positive_finite(closed[-1].get("c")) if closed else None
    if ema_fast is None or ema_slow is None or latest_close is None or ema_fast == ema_slow:
        return {"status": "YÖN BELİRSİZ", "available": False}
    direction = "up" if ema_fast > ema_slow and latest_close >= ema_slow else (
        "down" if ema_fast < ema_slow and latest_close <= ema_slow else None
    )
    if direction is None:
        return {"status": "SALINIM YÖNÜ TEYİTLİ DEĞİL", "available": False}
    typed_highs = [point for point in confirmed if point.get("kind") == "high"]
    typed_lows = [point for point in confirmed if point.get("kind") == "low"]
    if direction == "up":
        highs = sorted(
            (point for point in typed_highs if 0 <= int(point.get("index", -1)) < len(closed)),
            key=lambda point: int(point["index"]),
        )
        selected_high = next((
            point for point in reversed(highs)
            if any(
                low.get("kind") == "low" and 0 <= int(low.get("index", -1)) < int(point["index"])
                for low in typed_lows
            )
        ), None)
        if selected_high is None:
            return {"status": "TEYİTLİ YÜKSELİŞ SALINIMI YOK", "available": False}
        preceding_lows = [
            point for point in typed_lows
            if 0 <= int(point.get("index", -1)) < int(selected_high["index"])
        ]
        selected_low = max(preceding_lows, key=lambda point: int(point["index"]))
        low, high = float(selected_low["price"]), float(selected_high["price"])
        swing_low_index = int(selected_low["index"])
        if any(
            float(bar["c"]) < low
            for bar in closed[swing_low_index + 1:]
        ):
            return {
                "status": "YÜKSELİŞ SALINIMI SONRADAN KIRILDI",
                "available": False,
                "direction": "up",
                "swing_low": low,
                "swing_high": high,
                "timeframe": timeframe,
            }
    else:
        lows = sorted(
            (point for point in typed_lows if 0 <= int(point.get("index", -1)) < len(closed)),
            key=lambda point: int(point["index"]),
        )
        selected_low = next((
            point for point in reversed(lows)
            if any(
                high_point.get("kind") == "high"
                and 0 <= int(high_point.get("index", -1)) < int(point["index"])
                for high_point in typed_highs
            )
        ), None)
        if selected_low is None:
            return {"status": "TEYİTLİ DÜŞÜŞ SALINIMI YOK", "available": False}
        preceding_highs = [
            point for point in typed_highs
            if 0 <= int(point.get("index", -1)) < int(selected_low["index"])
        ]
        selected_high = max(preceding_highs, key=lambda point: int(point["index"]))
        high, low = float(selected_high["price"]), float(selected_low["price"])
        swing_high_index = int(selected_high["index"])
        if any(
            float(bar["c"]) > high
            for bar in closed[swing_high_index + 1:]
        ):
            return {
                "status": "DÜŞÜŞ SALINIMI SONRADAN KIRILDI",
                "available": False,
                "direction": "down",
                "swing_low": low,
                "swing_high": high,
                "timeframe": timeframe,
            }
    swing_range = high - low
    if not math.isfinite(swing_range) or swing_range <= 0:
        return {"status": "GEÇERSİZ SALINIM", "available": False}
    retracements = (0.382, 0.5, 0.618, 0.786)
    extensions = (1.272, 1.618)
    if direction == "up":
        retrace_levels = {f"retracement_{ratio:g}".replace(".", "_"): high - swing_range * ratio
                          for ratio in retracements}
        extension_levels = {f"extension_{ratio:g}".replace(".", "_"): low + swing_range * ratio
                            for ratio in extensions}
    else:
        retrace_levels = {f"retracement_{ratio:g}".replace(".", "_"): low + swing_range * ratio
                          for ratio in retracements}
        extension_levels = {f"extension_{ratio:g}".replace(".", "_"): high - swing_range * ratio
                            for ratio in extensions}
    return {
        "status": "TEYİTLİ SALINIM",
        "available": True,
        "direction": direction,
        "swing_low": round(low, 12),
        "swing_high": round(high, 12),
        "swing_range": round(swing_range, 12),
        "low_timestamp_ms": int(selected_low["timestamp_ms"]),
        "high_timestamp_ms": int(selected_high["timestamp_ms"]),
        "retracements": {key: round(value, 12) for key, value in retrace_levels.items()},
        "extensions": {key: round(value, 12) for key, value in extension_levels.items()},
        "timeframe": timeframe,
    }

def assess_timeframe(bars: list[dict[str, Any]], timeframe: str,
                     settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Tek zaman dilimini A/B/C aşaması ve bağımsız kanıt gruplarıyla inceler.

    B aşaması: aynı zaman diliminde kapanmış mumda anlamlı fiyat yapısı VE
    geçmiş hacim dağılımının üst çeyreğinde piyasa katılımı. Hacim ve işlem sayısı
    iki ayrı kanıt gibi sayılmaz. C, teyitli kırılımın sonraki kapanışlarda korunmasıdır.
    """
    cfg = settings or {}
    lookback = int(cfg.get("volume_history_bars", 40))
    price_lookback = int(cfg.get("resistance_lookback_bars", 20))
    min_history = max(lookback + 2, price_lookback + 3)
    closed = valid_bars(bars)
    analysis_window = closed[-min_history:]
    history_contiguous = bool(
        timeframe in {*TIMEFRAME_MS.keys(), "1M"}
        and len(analysis_window) == min_history
        and all(_timeframe_start_is_aligned(timeframe, int(bar["t"])) for bar in analysis_window)
        and all(
            timeframe_bar_end_ms(timeframe, int(analysis_window[index - 1]["t"]))
            == int(analysis_window[index]["t"])
            for index in range(1, len(analysis_window))
        )
    )
    enough_count = len(closed) >= min_history
    data_sufficient = enough_count and history_contiguous
    result: dict[str, Any] = {
        "timeframe": timeframe, "phase": None, "state": "VERİ EKSİK",
        "data_sufficient": data_sufficient,
        "history_contiguous": history_contiguous,
        "closed_bars": len(closed), "required_closed_bars": min_history,
        "findings": [], "missing_checks": [],
        "evidence_groups": [], "metrics": {},
    }
    if not enough_count:
        result["missing_checks"].append(
            f"{timeframe}: yeterli kapanmış mum yok ({len(closed)}/{min_history})")
        return result
    if not history_contiguous:
        result["state"] = "VERİ EKSİK — ANALİZ MUM GEÇMİŞİ KESİNTİLİ"
        result["missing_checks"].append(
            f"{timeframe}: son {min_history} mumluk analiz penceresinde zaman boşluğu veya geçersiz zaman dilimi var; "
            "teknik koşullar güvenilir biçimde hesaplanmadı."
        )
        return result

    last = closed[-1]
    prev = closed[:-1]
    high_hist = [float(b["h"]) for b in prev[-price_lookback:]]
    resistance = max(high_hist)
    support = min(float(b["l"]) for b in prev[-price_lookback:])
    typical_ranges = true_ranges(prev[-max(15, lookback):])
    typical_range = median(typical_ranges[-14:]) if typical_ranges else None
    indicator_snapshot = _indicator_snapshot(closed, cfg)
    atr14 = indicator_snapshot.get("atr_14")
    # Quote volume (q) and base volume (v) are different units. Use one source
    # consistently across the reference and continuation windows; mixed/incomplete
    # schemas must not fabricate a percentile by comparing unlike quantities.
    volume_basis_window = closed[-lookback - 3:]
    q_presence = ["q" in bar for bar in volume_basis_window]
    if q_presence and all(q_presence):
        proposed_volume_source = "q"
    elif q_presence and not any(q_presence):
        proposed_volume_source = "v"
    else:
        proposed_volume_source = None

    def read_volume(bar: dict[str, Any]) -> float | None:
        if proposed_volume_source is None:
            return None
        raw = bar.get(proposed_volume_source)
        if isinstance(raw, bool) or raw is None:
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        return value if math.isfinite(value) and value >= 0 else None

    volume_source_complete = (
        proposed_volume_source is not None
        and all(read_volume(bar) is not None for bar in volume_basis_window)
    )
    volume_measurement_source = proposed_volume_source if volume_source_complete else None
    qvolumes = (
        [float(read_volume(bar)) for bar in prev[-lookback:]]
        if volume_source_complete else []
    )
    volume_history_complete = volume_source_complete and len(qvolumes) == lookback
    volume_q60 = percentile(qvolumes, 0.60) if volume_history_complete else None
    volume_q75 = percentile(qvolumes, 0.75) if volume_history_complete else None
    current_volume = read_volume(last) if volume_source_complete else None
    current_volume_valid = current_volume is not None

    persistence_raw = [read_volume(bar) for bar in closed[-lookback - 3:-3]]
    persistence_history_complete = (
        volume_source_complete
        and len(persistence_raw) == lookback
        and all(value is not None for value in persistence_raw)
    )
    persistence_history = (
        [float(value) for value in persistence_raw]
        if persistence_history_complete else []
    )
    persistence_q60 = (
        percentile(persistence_history, 0.60)
        if persistence_history_complete else None
    )
    recent_volume_window = closed[-3:]
    recent_volume_values = [read_volume(bar) for bar in recent_volume_window]
    recent_volume_window_complete = (
        volume_source_complete
        and len(recent_volume_values) == 3
        and all(value is not None for value in recent_volume_values)
    )
    volume_persistence_count = (
        sum(
            1 for value in recent_volume_values
            if value is not None and value > 0 and value > persistence_q60
        )
        if persistence_q60 is not None and recent_volume_window_complete else 0
    )
    if not volume_history_complete:
        reason = (
            "q ve v hacim alanları eksik/karışık ya da sayısal olarak geçersiz."
            if not volume_source_complete
            else f"{lookback} ölçülmüş geçmiş hacim örneği gerekli ({len(qvolumes)}/{lookback})."
        )
        result["missing_checks"].append(
            f"{timeframe}: {reason} q60/q75 katılım eşikleri doğrulanmadı."
        )
    if not persistence_history_complete or not recent_volume_window_complete:
        result["missing_checks"].append(
            f"{timeframe}: devamlı hacim ölçümleri aynı geçerli birimde ve tam pencerede mevcut değil."
        )
    # Equal-to-percentile volume is not unusual, especially when historical values
    # contain many ties; require a strict exceedance for both participation thresholds.
    volume_unusual = bool(
        current_volume_valid and volume_q75 is not None
        and current_volume > 0 and current_volume > volume_q75
    )
    volume_early = bool(
        current_volume_valid and volume_q60 is not None
        and current_volume > 0 and current_volume > volume_q60
    )
    positive_z = _positive_return_z(closed, lookback)
    change_1 = pct_change(closed, 1)
    change_3 = pct_change(closed, 3)

    # Direnç referansı sadece önceki mumlardan hesaplanır; son mum referansa sızmaz.
    breakout_long = float(last["c"]) > resistance
    short_closes = [float(b["c"]) for b in prev[-5:]]
    short_high = max(short_closes) if short_closes else resistance
    rising_local_structure = (
        len(prev) >= 3 and float(last["c"]) > short_high
        and float(last["l"]) >= min(float(b["l"]) for b in prev[-3:])
    )
    directional_structure = breakout_long or rising_local_structure

    lows = [float(b["l"]) for b in closed[-3:]]
    rising_lows = len(lows) == 3 and lows[0] < lows[1] < lows[2]
    recent_ten = closed[-10:]
    compression = False
    if typical_range and typical_range > 0 and len(recent_ten) == 10:
        full_range = max(float(b["h"]) for b in recent_ten) - min(float(b["l"]) for b in recent_ten)
        compression_ratio = full_range / (typical_range * len(recent_ten))
        compression = compression_ratio <= float(cfg.get("compression_range_ratio", 0.55))
    else:
        compression_ratio = None
    distance_typical_range = ((resistance - float(last["c"])) / typical_range
                               if typical_range and typical_range > 0 else None)
    distance_atr = ((resistance - float(last["c"])) / atr14
                    if atr14 is not None and atr14 > 0 else None)
    near_resistance = bool(
        distance_atr is not None
        and 0 <= distance_atr <= float(cfg.get("near_resistance_atr", 1.5))
    )

    # C için geçmişteki son kırılım bulunur; en az bir sonraki kapanmış mum seviyeyle
    # ilişkisini korumalıdır. Gerçekleşmemiş mumlar bu doğrulamaya katılmaz.
    continuity = False
    continuity_volume_confirmed = False
    retest_hold = False
    continuity_level = None
    search_start = max(price_lookback, len(closed) - 5)
    for idx in range(search_start, len(closed) - 1):
        if idx < price_lookback:
            continue
        reference = max(float(b["h"]) for b in closed[idx-price_lookback:idx])
        breakout_bar = closed[idx]
        if float(breakout_bar["c"]) <= reference:
            continue
        historical_volumes = [float(b.get("q", b.get("v", 0)) or 0)
                              for b in closed[max(0, idx-lookback):idx]
                              if not b.get("synthetic", False)]
        breakout_q75 = percentile(historical_volumes, 0.75)
        breakout_volume = float(breakout_bar.get("q", breakout_bar.get("v", 0)) or 0)
        if breakout_q75 is None or breakout_volume <= 0 or breakout_volume <= breakout_q75:
            continue
        later = closed[idx + 1:]
        if not later:
            continue
        last_after = later[-1]
        if float(last_after["c"]) >= reference:
            continuity = True
            continuity_volume_confirmed = True
            continuity_level = reference
            if typical_range and float(last_after["l"]) <= reference + typical_range * 0.5:
                retest_hold = True
            break

    # A: hazırlık yapısı + en az bir yardımcı davranış. Bu, B doğrulaması değildir.
    price_prep = compression or rising_lows or near_resistance
    supportive_behavior = volume_early or (positive_z is not None and positive_z >= 0.75)
    phase = None
    state = "ADAY DEĞİL"
    findings: list[str] = []
    groups: list[str] = []
    if directional_structure:
        findings.append("Kapanmış mumda yönlü fiyat yapısı oluştu")
        groups.append("FİYAT YAPISI")
    elif price_prep:
        groups.append("FİYAT YAPISI")
    if volume_unusual:
        findings.append("Hacim, aynı zaman dilimindeki geçmiş dağılımın üst çeyreğinde")
        groups.append("PİYASA KATILIMI")
    elif volume_early:
        findings.append("Hacim geçmiş dağılımın üst %40'lık bölümüne girdi; henüz güçlü katılım teyidi değil")
    if compression:
        findings.append("Fiyat aralığı, coinin tipik mum aralığına göre daralmış")
    if rising_lows:
        findings.append("Son üç kapanmış mumda dipler yükseldi")
    if near_resistance:
        findings.append(f"Fiyat önceki direnç seviyesine ATR cinsinden yaklaşıyor ({distance_atr:.2f} ATR)")
    if positive_z is not None and positive_z >= 0.75:
        findings.append("Pozitif fiyat değişimi kendi geçmiş değişkenliğine göre dikkat çekici")
    if breakout_long:
        findings.append(f"Kapanmış mum önceki {price_lookback} mumun en yüksek seviyesini aştı")
    if continuity:
        findings.append("Önceki kırılım seviyesi sonraki kapanmış mumda korundu")
        if continuity_volume_confirmed and "PİYASA KATILIMI" not in groups:
            groups.append("PİYASA KATILIMI (KIRILIM MUMU)")
        if retest_hold:
            findings.append("Geri testte kırılım seviyesi korundu")

    # İlk doğrulama aynı zaman dilimindeki kapanmış mumda iki ana koşulu birlikte ister.
    # Hacim eşiği, aynı coinin ve aynı zaman diliminin kendi geçmişinden türetilir.
    if continuity and continuity_volume_confirmed:
        phase, state = "C", "DEVAMLILIK DOĞRULANIYOR"
    elif directional_structure and volume_unusual:
        phase, state = "B", "İLK DOĞRULAMA"
    elif price_prep and supportive_behavior:
        phase, state = "A", "ERKEN HAZIRLIK"
        if not volume_unusual:
            findings.append("Erken hazırlık; iki ana doğrulama henüz birlikte oluşmadı")
    elif price_prep:
        phase, state = "A", "ERKEN HAZIRLIK — KATILIM HENÜZ DESTEKLEMEDİ"
        findings.append("İzlemeye değer bir fiyat yapısı var; hacim/aktivite henüz destekleyici düzeye gelmedi")
    elif directional_structure and not volume_unusual:
        # Fiyat kırılımı tek başına B sayılmaz; katılım eksiği açıkça görünür.
        phase, state = "A", "KATILIM DOĞRULAMASI BEKLENİYOR"
        findings.append("Fiyat yapısı ilerledi ancak hacim koşulu kapanmış mumda doğrulanmadı")
        if "FİYAT YAPISI" not in groups:
            groups.append("FİYAT YAPISI")

    metrics = {
        "candle_start_ms": int(last["t"]),
        "close_time_ms": timeframe_bar_end_ms(timeframe, int(last["t"])) or 0,
        "close": float(last["c"]),
        "one_bar_change_pct": change_1, "three_bar_change_pct": change_3,
        "positive_return_z": positive_z, "current_volume": current_volume,
        "volume_q60_history": volume_q60, "volume_q75_history": volume_q75,
        "volume_measurement_source": volume_measurement_source,
        "volume_history_complete": volume_history_complete,
        "volume_history_sample_count": len(qvolumes),
        "current_volume_valid": current_volume_valid,
        "volume_persistence_history_complete": persistence_history_complete,
        "recent_volume_window_complete": recent_volume_window_complete,
        "volume_early": volume_early, "volume_unusual": volume_unusual,
        "volume_persistence_count": volume_persistence_count,
        "directional_structure": directional_structure,
        "breakout_level": continuity_level if continuity else resistance,
        "previous_resistance": resistance, "previous_support": support,
        "typical_candle_range": typical_range,
        "distance_to_resistance_typical_range": distance_typical_range,
        "distance_to_resistance_atr": distance_atr,
        "compression_ratio": compression_ratio, "compression": compression,
        "rising_lows": rising_lows, "near_resistance": near_resistance,
        "continuity": continuity, "continuity_volume_confirmed": continuity_volume_confirmed,
        "retest_hold": retest_hold,
    }
    structure_pivots = _confirmed_pivot_points(closed, timeframe)
    support_resistance_zones = _support_resistance_zones(
        closed, timeframe, atr14, structure_pivots
    )
    confirmed_channel = _confirmed_channel(
        closed, timeframe, atr14, structure_pivots
    )
    fibonacci = _fibonacci_swing(
        closed, timeframe, structure_pivots, indicator_snapshot
    )
    metrics.update(indicator_snapshot)
    metrics.update({
        "confirmed_pivot_count": len(structure_pivots),
        "support_resistance_zones": support_resistance_zones,
        "confirmed_channel": confirmed_channel,
        "fibonacci": fibonacci,
    })
    result.update({"phase": phase, "state": state, "findings": findings,
                   "evidence_groups": groups, "metrics": metrics,
                   "missing_checks": result["missing_checks"]})
    return result



def _finite_numeric_metric(value: Any) -> float | None:
    """Accept real finite numeric metrics, never booleans or numeric-looking strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _positive_finite(value: Any) -> float | None:
    numeric = _finite_numeric_metric(value)
    return numeric if numeric is not None and numeric > 0 else None


def build_trade_plan(
    candidate: dict[str, Any],
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a conditional technical entry/stop/target plan; no order is sent."""
    cfg = settings or {}
    if candidate.get("data_freshness") != "CANLI AKIŞ GÜNCEL":
        return {
            "status": "VERİ ESKİ — PLAN YOK",
            "reason": "Sayısal plan için seçilen coinin bütün gerekli canlı zaman dilimleri güncel olmalıdır.",
        }
    # Alarm uygunluğu teknik plan üretiminden bağımsızdır: evrende kalan ve
    # güncel B/C kanıtı taşıyan parite için plan hesaplanabilir. Bu bayrak yalnızca
    # GÜÇLÜ FIRSAT/alarm kapısında kullanılmalıdır.
    phase = candidate.get("phase")
    if phase not in ("B", "C"):
        return {
            "status": "UYGUN DEĞİL",
            "reason": "Sayısal giriş planı için aynı zaman diliminde doğrulanmış B/C aşaması gerekir.",
        }
    timeframe = str(candidate.get("phase_timeframe") or "")
    assessments = candidate.get("timeframes")
    assessment = assessments.get(timeframe) if isinstance(assessments, dict) else None
    metrics = assessment.get("metrics") if isinstance(assessment, dict) else None
    metrics = metrics if isinstance(metrics, dict) else {}
    close = _positive_finite(metrics.get("close"))
    level = _positive_finite(metrics.get("breakout_level"))
    support = _positive_finite(metrics.get("previous_support"))
    atr = _positive_finite(metrics.get("atr_14"))
    current_price = _positive_finite(candidate.get("latest_price"))
    if any(value is None for value in (close, level, support, atr, current_price)):
        return {
            "status": "HESAPLANAMADI",
            "reason": "Kapanmış mum kapanışı, kırılım seviyesi, destek, ATR(14) veya güncel fiyat eksik/geçersiz.",
            "timeframe": timeframe,
        }
    if (phase == "B" and close <= level) or (phase == "C" and close < level):
        return {
            "status": "HESAPLANAMADI",
            "reason": (
                f"Seçilen {timeframe} zaman diliminin kapanmış mum kapanışı kırılım seviyesini doğrulamıyor; "
                "başka bir zaman diliminin verisi bu kontrolün yerine geçmez."
            ),
            "timeframe": timeframe,
            "breakout_level": level,
            "signal_close": close,
            "current_price": current_price,
        }

    entry_low = level
    entry_high = level + 0.25 * atr
    entry_reference = (entry_low + entry_high) / 2.0
    stop = min(support, level - 0.5 * atr)
    risk = entry_reference - stop
    if stop <= 0 or risk <= 0 or not all(
        math.isfinite(value) for value in (entry_low, entry_high, entry_reference, stop, risk)
    ):
        return {
            "status": "HESAPLANAMADI",
            "reason": "Teknik yapıdan geçerli pozitif stop ve risk aralığı üretilemedi.",
            "timeframe": timeframe,
        }

    # A technical target must remain ahead of both the full entry band and the latest observed market price.
    target_floor = max(entry_high, current_price)
    candidates_by_price: list[dict[str, Any]] = []
    timeframe_names = ("5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M")
    for tf in timeframe_names:
        row = assessments.get(tf) if isinstance(assessments, dict) else None
        tf_metrics = row.get("metrics") if isinstance(row, dict) else None
        if not isinstance(tf_metrics, dict):
            continue
        zones = tf_metrics.get("support_resistance_zones")
        if isinstance(zones, list):
            for zone in zones:
                if not isinstance(zone, dict) or zone.get("kind") != "resistance":
                    continue
                price = _positive_finite(zone.get("center"))
                # A target must be beyond the full entry zone, not merely above its midpoint.
                if price is None or price <= target_floor or zone.get("strong") is not True:
                    continue
                candidates_by_price.append({
                    "price": price,
                    "basis": "Teyitli direnç bölgesi",
                    "source_timeframe": tf,
                    "touch_count": zone.get("touch_count"),
                })
        if tf in ("1h", "4h", "1d", "1w", "1M"):
            channel = tf_metrics.get("confirmed_channel")
            channel_close = _positive_finite(tf_metrics.get("close"))
            channel_upper = (
                _positive_finite(channel.get("upper_now"))
                if isinstance(channel, dict) and channel.get("available") is True
                else None
            )
            channel_position = channel.get("position_0_to_1") if isinstance(channel, dict) else None
            channel_direction = channel.get("direction") if isinstance(channel, dict) else None
            if (
                channel_upper is not None
                and channel_upper > target_floor
                and channel_close is not None
                and channel_close < channel_upper
                and isinstance(channel_position, (int, float))
                and not isinstance(channel_position, bool)
                and 0.0 <= float(channel_position) < 1.0
                and channel_direction in {"YÜKSELEN", "YATAY"}
            ):
                candidates_by_price.append({
                    "price": channel_upper,
                    "basis": "Teyitli kanal üst sınırı",
                    "source_timeframe": tf,
                    "touch_count": None,
                })

        if tf not in ("4h", "1d", "1w", "1M"):
            continue
        fib = tf_metrics.get("fibonacci")
        if not isinstance(fib, dict) or fib.get("available") is not True or fib.get("direction") != "up":
            continue
        extensions = fib.get("extensions")
        if not isinstance(extensions, dict):
            continue
        for key, raw_price in extensions.items():
            price = _positive_finite(raw_price)
            if price is not None and price > target_floor:
                candidates_by_price.append({
                    "price": price,
                    "basis": f"Fibonacci uzatma {str(key).replace('extension_', '').replace('_', '.')}",
                    "source_timeframe": tf,
                    "touch_count": None,
                })

    candidates_by_price.sort(key=lambda item: item["price"])
    # Merge overlapping technical target areas using half the selected timeframe's ATR.
    target_clusters: list[list[dict[str, Any]]] = []
    merge_tolerance = 0.5 * atr
    for item in candidates_by_price:
        if (
            target_clusters
            and abs(item["price"] - sum(entry["price"] for entry in target_clusters[-1]) / len(target_clusters[-1]))
            <= merge_tolerance
        ):
            target_clusters[-1].append(item)
        else:
            target_clusters.append([item])

    target_levels = []
    for cluster in target_clusters:
        price = sum(item["price"] for item in cluster) / len(cluster)
        target_levels.append({
            "price": price,
            "basis": " + ".join(dict.fromkeys(item["basis"] for item in cluster)),
            "source_timeframes": list(dict.fromkeys(item["source_timeframe"] for item in cluster)),
            "touch_count": max(
                (int(item["touch_count"]) for item in cluster
                 if isinstance(item.get("touch_count"), int)),
                default=None,
            ),
        })
    target_levels = target_levels[:3]

    risk_pct = (risk / entry_reference) * 100.0
    r_targets = []
    for multiple in (1, 2, 3):
        target = entry_reference + risk * multiple
        r_targets.append({
            "name": f"{multiple}R karşılaştırması",
            "price": round(target, 10),
            "risk_multiple": multiple,
            "change_pct": round(((target / entry_reference) - 1.0) * 100.0, 4),
        })

    liquidity = candidate.get("liquidity_assessment")
    liquidity = liquidity if isinstance(liquidity, dict) else {}
    spread_pct = liquidity.get("spread_pct")
    commission_pct = cfg.get("commission_rate_per_side_pct")
    slippage_pct = cfg.get("slippage_pct_per_side")
    cost_inputs_valid = all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
        for value in (commission_pct, slippage_pct, spread_pct)
    )
    round_trip_cost_pct = None
    net_risk_reward = None
    net_targets = []
    if cost_inputs_valid:
        round_trip_cost_pct = (
            2.0 * float(commission_pct)
            + 2.0 * float(slippage_pct)
            + float(spread_pct)
        )
        cost_amount = entry_reference * round_trip_cost_pct / 100.0
        net_risk = risk + cost_amount
        for target in target_levels:
            gross_reward = target["price"] - entry_reference
            net_reward = gross_reward - cost_amount
            net_rr = net_reward / net_risk if net_risk > 0 else None
            net_targets.append({
                **target,
                "gross_reward_pct": round(gross_reward / entry_reference * 100.0, 4),
                "net_reward_pct": round(net_reward / entry_reference * 100.0, 4),
                "gross_risk_reward": round(gross_reward / risk, 4),
                "net_risk_reward": round(net_rr, 4) if net_rr is not None else None,
            })
        if net_targets:
            net_risk_reward = net_targets[0]["net_risk_reward"]

    if current_price < entry_low:
        # A live price below the entry/breakout zone means do not open a new position.
        # It is not, by itself, confirmation that the structural setup has failed.
        status = "FİYAT GİRİŞ BÖLGESİNİN ALTINDA — YENİ GİRİŞ BEKLE"
    elif current_price <= entry_high:
        status = "FİYAT GİRİŞ BÖLGESİNDE — KOŞULLU"
    else:
        status = "FİYAT GİRİŞ BÖLGESİNİN ÜZERİNDE — KOVALAMA YOK"
    technical_targets_available = bool(target_levels)
    costs_included = bool(cost_inputs_valid)
    costs_note = (
        "Komisyon, spread ve kayma girdileriyle gidiş-dönüş maliyeti hesaplandı."
        if costs_included else
        "Komisyon/kayma ayarı veya güncel spread eksik; masraf sonrası net risk/getiri doğrulanmadı."
    )
    return {
        "status": status,
        "timeframe": timeframe,
        "phase": phase,
        "current_price": round(current_price, 10),
        "signal_close": round(close, 10),
        "breakout_level": round(level, 10),
        "entry_zone_low": round(entry_low, 10),
        "entry_zone_high": round(entry_high, 10),
        "entry_reference": round(entry_reference, 10),
        "stop_loss": round(stop, 10),
        "risk_pct": round(risk_pct, 4),
        "stop_loss_pct": round(-risk_pct, 4),
        "targets": [
            {
                "name": f"Teknik hedef {index}",
                "price": round(item["price"], 10),
                "risk_multiple": round((item["price"] - entry_reference) / risk, 4),
                "change_pct": round((item["price"] / entry_reference - 1.0) * 100.0, 4),
                "risk_reward": round((item["price"] - entry_reference) / risk, 4),
                "basis": item["basis"],
                "source_timeframes": item["source_timeframes"],
                "touch_count": item["touch_count"],
                "gross_risk_reward": (
                    net_targets[index - 1].get("gross_risk_reward")
                    if index - 1 < len(net_targets) else round((item["price"] - entry_reference) / risk, 4)
                ),
                "net_risk_reward": (
                    net_targets[index - 1].get("net_risk_reward")
                    if index - 1 < len(net_targets) else None
                ),
            }
            for index, item in enumerate(target_levels, start=1)
        ],
        "technical_targets_available": technical_targets_available,
        "r_targets": r_targets,
        "target_basis": (
            "Ana hedefler kapanmış mumlarla doğrulanmış direnç bölgeleri ve 4h/1d/1w/1M Fibonacci uzatmalarından seçilir. "
            "1R/2R/3R yalnızca ikincil karşılaştırmadır."
        ),
        "costs_included": costs_included,
        "commission_rate_per_side_pct": commission_pct if costs_included else None,
        "slippage_pct_per_side": slippage_pct if costs_included else None,
        "spread_pct": spread_pct if costs_included else None,
        "round_trip_cost_pct": round(round_trip_cost_pct, 6) if round_trip_cost_pct is not None else None,
        "net_risk_reward": net_risk_reward,
        "costs_note": costs_note,
        "invalid_if": f"{stop:.10g} USDT altındaki zarar durdurma seviyesi görülürse senaryo geçersiz sayılır.",
        "note": "Giriş referansı bölge orta noktasıdır; hedefler teknik seviyelerdir. Otomatik emir gönderilmez.",
    }


def _closed_price_map(
    bars: list[dict[str, Any]] | None,
    timeframe: str,
) -> dict[int, float]:
    """Map UTC candle-close timestamps to closed prices, omitting malformed intervals."""
    interval = TIMEFRAME_MS.get(timeframe)
    if interval is None:
        return {}
    output: dict[int, float] = {}
    for bar in valid_bars(bars or []):
        start = int(bar["t"])
        if not _timeframe_start_is_aligned(timeframe, start):
            continue
        end = timeframe_bar_end_ms(timeframe, start)
        close = _positive_finite(bar.get("c"))
        if end is not None and close is not None:
            output[end] = close
    return output


def _closed_return_map(
    bars: list[dict[str, Any]] | None,
    timeframe: str,
) -> dict[int, float]:
    """Calculate closed-bar returns only across adjacent, contiguous candle intervals."""
    interval = TIMEFRAME_MS.get(timeframe)
    if interval is None:
        return {}
    closed = valid_bars(bars or [])
    output: dict[int, float] = {}
    for previous, current in zip(closed, closed[1:]):
        previous_start, current_start = int(previous["t"]), int(current["t"])
        if (
            not _timeframe_start_is_aligned(timeframe, previous_start)
            or not _timeframe_start_is_aligned(timeframe, current_start)
            or previous_start + interval != current_start
        ):
            continue
        previous_close = _positive_finite(previous.get("c"))
        current_close = _positive_finite(current.get("c"))
        current_end = timeframe_bar_end_ms(timeframe, current_start)
        if previous_close is None or current_close is None or current_end is None:
            continue
        output[current_end] = (current_close / previous_close - 1.0) * 100.0
    return output


def _synchronized_return_difference(
    own_bars: list[dict[str, Any]] | None,
    btc_bars: list[dict[str, Any]] | None,
    timeframe: str,
    lookback: int,
) -> float | None:
    """Coin minus BTC percentage return over synchronized, consecutive closed candles."""
    interval = TIMEFRAME_MS.get(timeframe)
    if interval is None or lookback < 1:
        return None
    own = _closed_price_map(own_bars, timeframe)
    btc = _closed_price_map(btc_bars, timeframe)
    if not own or not btc or max(own) != max(btc):
        return None
    common_times = sorted(set(own).intersection(btc))
    required = lookback + 1
    if len(common_times) < required:
        return None
    window = common_times[-required:]
    if any(right - left != interval for left, right in zip(window, window[1:])):
        return None
    own_start, own_end = own[window[0]], own[window[-1]]
    btc_start, btc_end = btc[window[0]], btc[window[-1]]
    if min(own_start, own_end, btc_start, btc_end) <= 0:
        return None
    own_return = (own_end / own_start - 1.0) * 100.0
    btc_return = (btc_end / btc_start - 1.0) * 100.0
    difference = own_return - btc_return
    return difference if math.isfinite(difference) else None


def _pearson_correlation(values_x: list[float], values_y: list[float]) -> float | None:
    if len(values_x) != len(values_y) or len(values_x) < 2:
        return None
    mean_x = sum(values_x) / len(values_x)
    mean_y = sum(values_y) / len(values_y)
    sum_xx = sum((value - mean_x) ** 2 for value in values_x)
    sum_yy = sum((value - mean_y) ** 2 for value in values_y)
    if sum_xx <= 1e-18 or sum_yy <= 1e-18:
        return None
    covariance = sum(
        (x - mean_x) * (y - mean_y) for x, y in zip(values_x, values_y)
    )
    value = covariance / math.sqrt(sum_xx * sum_yy)
    if not math.isfinite(value):
        return None
    return max(-1.0, min(1.0, value))


def _relative_strength_and_correlation(
    bars_by_interval: dict[str, list[dict[str, Any]]],
    btc_bars_by_interval: dict[str, list[dict[str, Any]]] | None,
) -> tuple[dict[str, float | None], dict[str, dict[str, Any]]]:
    """Keep relative return and Pearson correlation distinct; require matched closed bars."""
    relative: dict[str, float | None] = {"15m": None, "1h": None, "4h": None}
    correlation: dict[str, dict[str, Any]] = {
        "1h": {"value": None, "observations": 0, "minimum_required": 60},
        "4h": {"value": None, "observations": 0, "minimum_required": 34},
    }
    if not isinstance(btc_bars_by_interval, dict) or not btc_bars_by_interval:
        return relative, correlation

    for timeframe, lookback in (("15m", 16), ("1h", 24), ("4h", 6)):
        relative[timeframe] = _synchronized_return_difference(
            bars_by_interval.get(timeframe),
            btc_bars_by_interval.get(timeframe),
            timeframe,
            lookback,
        )

    for timeframe, max_observations, minimum in (("1h", 72, 60), ("4h", 42, 34)):
        own_returns = _closed_return_map(bars_by_interval.get(timeframe), timeframe)
        btc_returns = _closed_return_map(btc_bars_by_interval.get(timeframe), timeframe)
        if not own_returns or not btc_returns or max(own_returns) != max(btc_returns):
            continue
        shared_times = sorted(set(own_returns).intersection(btc_returns))
        # Count only the newest contiguous synchronized block, including when the
        # total matched observations are already below the minimum. Older samples
        # separated by a gap are not usable for the current correlation window.
        latest_block = [shared_times[-1]]
        interval = TIMEFRAME_MS[timeframe]
        for stamp in reversed(shared_times[:-1]):
            if latest_block[-1] - stamp != interval:
                break
            latest_block.append(stamp)
        latest_block.reverse()
        selected = latest_block[-max_observations:]
        correlation[timeframe]["observations"] = len(selected)
        if len(selected) < minimum:
            continue
        value = _pearson_correlation(
            [own_returns[stamp] for stamp in selected],
            [btc_returns[stamp] for stamp in selected],
        )
        correlation[timeframe]["value"] = round(value, 6) if value is not None else None
    return relative, correlation



def score_btc_market_context(
    bars_by_interval: dict[str, list[dict[str, Any]]] | None,
) -> dict[str, Any]:
    """Build BTC direction, confirmed key-level, channel and volatility context."""
    bars_by_interval = bars_by_interval if isinstance(bars_by_interval, dict) else {}
    context_by_tf: dict[str, dict[str, Any]] = {}
    contiguous_bars_by_tf: dict[str, list[dict[str, Any]]] = {}
    bullish_count = 0
    support_health_count = 0
    volatility_score = 0.0
    risk_warnings: list[str] = []
    data_quality_warnings: list[str] = []

    def latest_contiguous_segment(
        rows: list[dict[str, Any]], timeframe: str,
    ) -> list[dict[str, Any]]:
        closed = valid_bars(rows)
        if not closed or not _timeframe_start_is_aligned(timeframe, int(closed[-1]["t"])):
            return []
        segment_start = len(closed) - 1
        for cursor in range(len(closed) - 1, 0, -1):
            previous, current = closed[cursor - 1], closed[cursor]
            if (
                not _timeframe_start_is_aligned(timeframe, int(previous["t"]))
                or timeframe_bar_end_ms(timeframe, int(previous["t"])) != int(current["t"])
            ):
                break
            segment_start = cursor - 1
        return closed[segment_start:]

    for timeframe in ("1h", "4h"):
        segment = latest_contiguous_segment(
            bars_by_interval.get(timeframe, []), timeframe
        )[-90:]
        contiguous_bars_by_tf[timeframe] = segment
        if len(segment) < 30:
            reason = (
                "Yeterli kapanmış BTC mumu yok"
                if len(segment) < 30 and not valid_bars(bars_by_interval.get(timeframe, []))
                else "Son kesintisiz BTC mum penceresi yetersiz/kesintili"
            )
            context_by_tf[timeframe] = {
                "available": False,
                "data_sufficient": False,
                "reason": reason,
                "closed_bars_in_latest_contiguous_segment": len(segment),
                "required_closed_bars": 30,
            }
            data_quality_warnings.append(
                f"BTC {timeframe}: ana yön ve seviye bağlamı için son kesintisiz pencere yetersiz."
            )
            continue

        indicators = _indicator_snapshot(segment)
        close = _positive_finite(segment[-1].get("c"))
        ema_slow = _positive_finite(indicators.get("ema_slow"))
        ema_bullish = indicators.get("ema_bullish") is True
        plus_di, minus_di = indicators.get("plus_di_14"), indicators.get("minus_di_14")
        dmi_up = (
            isinstance(plus_di, (int, float))
            and isinstance(minus_di, (int, float))
            and plus_di > minus_di
        )
        previous = segment[-21:-1]
        rolling_20_bar_low = min(
            (float(bar["l"]) for bar in previous), default=None
        )
        atr = _positive_finite(indicators.get("atr_14"))
        if close is None or ema_slow is None:
            context_by_tf[timeframe] = {
                "available": False,
                "data_sufficient": False,
                "reason": "BTC teknik yön verisi hesaplanamadı",
                "closed_bars_in_latest_contiguous_segment": len(segment),
                "required_closed_bars": 30,
            }
            data_quality_warnings.append(
                f"BTC {timeframe}: kapanış veya EMA verisi doğrulanamadı."
            )
            continue

        price_trend = close > ema_slow and ema_bullish
        bullish = price_trend and dmi_up
        bullish_count += int(bullish)

        pivots = _confirmed_pivot_points(segment, timeframe)
        zones = _support_resistance_zones(segment, timeframe, atr, pivots)
        channel = _confirmed_channel(segment, timeframe, atr, pivots)
        strong_supports = [
            zone for zone in zones
            if isinstance(zone, dict) and zone.get("kind") == "support"
            and zone.get("strong") is True
            and _positive_finite(zone.get("lower")) is not None
            and _positive_finite(zone.get("upper")) is not None
        ]
        strong_resistances = [
            zone for zone in zones
            if isinstance(zone, dict) and zone.get("kind") == "resistance"
            and zone.get("strong") is True
            and _positive_finite(zone.get("lower")) is not None
            and _positive_finite(zone.get("upper")) is not None
        ]
        latest_support = max(
            strong_supports,
            key=lambda zone: int(zone.get("last_touch_ms", 0)),
            default=None,
        )
        if latest_support is None:
            support_status = "GÜÇLÜ DESTEK TEYİDİ YOK"
            holding_support: bool | None = None
        else:
            support_lower = float(latest_support["lower"])
            support_upper = float(latest_support["upper"])
            if close < support_lower:
                support_status = "SON GÜÇLÜ DESTEK KAYBEDİLDİ"
                holding_support = False
                risk_warnings.append(
                    f"BTC {timeframe}: son teyitli güçlü destek bölgesinin altında kapanış."
                )
            elif close <= support_upper:
                support_status = "GÜÇLÜ DESTEK BÖLGESİ TEST EDİLİYOR"
                holding_support = True
            else:
                support_status = "SON GÜÇLÜ DESTEK KORUNUYOR"
                holding_support = True
        if holding_support is True:
            support_health_count += 1

        if strong_resistances:
            resistance_inside = [
                zone for zone in strong_resistances
                if float(zone["lower"]) <= close <= float(zone["upper"])
            ]
            resistance_above = [
                zone for zone in strong_resistances
                if float(zone["lower"]) > close
            ]
            resistance_below = [
                zone for zone in strong_resistances
                if float(zone["upper"]) < close
            ]
            if resistance_inside:
                critical_resistance = min(
                    resistance_inside, key=lambda zone: abs(float(zone["center"]) - close)
                )
                resistance_status = "GÜÇLÜ DİRENÇ BÖLGESİ İÇİNDE"
            elif resistance_above:
                critical_resistance = min(
                    resistance_above, key=lambda zone: float(zone["lower"]) - close
                )
                resistance_status = "ÜSTÜNDEKİ GÜÇLÜ DİRENÇ BEKLENİYOR"
            else:
                critical_resistance = max(
                    resistance_below, key=lambda zone: int(zone.get("last_touch_ms", 0))
                )
                resistance_status = "GÜÇLÜ DİRENÇ ÜSTÜNDE — DEVAMLILIK TEYİDİ GEREKİR"
        else:
            critical_resistance = None
            resistance_status = "TEYİTLİ GÜÇLÜ DİRENÇ YOK"

        if isinstance(channel, dict) and channel.get("available") is True:
            channel_lower = _positive_finite(channel.get("lower_now"))
            channel_upper = _positive_finite(channel.get("upper_now"))
            channel_position = channel.get("position_0_to_1")
            if channel_lower is not None and close < channel_lower:
                channel_status = "KANAL ALT SINIRI KAYBEDİLDİ"
                risk_warnings.append(
                    f"BTC {timeframe}: teyitli kanal alt sınırının altında kapanış."
                )
            elif channel_upper is not None and close > channel_upper:
                channel_status = "KANAL ÜSTÜ KIRILIM ADAYI — DEVAMLILIK BEKLENİYOR"
            elif isinstance(channel_position, (int, float)):
                channel_status = "TEYİTLİ KANAL İÇİNDE"
            else:
                channel_status = "KANAL KONUMU HESAPLANAMADI"
        else:
            channel_status = str(
                channel.get("status") if isinstance(channel, dict) else None
            ) or "TEYİTLİ KANAL YOK"

        context_by_tf[timeframe] = {
            "available": True,
            "data_sufficient": True,
            "closed_bars_in_latest_contiguous_segment": len(segment),
            "bullish": bullish,
            "price_above_slow_ema": close > ema_slow,
            "ema_direction_up": ema_bullish,
            "dmi_direction_up": dmi_up,
            "holding_support": holding_support,
            "support_status": support_status,
            "latest_confirmed_support_zone": latest_support,
            "resistance_status": resistance_status,
            "nearest_relevant_resistance_zone": critical_resistance,
            "latest_close": close,
            "previous_support": rolling_20_bar_low,
            "rolling_20_bar_low": rolling_20_bar_low,
            "strong_support_zones": sorted(
                strong_supports,
                key=lambda zone: int(zone.get("last_touch_ms", 0)),
                reverse=True,
            )[:3],
            "strong_resistance_zones": sorted(
                strong_resistances,
                key=lambda zone: int(zone.get("last_touch_ms", 0)),
                reverse=True,
            )[:3],
            "confirmed_channel": channel,
            "channel_status": channel_status,
            "atr_14": atr,
            "distance_to_resistance_atr": (
                round((float(critical_resistance["center"]) - close) / atr, 4)
                if critical_resistance is not None and atr is not None and atr > 0
                else None
            ),
        }
        if resistance_status.startswith("GÜÇLÜ DİRENÇ ÜSTÜNDE"):
            context_by_tf[timeframe]["resistance_breakout_confirmation_pending"] = True

    direction_score = min(4.0, 2.0 * bullish_count)
    critical_level_score = min(3.0, 1.5 * support_health_count)

    hourly = contiguous_bars_by_tf.get("1h", [])
    if len(hourly) >= 54:
        recent_ranges = true_ranges(hourly[-14:])
        baseline_ranges = true_ranges(hourly[-54:-14])
        recent_typical_range = median(recent_ranges)
        baseline_typical_range = median(baseline_ranges)
        if (
            recent_typical_range is not None and recent_typical_range > 0
            and baseline_typical_range is not None and baseline_typical_range > 0
        ):
            volatility_ratio = recent_typical_range / baseline_typical_range
            if volatility_ratio <= 1.5:
                volatility_score = 3.0
            elif volatility_ratio <= 2.0:
                volatility_score = 1.5
            else:
                volatility_score = 0.0
                risk_warnings.append(
                    f"BTC 1h oynaklığı son 14 mumda önceki 40 mumun medyan aralığının {volatility_ratio:.2f} katı."
                )
        else:
            volatility_ratio = None
            data_quality_warnings.append("BTC 1h oynaklık karşılaştırması hesaplanamadı.")
    else:
        volatility_ratio = None
        data_quality_warnings.append(
            "BTC 1h oynaklık puanı için en az 54 kesintisiz kapanmış mum gerekiyor."
        )

    available_count = sum(
        1 for row in context_by_tf.values() if row.get("available") is True
    )
    if available_count < 2:
        data_quality_warnings.append(
            "BTC ana yön/seviye bağlamı kısmi; eksik zaman dilimi için olumlu puan verilmedi."
        )
    return {
        "direction_score": direction_score,
        "critical_level_score": critical_level_score,
        "volatility_score": volatility_score,
        "total_score": round(direction_score + critical_level_score + volatility_score, 2),
        "bullish_timeframes": bullish_count,
        "support_holding_timeframes": support_health_count,
        "critical_level_loss_timeframes": [
            timeframe for timeframe, row in context_by_tf.items()
            if row.get("support_status") == "SON GÜÇLÜ DESTEK KAYBEDİLDİ"
            or row.get("channel_status") == "KANAL ALT SINIRI KAYBEDİLDİ"
        ],
        "relative_volatility_ratio": round(volatility_ratio, 6) if volatility_ratio is not None else None,
        "timeframes": context_by_tf,
        "risk_warnings": list(dict.fromkeys(risk_warnings)),
        "data_quality_warnings": list(dict.fromkeys(data_quality_warnings)),
        "data_completeness": "TAM" if available_count == 2 else "KISMİ" if available_count else "EKSİK",
        "status": "HESAPLANDI" if available_count else "BTC VERİSİ EKSİK",
    }

def assess_btc_strong_opportunity_gate(
    context: dict[str, Any] | None,
    *,
    freshness: str | None,
    require_measurements: bool = False,
) -> dict[str, Any]:
    """Single source of truth for BTC context eligibility of strong opportunities/alerts."""
    btc = context if isinstance(context, dict) else {}
    freshness_ok = freshness is None or freshness == "CANLI AKIŞ GÜNCEL"
    has_completeness = "data_completeness" in btc
    volatility_ratio = _positive_finite(btc.get("relative_volatility_ratio"))
    volatility_valid = volatility_ratio is not None
    if has_completeness:
        complete = btc.get("data_completeness") == "TAM" and volatility_valid
    else:
        complete = not require_measurements
    if require_measurements and not has_completeness:
        complete = False

    raw_losses = btc.get("critical_level_loss_timeframes")
    losses = (
        [str(item) for item in raw_losses if isinstance(item, str) and item]
        if isinstance(raw_losses, list) else []
    )
    extreme_volatility = volatility_valid and float(volatility_ratio) > 2.0

    reasons: list[str] = []
    if not freshness_ok:
        reasons.append("BTC 1h/4h canlı bağlamı eski/eksik; güçlü fırsat/alarm kapalı.")
    elif not complete:
        reasons.append(
            "BTC yön/seviye/oynaklık bağlamı için yeterli kesintisiz ölçüm yok; güçlü fırsat/alarm kapalı."
        )
    if losses:
        reasons.append(
            "BTC kritik destek veya teyitli kanal alt sınırı kaybı var ("
            + ", ".join(losses)
            + "); güçlü fırsat/alarm kapalı."
        )
    if extreme_volatility:
        reasons.append("BTC 1h oynaklık oranı 2,0 katı aşıyor; güçlü fırsat/alarm kapalı.")

    return {
        "eligible": freshness_ok and complete and not losses and not extreme_volatility,
        "fresh": freshness_ok,
        "complete": complete,
        "critical_level_loss_timeframes": losses,
        "relative_volatility_ratio": volatility_ratio,
        "extreme_volatility": bool(extreme_volatility),
        "reasons": reasons,
    }


def evaluate_binance_candidate(symbol: str, bars_by_interval: dict[str, list[dict[str, Any]]],
                               btc_bars_by_interval: dict[str, list[dict[str, Any]]] | None = None,
                               pair: dict[str, Any] | None = None,
                               settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """A/B/C aşamalarından en güçlü güncel aşamayı seçer; sabit toplam puan yoktur."""
    findings: list[str] = []
    missing: list[str] = []
    relative, correlation = _relative_strength_and_correlation(
        bars_by_interval, btc_bars_by_interval
    )
    timeframe_results: dict[str, Any] = {}
    eligible_phase_results: list[dict[str, Any]] = []
    for tf in ("5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"):
        assessment = assess_timeframe(bars_by_interval.get(tf, []), tf, settings)
        timeframe_results[tf] = assessment
        if assessment.get("missing_checks"):
            missing.extend(assessment["missing_checks"])
        if assessment.get("phase"):
            findings.extend([f"{tf}: {x}" for x in assessment.get("findings", [])])
            if tf in ("5m", "15m", "30m", "1h"):
                eligible_phase_results.append(assessment)

    if not eligible_phase_results:
        symbol_pair = pair or {}
        price_rows = (bars_by_interval.get("5m", []) or bars_by_interval.get("15m", [])
                      or bars_by_interval.get("30m", []))
        latest = price_rows[-1] if price_rows else {}
        recent_closed = {}
        for tf in ("5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"):
            closed_rows = valid_bars(bars_by_interval.get(tf, []))
            recent_closed[tf] = [
                {key: row.get(key) for key in ("t", "o", "h", "l", "c", "v", "q", "n")}
                for row in closed_rows[-8:]
            ]
        return {
            "symbol": symbol, "base_asset": symbol_pair.get("base_asset"),
            "quote_asset": "USDT", "source": "Binance Spot", "phase": None,
            "state": "ADAY DEĞİL — HAZIRLIK/YÖNLÜ YAPI EŞİĞİ OLUŞMADI",
            "phase_timeframe": None, "latest_price": latest.get("c"),
            "latest_bar_start_ms": latest.get("t"), "findings": [], "evidence_groups": [],
            "timeframes": timeframe_results, "higher_timeframe_context": {},
            "recent_closed_candles": recent_closed,
            "relative_strength_vs_btc_pct_points": relative,
            "btc_return_correlation": correlation,
            "missing_checks": sorted(set(missing)),
            "source_market_pair": symbol_pair.get("binance_symbol", symbol),
            "btcturk_market_pair": symbol_pair.get("btcturk_symbol"),
            "category_status": symbol_pair.get("category_status"),
            "generated_at_utc": utc_now(),
            "data_note": "Bu kayıt tarama kapsamı/audit içindir; aday aşaması değildir.",
        }
    eligible_phase_results.sort(key=lambda row: (
        PHASE_ORDER.get(row.get("phase"), 0),
        len(set(row.get("evidence_groups", []))),
        row.get("metrics", {}).get("close_time_ms", 0),
    ), reverse=True)
    chosen = eligible_phase_results[0]
    phase = chosen["phase"]
    # Daha yüksek TF'ler filtre değil, risk ve öncelik bağlamıdır.
    higher_context = {}
    for tf in ("4h", "1d", "1w", "1M"):
        closed = valid_bars(bars_by_interval.get(tf, []))
        mean = sma([float(b["c"]) for b in closed], 20)
        if len(closed) >= 20 and mean:
            above = float(closed[-1]["c"]) > mean
            upward = len(closed) >= 2 and float(closed[-1]["c"]) > float(closed[-2]["c"])
            higher_context[tf] = {"above_sma20": above, "last_candle_up": upward}
            if not above:
                findings.append(f"Bağlam uyarısı: {tf} fiyatı 20 mum ortalamasının altında")
        else:
            higher_context[tf] = {"status": "YETERLİ GEÇMİŞ YOK"}
            missing.append(f"{tf}: üst zaman dilimi bağlamı için yeterli veri yok")

    positive_rel = [tf for tf, value in relative.items() if value is not None and value > 0]
    if positive_rel:
        findings.append("BTC'ye göre eş zamanlı kapanış getirilerinde göreceli güç pozitif: "
                        + ", ".join(positive_rel))
    if not btc_bars_by_interval or all(value is None for value in relative.values()):
        missing.append("BTC ile eş zamanlı kapanmış mumlardan göreceli güç hesaplanamadı")
    if not any(value.get("value") is not None for value in correlation.values()):
        missing.append("BTC korelasyonu için eş zamanlı ve yeterli kapanmış mum gözlemi yok")

    price_rows = (bars_by_interval.get("5m", []) or bars_by_interval.get("15m", [])
                  or bars_by_interval.get("30m", []))
    latest = price_rows[-1] if price_rows else chosen.get("metrics", {})
    symbol_pair = pair or {}
    recent_closed_candles = {}
    for tf in ("5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"):
        closed_rows = valid_bars(bars_by_interval.get(tf, []))
        recent_closed_candles[tf] = [
            {key: row.get(key) for key in ("t", "o", "h", "l", "c", "v", "q", "n")}
            for row in closed_rows[-8:]
        ]
    result = {
        "symbol": symbol, "base_asset": symbol_pair.get("base_asset"),
        "quote_asset": "USDT", "source": "Binance Spot",
        "phase": phase, "state": chosen.get("state"),
        "phase_timeframe": chosen.get("timeframe"),
        "latest_price": latest.get("c"),
        "latest_bar_start_ms": latest.get("t", chosen.get("metrics", {}).get("close_time_ms")),
        "findings": list(dict.fromkeys(findings)),
        "evidence_groups": sorted(set(chosen.get("evidence_groups", []))),
        "timeframes": timeframe_results, "higher_timeframe_context": higher_context,
        "recent_closed_candles": recent_closed_candles,
        "relative_strength_vs_btc_pct_points": relative,
        "btc_return_correlation": correlation,
        "missing_checks": sorted(set(missing)),
        "source_market_pair": symbol_pair.get("binance_symbol", symbol),
        "btcturk_market_pair": symbol_pair.get("btcturk_symbol"),
        "category_status": symbol_pair.get("category_status"),
        "generated_at_utc": utc_now(),
        "data_note": "A hazırlıktır; B aynı zaman diliminde kapanmış mumda fiyat yapısı+hacim doğrulamasıdır; C devamlılık bulgusudur. AL/emir değildir.",
    }
    result["risk_plan"] = build_trade_plan(result)
    return result


def score_opportunity(
    candidate: dict[str, Any],
    *,
    btc_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce one evidence-based 0–100 score and a single final decision label."""
    assessments = candidate.get("timeframes")
    assessments = assessments if isinstance(assessments, dict) else {}
    phase_tf = str(candidate.get("phase_timeframe") or "")
    phase_assessment = assessments.get(phase_tf)
    phase_assessment = phase_assessment if isinstance(phase_assessment, dict) else None

    def metrics_for(timeframe: str) -> dict[str, Any]:
        row = assessments.get(timeframe)
        if not isinstance(row, dict):
            return {}
        data = row.get("metrics")
        return data if isinstance(data, dict) else {}

    short_timeframes = ("15m", "30m", "1h")
    short_metrics = [metrics_for(tf) for tf in short_timeframes]
    short_metrics = [metrics for metrics in short_metrics if metrics]
    primary_metrics = metrics_for(phase_tf) if phase_tf else {}
    if not primary_metrics:
        ranked = [
            (len(set((assessments.get(tf) or {}).get("evidence_groups", []))),
             (assessments.get(tf) or {}).get("metrics", {}).get("close_time_ms", 0),
             metrics_for(tf))
            for tf in ("5m", "15m", "30m", "1h")
            if metrics_for(tf)
        ]
        if ranked:
            primary_metrics = max(ranked, key=lambda item: (item[0], item[1]))[2]
    candidate_price = _positive_finite(candidate.get("latest_price"))
    if candidate_price is None:
        candidate_price = _positive_finite(primary_metrics.get("close"))

    early_squeeze = 6 if any(row.get("compression") is True for row in short_metrics) else 0
    early_rising_lows = 6 if any(row.get("rising_lows") is True for row in short_metrics) else 0
    early_near_resistance = 4 if any(row.get("near_resistance") is True for row in short_metrics) else 0
    early_other_structure = 4 if any(
        (
            row.get("directional_structure") is True
            and not row.get("compression")
            and not row.get("rising_lows")
            and not row.get("near_resistance")
        ) or (
            row.get("continuity") is True and row.get("retest_hold") is True
        )
        for row in short_metrics
    ) else 0
    early_score = min(
        20, early_squeeze + early_rising_lows + early_near_resistance + early_other_structure
    )

    unusual_volume_score = 10 if primary_metrics.get("volume_unusual") is True else 0
    persistence_count = primary_metrics.get("volume_persistence_count", 0)
    persistence_score = 5 if isinstance(persistence_count, int) and persistence_count >= 2 else 0
    volume_score = min(15, unusual_volume_score + persistence_score)

    # EMA bonus requires the fast/slow order, both slopes, and price location.
    # Keep ema_bullish itself unchanged because the shared BTC trend context uses it.
    ema_score = 5 if primary_metrics.get("ema_confirmed_bullish") is True else 0
    histogram = _finite_numeric_metric(primary_metrics.get("macd_histogram"))
    macd_positive_score = 3 if histogram is not None and histogram > 0 else 0
    macd_rising_score = 2 if primary_metrics.get("macd_histogram_rising") is True else 0
    rsi = _finite_numeric_metric(primary_metrics.get("rsi_14"))
    rsi_score = (
        5 if rsi is not None and 55 <= rsi <= 70
        else 2 if rsi is not None and 70 < rsi <= 80
        else 0
    )
    momentum_score = min(15, ema_score + macd_positive_score + macd_rising_score + rsi_score)

    adx = _finite_numeric_metric(primary_metrics.get("adx_14"))
    adx_score = 5 if adx is not None and adx >= 20 else 0
    plus_di = _finite_numeric_metric(primary_metrics.get("plus_di_14"))
    minus_di = _finite_numeric_metric(primary_metrics.get("minus_di_14"))
    dmi_score = 5 if (
        plus_di is not None and minus_di is not None and plus_di > minus_di
    ) else 0
    trend_score = min(10, adx_score + dmi_score)

    sr_score = 0
    sr_confluence_timeframes: set[str] = set()
    channel_score = 0
    fib_htf_score = 0
    for timeframe, row in assessments.items():
        if not isinstance(row, dict):
            continue
        timeframe_name = str(timeframe)
        metrics = metrics_for(timeframe_name)
        close = _positive_finite(metrics.get("close"))
        atr = _positive_finite(metrics.get("atr_14"))
        zones = metrics.get("support_resistance_zones")
        if close is not None and atr is not None and isinstance(zones, list):
            has_near_strong_zone = any(
                isinstance(zone, dict)
                and zone.get("strong") is True
                and _positive_finite(zone.get("center")) is not None
                and abs(close - float(zone["center"])) <= 0.5 * atr
                for zone in zones
            )
            if has_near_strong_zone:
                sr_confluence_timeframes.add(timeframe_name)

        channel = metrics.get("confirmed_channel")
        if channel_score == 0 and isinstance(channel, dict) and channel.get("available") is True:
            position = channel.get("position_0_to_1")
            direction = channel.get("direction")
            position_value = _finite_numeric_metric(position)
            if (
                position_value is not None
                and 0.0 <= position_value <= 0.8
                and direction in {"YÜKSELEN", "YATAY"}
            ):
                channel_score = 5

        fib = metrics.get("fibonacci")
        if (
            fib_htf_score == 0
            and str(timeframe) in {"4h", "1d", "1w", "1M"}
            and isinstance(fib, dict)
            and fib.get("available") is True
            and fib.get("direction") == "up"
        ):
            atr = _positive_finite(metrics.get("atr_14"))
            levels = []
            for group in ("retracements", "extensions"):
                values = fib.get(group)
                if isinstance(values, dict):
                    levels.extend(
                        number for value in values.values()
                        if (number := _finite_numeric_metric(value)) is not None and number > 0
                    )
            if close is not None and atr is not None and levels and min(
                abs(close - level) for level in levels
            ) <= 0.5 * atr:
                fib_htf_score = 5
    # One nearby zone is a local level, not multi-timeframe confluence.
    sr_score = 5 if len(sr_confluence_timeframes) >= 2 else 0

    higher_context = candidate.get("higher_timeframe_context")
    higher_context = higher_context if isinstance(higher_context, dict) else {}
    aligned_higher = sum(
        1 for tf in ("4h", "1d", "1w", "1M")
        if isinstance(higher_context.get(tf), dict)
        and higher_context[tf].get("above_sma20") is True
        and higher_context[tf].get("last_candle_up") is True
    )
    # Üst zaman dilimi uyumu, doğrulanmış kanal kanıtı değildir.
    # Aynı SMA/kapanış kanıtını hem kanal hem üst-zaman-dilimi puanı olarak sayma.
    if sr_score == 0 and channel_score == 0 and fib_htf_score == 0 and aligned_higher >= 2:
        # High-timeframe SMA/close alignment is a fallback only; it must not stack
        # on separately credited support/resistance, a confirmed channel or Fibonacci.
        fib_htf_score = 2
    multi_timeframe_score = min(15, sr_score + channel_score + fib_htf_score)

    # If a live BTC context is explicitly stale/incomplete, none of its derived
    # relative-strength or peer-leadership values may contribute to the score.
    btc_freshness_value = candidate.get("btc_market_context_freshness")
    btc_context_explicitly_stale = (
        btc_freshness_value is not None
        and btc_freshness_value != "CANLI AKIŞ GÜNCEL"
    )
    relative = candidate.get("relative_strength_vs_btc_pct_points")
    relative = relative if isinstance(relative, dict) and not btc_context_explicitly_stale else {}
    positive_horizons = sum(
        1 for tf in ("15m", "1h", "4h")
        if (
            (relative_value := _finite_numeric_metric(relative.get(tf))) is not None
            and relative_value > 0
        )
    )
    relative_strength_score = 6 if positive_horizons >= 2 else 3 if positive_horizons == 1 else 0
    group_category = candidate.get("group_category")
    group_comparable_count = candidate.get("group_comparable_count")
    group_leadership_verified = (
        candidate.get("group_category_verified") is True
        and isinstance(group_category, str)
        and bool(group_category.strip())
        and isinstance(group_comparable_count, int)
        and not isinstance(group_comparable_count, bool)
        and group_comparable_count >= 3
        and not btc_context_explicitly_stale
    )
    group_leadership = (
        candidate.get("group_leadership_score") if group_leadership_verified else None
    )
    group_leadership_value = _finite_numeric_metric(group_leadership)
    if group_leadership_value is not None:
        group_score = min(4, max(0, int(round(group_leadership_value))))
    else:
        group_score = 0
    relative_strength_score = min(10, relative_strength_score + group_score)

    btc_context = btc_context if isinstance(btc_context, dict) else {}
    btc_direction = btc_context.get("direction_score", 0)
    btc_level = btc_context.get("critical_level_score", 0)
    btc_volatility = btc_context.get("volatility_score", 0)
    btc_direction_value = _finite_numeric_metric(btc_direction)
    btc_level_value = _finite_numeric_metric(btc_level)
    btc_volatility_value = _finite_numeric_metric(btc_volatility)
    btc_scores = [
        min(4, max(0, btc_direction_value)) if btc_direction_value is not None else 0,
        min(3, max(0, btc_level_value)) if btc_level_value is not None else 0,
        min(3, max(0, btc_volatility_value)) if btc_volatility_value is not None else 0,
    ]
    btc_score = 0.0 if btc_context_explicitly_stale else round(sum(btc_scores), 2)

    liquidity = candidate.get("liquidity_assessment")
    liquidity = liquidity if isinstance(liquidity, dict) else {}
    liquidity_score = 0
    if liquidity.get("quote_volume_quality_passed") is True:
        liquidity_score += 2
    if liquidity.get("spread_quality_passed") is True:
        liquidity_score += 1
    if liquidity.get("depth_quality_passed") is True:
        liquidity_score += 2
    components = {
        "early_price_structure": early_score,
        "volume_participation": volume_score,
        "momentum": momentum_score,
        "trend_direction_strength": trend_score,
        "multi_timeframe_structure": multi_timeframe_score,
        "relative_strength_group_leadership": relative_strength_score,
        "btc_market_context": btc_score,
        "liquidity_tradability": liquidity_score,
    }
    total_score = min(100, max(0, int(round(sum(components.values())))))

    plan = candidate.get("risk_plan")
    plan = plan if isinstance(plan, dict) else {}
    stop_price = _positive_finite(plan.get("stop_loss"))
    entry_low = _positive_finite(plan.get("entry_zone_low"))
    entry_high = _positive_finite(plan.get("entry_zone_high"))
    plan_targets = plan.get("targets")
    plan_target_prices = [
        _positive_finite(row.get("price"))
        for row in plan_targets if isinstance(row, dict)
    ] if isinstance(plan_targets, list) else []
    has_target_beyond_entry_zone = (
        entry_high is not None
        and any(price is not None and price > entry_high for price in plan_target_prices)
    )
    has_explicit_invalidation = (
        isinstance(plan.get("invalid_if"), str) and bool(plan["invalid_if"].strip())
    )
    valid_plan = (
        stop_price is not None and entry_low is not None and entry_high is not None
        and stop_price < entry_low
        and entry_high >= entry_low
        and plan.get("technical_targets_available") is True
        and has_target_beyond_entry_zone
        and has_explicit_invalidation
    )
    cost_rr = plan.get("net_risk_reward")
    after_cost_rr_valid = (
        isinstance(cost_rr, (int, float)) and math.isfinite(cost_rr) and cost_rr >= 1.5
        and plan.get("costs_included") is True
    )
    entry_not_chased = (
        candidate_price is not None and entry_low is not None and entry_high is not None
        and entry_low <= candidate_price <= entry_high
        and plan.get("status") == "FİYAT GİRİŞ BÖLGESİNDE — KOŞULLU"
    )
    liquidity_passed = liquidity.get("passed") is True
    eligible = candidate.get("strong_alarm_eligible") is True
    fresh = candidate.get("data_freshness") == "CANLI AKIŞ GÜNCEL"
    phase = candidate.get("phase")

    # Historical replay may omit stream age but still supplies its as-of BTC measurements.
    btc_freshness_value = candidate.get("btc_market_context_freshness")
    btc_strong_gate = assess_btc_strong_opportunity_gate(
        btc_context,
        freshness=btc_freshness_value,
        require_measurements=False,
    )
    btc_context_gate_passed = btc_strong_gate["eligible"]
    strong_qualified = bool(
        total_score >= 80
        and phase in ("B", "C")
        and fresh
        and eligible
        and liquidity_passed
        and entry_not_chased
        and valid_plan
        and after_cost_rr_valid
        and btc_context_gate_passed
    )

    gate_reasons: list[str] = []
    if not fresh:
        gate_reasons.append("Canlı mum verisi güncel değil veya eksik.")
    if not eligible:
        gate_reasons.append(
            str(candidate.get("strong_alarm_block_reason") or
                "Parite güçlü fırsat için kaynak/uygunluk filtresinden geçmedi.")
        )
    if not liquidity_passed:
        gate_reasons.extend(
            str(reason) for reason in liquidity.get("failed_gates", [])
            if isinstance(reason, str) and reason
        )
        if not liquidity.get("failed_gates"):
            gate_reasons.append("Binance likidite koşulları henüz doğrulanmadı.")
    if phase not in ("B", "C"):
        gate_reasons.append("A/B/C teknik aşaması B veya C değil.")
    if total_score < 80:
        gate_reasons.append("Fırsat puanı 80/100 eşiğinin altında.")
    if not entry_not_chased:
        gate_reasons.append("Teknik giriş bölgesi güncel fiyatta kovalanmadan doğrulanmadı.")
    if not valid_plan:
        gate_reasons.append("Teknik destek/direnç veya Fibonacci tabanlı hedef içeren geçerli plan yok.")
    if not after_cost_rr_valid:
        gate_reasons.append("Komisyon, spread ve kayma sonrası net risk/getiri ≥1,5 doğrulanmadı.")
    gate_reasons.extend(btc_strong_gate["reasons"])

    near_resistance = any(row.get("near_resistance") is True for row in short_metrics)
    continuity_confirmed = any(
        row.get("continuity") is True and row.get("continuity_volume_confirmed") is True
        for row in short_metrics
    )
    # A price below the entry zone means "wait for a valid entry"; only the
    # explicit structural invalidation/stop is allowed to classify this setup invalid.
    invalidated = (
        stop_price is not None and candidate_price is not None
        and candidate_price <= stop_price
    )
    if not fresh:
        decision = "İŞLEM YOK"
        decision_reason = "Canlı mum verisi güncel değil veya eksik; güncel fırsat kararı üretilemez."
    elif invalidated:
        decision = "FIRSAT GEÇERSİZ"
        decision_reason = (
            "Güncel ve geçerli piyasa fiyatı teknik kırılım/zarar durdurma invalidasyon seviyesini aştı."
        )
    elif liquidity.get("passed") is False:
        decision = "İŞLEM YOK"
        decision_reason = "Doğrulanmış likidite ölçümlerinden biri zorunlu eşiği geçemedi."
    elif strong_qualified:
        decision = "GÜÇLÜ FIRSAT"
        decision_reason = (
            "Puan, B/C teyidi, güncel veri, teknik giriş/stop/hedef, likidite "
            "ve maliyet sonrası net risk/getiri koşullarının tamamı sağlandı."
        )
    elif total_score < 45:
        decision = "İŞLEM YOK"
        decision_reason = "Doğrulanmış fırsat kanıtı 45/100 taban eşiğine ulaşmadı."
    elif phase not in ("B", "C") and near_resistance and not continuity_confirmed:
        decision = "KIRILIM BEKLENİYOR"
        decision_reason = "Direnç yakınında; kapanmış mum ve katılım devamlılığı teyidi bekleniyor."
    elif total_score >= 65:
        decision = "ERKEN ADAY"
        decision_reason = "Erken fiyat yapısı/ivme/katılım puanı anlamlı; güçlü fırsat kapıları eksik."
    else:
        decision = "İZLEMEDE"
        decision_reason = "Bazı teknik kanıtlar var ancak işlem önceliği için yeterli değil."

    if not eligible and decision in {"ERKEN ADAY", "KIRILIM BEKLENİYOR", "İZLEMEDE"}:
        restriction = str(
            candidate.get("strong_alarm_block_reason")
            or "Parite güçlü alarm uygunluk filtresinden geçmedi."
        ).strip()
        if restriction:
            decision_reason += f" Güçlü alarm kapalı: {restriction}."
    if liquidity.get("passed") is None and "Binance likidite koşulları henüz doğrulanmadı." not in gate_reasons:
        gate_reasons.append("Binance likidite koşulları henüz doğrulanmadı.")
    return {
        "opportunity_score": total_score,
        "score_0_100": total_score,
        "score_components": components,
        "final_decision": decision,
        "decision_class": decision,
        "decision_reason": decision_reason,
        "strong_opportunity_qualified": strong_qualified,
        "strong_opportunity_gate_reasons": list(dict.fromkeys(gate_reasons)),
    }


def aggregate_bars(bars: list[dict[str, Any]], interval_minutes: int) -> list[dict[str, Any]]:
    """1 dakikalık mumları epoch sınırlarına göre türetir; eksik dakikada barı doğrulanmış saymaz."""
    interval_ms = interval_minutes * 60_000
    buckets: dict[int, list[dict[str, Any]]] = {}
    for bar in bars:
        start = int(bar["t"]) // interval_ms * interval_ms
        buckets.setdefault(start, []).append(bar)
    output: list[dict[str, Any]] = []
    now_ms = int(time.time() * 1000)
    for start in sorted(buckets):
        group = sorted(buckets[start], key=lambda x: x["t"])
        expected_count = interval_minutes
        contiguous = len({int(b["t"]) for b in group}) == len(group)
        # 5/15/30 dakikalık mum yalnızca doğru sınırdaki tam dakika grubuysa kapanmış sayılır.
        fully_formed = len(group) == expected_count and contiguous and all(
            int(b["t"]) // 60_000 * 60_000 == int(b["t"]) for b in group
        )
        end_ms = start + interval_ms
        is_closed = end_ms <= now_ms and fully_formed and all(bool(b.get("closed", True)) for b in group)
        output.append({
            "t": start, "o": float(group[0]["o"]),
            "h": max(float(b["h"]) for b in group),
            "l": min(float(b["l"]) for b in group),
            "c": float(group[-1]["c"]),
            "v": sum(float(b.get("v", 0) or 0) for b in group),
            "q": sum(float(b.get("q", 0) or 0) for b in group),
            "n": sum(int(b.get("n", 0) or 0) for b in group),
            "closed": is_closed, "synthetic": any(bool(b.get("synthetic", False)) for b in group),
            "source_bar_count": len(group), "expected_source_bar_count": expected_count,
            "incomplete": not fully_formed,
        })
    return output
