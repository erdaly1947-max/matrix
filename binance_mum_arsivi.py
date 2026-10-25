"""Binance Spot kapanmış OHLCV mumları için kalıcı SQLite arşivi.

Kayıt anahtarı sembol, zaman dilimi ve mum açılış zamanıdır. Yalnızca doğrulanmış,
kapanmış ve sentetik olmayan mumlar saklanır. Aday geçmişi bakımından ayrıdır;
bu arşivde otomatik saklama süresi veya silme işlemi uygulanmaz.
"""
from __future__ import annotations

import math
import re
import sqlite3
from contextlib import contextmanager
import threading
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from radar_core import valid_bars

DAY_MS = 86_400_000
DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_MIN_CANDLES = 90
SUPPORTED_TIMEFRAMES = ("5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M")
_FIXED_INTERVAL_MS = {
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": DAY_MS,
    "1w": 7 * DAY_MS,
}
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,30}$")


def _utc_datetime(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def _month_start(value: datetime) -> datetime:
    return datetime(value.year, value.month, 1, tzinfo=timezone.utc)


def _previous_month_start(value: datetime) -> datetime:
    current = _month_start(value)
    previous_day = current - timedelta(days=1)
    return _month_start(previous_day)


def current_candle_open_ms(timeframe: str, now_ms: int | None = None) -> int:
    """Return the open time of the currently forming candle in UTC milliseconds."""
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Desteklenmeyen zaman dilimi: {timeframe}")
    current_ms = int(datetime.now(timezone.utc).timestamp() * 1000) if now_ms is None else now_ms
    if isinstance(current_ms, bool) or not isinstance(current_ms, int) or current_ms <= 0:
        raise ValueError("now_ms pozitif bir milisaniye zaman damgası olmalı.")
    current = _utc_datetime(current_ms)
    if timeframe == "1M":
        return int(_month_start(current).timestamp() * 1000)
    if timeframe == "1w":
        monday = current.date() - timedelta(days=current.weekday())
        start = datetime.combine(monday, datetime_time.min, tzinfo=timezone.utc)
        return int(start.timestamp() * 1000)
    interval_ms = _FIXED_INTERVAL_MS[timeframe]
    return (current_ms // interval_ms) * interval_ms


def history_window_start_ms(
    timeframe: str,
    now_ms: int | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    min_candles: int = DEFAULT_MIN_CANDLES,
) -> int:
    """Start of the required history window, aligned to UTC candle boundaries.

    The start is the earlier of a 30-day time window and the requested number of
    candle intervals. This keeps both calendar coverage and indicator warm-up:
    e.g. 5m needs a month, while 1d/1w/1M need at least 90 daily/weekly/monthly
    candles. Weekly starts align to Monday; monthly starts follow calendar months.
    """
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Desteklenmeyen zaman dilimi: {timeframe}")
    if isinstance(lookback_days, bool) or not isinstance(lookback_days, int):
        raise ValueError("lookback_days gerçek bir tamsayı olmalı.")
    if not 1 <= lookback_days <= 3650:
        raise ValueError("lookback_days 1 ile 3650 arasında olmalı.")
    if isinstance(min_candles, bool) or not isinstance(min_candles, int):
        raise ValueError("min_candles gerçek bir tamsayı olmalı.")
    if not 1 <= min_candles <= 5000:
        raise ValueError("min_candles 1 ile 5000 arasında olmalı.")
    current_ms = int(datetime.now(timezone.utc).timestamp() * 1000) if now_ms is None else now_ms
    if isinstance(current_ms, bool) or not isinstance(current_ms, int) or current_ms <= 0:
        raise ValueError("now_ms pozitif bir milisaniye zaman damgası olmalı.")
    current = _utc_datetime(current_ms)
    time_target_ms = current_ms - lookback_days * DAY_MS
    time_target = _utc_datetime(time_target_ms)
    if timeframe == "1M":
        time_start_ms = int(_previous_month_start(current).timestamp() * 1000)
        month_index = current.year * 12 + current.month - 1 - min_candles
        candle_start = datetime(
            month_index // 12, month_index % 12 + 1, 1, tzinfo=timezone.utc,
        )
        candle_start_ms = int(candle_start.timestamp() * 1000)
        return min(time_start_ms, candle_start_ms)
    if timeframe == "1w":
        target_monday = time_target.date() - timedelta(days=time_target.weekday())
        time_start = datetime.combine(target_monday, datetime_time.min, tzinfo=timezone.utc)
        candle_start_ms = current_candle_open_ms(timeframe, now_ms=current_ms) - (
            min_candles * _FIXED_INTERVAL_MS[timeframe]
        )
        return min(int(time_start.timestamp() * 1000), candle_start_ms)
    interval_ms = _FIXED_INTERVAL_MS[timeframe]
    time_start_ms = (time_target_ms // interval_ms) * interval_ms
    candle_start_ms = current_candle_open_ms(timeframe, now_ms=current_ms) - (
        min_candles * interval_ms
    )
    return min(time_start_ms, candle_start_ms)


def next_candle_open_ms(open_time_ms: int, timeframe: str) -> int:
    """Return the next expected candle-open timestamp (milliseconds)."""
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Desteklenmeyen zaman dilimi: {timeframe}")
    if isinstance(open_time_ms, bool) or not isinstance(open_time_ms, int) or open_time_ms <= 0:
        raise ValueError("open_time_ms pozitif bir milisaniye zaman damgası olmalı.")
    if timeframe != "1M":
        return open_time_ms + _FIXED_INTERVAL_MS[timeframe]
    opened = _utc_datetime(open_time_ms)
    if opened.month == 12:
        next_month = datetime(opened.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(opened.year, opened.month + 1, 1, tzinfo=timezone.utc)
    return int(next_month.timestamp() * 1000)


def _coalesce_ranges(
    ranges: list[tuple[int, int]], timeframe: str, *, maximum_page_bars: int = 1000,
) -> list[tuple[int, int]]:
    if not ranges:
        return []
    interval_ms = 31 * DAY_MS if timeframe == "1M" else _FIXED_INTERVAL_MS[timeframe]
    max_span_ms = interval_ms * max(1, maximum_page_bars - 1)
    merged: list[list[int]] = []
    for start_ms, end_ms in sorted(ranges):
        if end_ms <= start_ms:
            continue
        if merged and start_ms - merged[-1][1] <= max_span_ms:
            merged[-1][1] = max(merged[-1][1], end_ms)
        else:
            merged.append([start_ms, end_ms])
    return [(start_ms, end_ms) for start_ms, end_ms in merged]


def find_missing_ranges(
    timestamps_ms: Iterable[int],
    timeframe: str,
    start_ms: int,
    end_ms: int,
    *,
    fill_prefix: bool = False,
) -> list[tuple[int, int]]:
    """Find absent candle-open ranges inside [start_ms, end_ms).

    If an older archive exists before the requested window, `fill_prefix` asks
    the caller to repair a missing leading section too. For newly listed symbols,
    a missing prefix before the first known candle is not assumed to be a data loss.
    """
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Desteklenmeyen zaman dilimi: {timeframe}")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (start_ms, end_ms)):
        raise ValueError("Aralık sınırları tamsayı milisaniye olmalı.")
    if start_ms <= 0 or end_ms < start_ms:
        raise ValueError("Geçersiz mum geçmişi aralığı.")
    if end_ms == start_ms:
        return []
    times = sorted({
        value for value in timestamps_ms
        if isinstance(value, int) and not isinstance(value, bool) and start_ms <= value < end_ms
    })
    if not times:
        return [(start_ms, end_ms)]

    cursor = start_ms if fill_prefix else times[0]
    ranges: list[tuple[int, int]] = []
    for timestamp in times:
        if timestamp < cursor:
            continue
        if timestamp > cursor:
            ranges.append((cursor, timestamp))
        next_open = next_candle_open_ms(timestamp, timeframe)
        if next_open <= timestamp:
            raise ValueError("Mum geçmişi sıralaması ilerleyemedi.")
        cursor = max(cursor, next_open)
    if cursor < end_ms:
        ranges.append((cursor, end_ms))
    return _coalesce_ranges(ranges, timeframe)


class CandleArchive:
    """SQLite-backed, durable OHLCV archive with a unique candle key."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._schema_lock = threading.Lock()
        self._schema_ready = False

    @staticmethod
    def _validate_key(symbol: str, timeframe: str) -> tuple[str, str]:
        normalized_symbol = str(symbol).strip().upper()
        if not _SYMBOL_RE.fullmatch(normalized_symbol):
            raise ValueError(f"Geçersiz Binance sembolü: {symbol!r}")
        if timeframe not in SUPPORTED_TIMEFRAMES:
            raise ValueError(f"Desteklenmeyen zaman dilimi: {timeframe}")
        return normalized_symbol, timeframe

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=30.0)
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            if not self._schema_ready:
                with self._schema_lock:
                    if not self._schema_ready:
                        connection.execute("PRAGMA journal_mode = WAL")
                        connection.execute(
                            """
                            CREATE TABLE IF NOT EXISTS candle_history (
                                symbol TEXT NOT NULL,
                                timeframe TEXT NOT NULL,
                                open_time_ms INTEGER NOT NULL,
                                open REAL NOT NULL,
                                high REAL NOT NULL,
                                low REAL NOT NULL,
                                close REAL NOT NULL,
                                base_volume REAL NOT NULL,
                                quote_volume REAL NOT NULL,
                                trade_count INTEGER NOT NULL,
                                updated_at_utc TEXT NOT NULL,
                                PRIMARY KEY (symbol, timeframe, open_time_ms)
                            )
                            """
                        )
                        connection.execute(
                            "CREATE INDEX IF NOT EXISTS idx_candle_history_time "
                            "ON candle_history(symbol, timeframe, open_time_ms)"
                        )
                        connection.commit()
                        self._schema_ready = True
        except Exception:
            connection.close()
            raise
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Commit/rollback one operation and always close its SQLite connection."""
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def upsert_bars(self, symbol: str, timeframe: str, bars: Iterable[dict[str, Any]]) -> int:
        """Persist only valid, closed, non-synthetic candles; duplicates update in place."""
        normalized_symbol, timeframe = self._validate_key(symbol, timeframe)
        candidates = [row for row in bars if isinstance(row, dict)]
        usable = valid_bars(candidates, closed_only=True, exclude_synthetic=True)
        records = []
        for row in usable:
            if row.get("closed") is not True or row.get("synthetic", False) is not False:
                continue
            try:
                timestamp = row.get("t")
                trade_count_value = row.get("n", 0)
                if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
                    continue
                if isinstance(trade_count_value, bool):
                    continue
                trade_count_number = float(trade_count_value)
                if not math.isfinite(trade_count_number) or trade_count_number < 0:
                    continue
                if not trade_count_number.is_integer():
                    continue
                values = tuple(float(row[key]) for key in ("o", "h", "l", "c"))
                base_volume = float(row.get("v", 0) or 0)
                quote_volume = float(row.get("q", 0) or 0)
                all_values = (*values, base_volume, quote_volume)
                if not all(math.isfinite(value) for value in all_values):
                    continue
                if min(values) <= 0 or base_volume < 0 or quote_volume < 0:
                    continue
                records.append((
                    normalized_symbol, timeframe, timestamp, *values,
                    base_volume, quote_volume, int(trade_count_number),
                ))
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        if not records:
            return 0

        updated_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT INTO candle_history (
                    symbol, timeframe, open_time_ms, open, high, low, close,
                    base_volume, quote_volume, trade_count, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe, open_time_ms) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    base_volume=excluded.base_volume,
                    quote_volume=excluded.quote_volume,
                    trade_count=excluded.trade_count,
                    updated_at_utc=excluded.updated_at_utc
                """,
                [(*record, updated_at) for record in records],
            )
        return len(records)

    @staticmethod
    def _row_to_bar(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "t": int(row[0]),
            "o": float(row[1]),
            "h": float(row[2]),
            "l": float(row[3]),
            "c": float(row[4]),
            "v": float(row[5]),
            "q": float(row[6]),
            "n": int(row[7]),
            "closed": True,
            "synthetic": False,
        }

    def load_bars(
        self,
        symbol: str,
        timeframe: str,
        *,
        since_ms: int | None = None,
        until_ms: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Load archived closed candles in ascending timestamp order."""
        normalized_symbol, timeframe = self._validate_key(symbol, timeframe)
        if since_ms is not None and (
            isinstance(since_ms, bool) or not isinstance(since_ms, int) or since_ms < 0
        ):
            raise ValueError("since_ms tamsayı milisaniye olmalı.")
        if until_ms is not None and (
            isinstance(until_ms, bool) or not isinstance(until_ms, int) or until_ms < 0
        ):
            raise ValueError("until_ms tamsayı milisaniye olmalı.")
        if since_ms is not None and until_ms is not None and until_ms < since_ms:
            raise ValueError("until_ms, since_ms değerinden küçük olamaz.")
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        ):
            raise ValueError("limit pozitif bir tamsayı olmalı.")
        clauses = ["symbol = ?", "timeframe = ?"]
        params: list[Any] = [normalized_symbol, timeframe]
        if since_ms is not None:
            clauses.append("open_time_ms >= ?")
            params.append(since_ms)
        if until_ms is not None:
            clauses.append("open_time_ms < ?")
            params.append(until_ms)
        sql = (
            "SELECT open_time_ms, open, high, low, close, base_volume, quote_volume, trade_count "
            "FROM candle_history WHERE " + " AND ".join(clauses) + " ORDER BY open_time_ms"
        )
        if limit is not None:
            sql = (
                "SELECT open_time_ms, open, high, low, close, base_volume, quote_volume, trade_count "
                "FROM candle_history WHERE " + " AND ".join(clauses)
                + " ORDER BY open_time_ms DESC LIMIT ?"
            )
            params.append(limit)
        with self._connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        if limit is not None:
            rows.reverse()
        return [self._row_to_bar(row) for row in rows]

    def iter_latest_bars(
        self,
        keys: Iterable[tuple[str, str]],
        *,
        limit: int = 140,
    ) -> Iterator[tuple[tuple[str, str], list[dict[str, Any]]]]:
        """Yield recent history per key through one connection without duplicating all bars in RAM."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit pozitif bir tamsayı olmalı.")
        normalized_keys = list(dict.fromkeys(
            self._validate_key(symbol, timeframe) for symbol, timeframe in keys
        ))
        with self._connection() as connection:
            for symbol, timeframe in normalized_keys:
                rows = connection.execute(
                    """
                    SELECT open_time_ms, open, high, low, close,
                           base_volume, quote_volume, trade_count
                    FROM candle_history
                    WHERE symbol = ? AND timeframe = ?
                    ORDER BY open_time_ms DESC LIMIT ?
                    """,
                    (symbol, timeframe, limit),
                ).fetchall()
                rows.reverse()
                yield ((symbol, timeframe), [
                    self._row_to_bar(row) for row in rows
                ])

    def window_status(
        self,
        symbol: str,
        timeframe: str,
        *,
        since_ms: int,
        until_ms: int,
    ) -> tuple[list[int], int | None]:
        """Return in-window timestamps and the oldest timestamp, using one connection."""
        normalized_symbol, timeframe = self._validate_key(symbol, timeframe)
        for name, value in (("since_ms", since_ms), ("until_ms", until_ms)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} negatif olmayan tamsayı milisaniye olmalı.")
        if until_ms < since_ms:
            raise ValueError("until_ms, since_ms değerinden küçük olamaz.")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT open_time_ms FROM candle_history
                WHERE symbol = ? AND timeframe = ?
                  AND open_time_ms >= ? AND open_time_ms < ?
                ORDER BY open_time_ms
                """,
                (normalized_symbol, timeframe, since_ms, until_ms),
            ).fetchall()
            oldest = connection.execute(
                "SELECT MIN(open_time_ms) FROM candle_history WHERE symbol = ? AND timeframe = ?",
                (normalized_symbol, timeframe),
            ).fetchone()
        return [int(row[0]) for row in rows], (
            int(oldest[0]) if oldest and oldest[0] is not None else None
        )

    def list_timestamps(
        self,
        symbol: str,
        timeframe: str,
        *,
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> list[int]:
        normalized_symbol, timeframe = self._validate_key(symbol, timeframe)
        clauses = ["symbol = ?", "timeframe = ?"]
        params: list[Any] = [normalized_symbol, timeframe]
        if since_ms is not None:
            clauses.append("open_time_ms >= ?")
            params.append(since_ms)
        if until_ms is not None:
            clauses.append("open_time_ms < ?")
            params.append(until_ms)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT open_time_ms FROM candle_history WHERE "
                + " AND ".join(clauses) + " ORDER BY open_time_ms",
                params,
            ).fetchall()
        return [int(row[0]) for row in rows]

    def oldest_timestamp(self, symbol: str, timeframe: str) -> int | None:
        normalized_symbol, timeframe = self._validate_key(symbol, timeframe)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT MIN(open_time_ms) FROM candle_history WHERE symbol = ? AND timeframe = ?",
                (normalized_symbol, timeframe),
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def latest_timestamp(self, symbol: str, timeframe: str) -> int | None:
        normalized_symbol, timeframe = self._validate_key(symbol, timeframe)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT MAX(open_time_ms) FROM candle_history WHERE symbol = ? AND timeframe = ?",
                (normalized_symbol, timeframe),
            ).fetchone()
        return int(row[0]) if row and row[0] is not None else None
