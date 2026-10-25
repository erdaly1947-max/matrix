"""Binance analiz motoru; BtcTurk USDT Spot evrenini ve Binance piyasa verilerini kullanır."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import ssl
import sys
import threading
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import websocket

from ortak_piyasa import (append_universe_snapshot, collect_network_diagnostics,
                          fetch_binance_usdt_spot, fetch_common_usdt_symbols,
                          get_binance_rest_bases, get_binance_ws_bases,
                          load_settings, load_settings_snapshot, public_get)
from tek_motor_evreni import (
    NoActiveCachedIntersectionError, build_single_engine_universe,
)
from radar_core import (APP_VERSION, DATA_DIR, LOG_DIR, RUN_DIR, atomic_json, load_json,
                        normalize_bar, valid_bars, evaluate_binance_candidate, build_trade_plan,
                        score_opportunity, score_btc_market_context,
                        assess_btc_strong_opportunity_gate, setup_logger,
                        stop_requested, utc_now, configure_utf8_console)
from sinyal_kaydi import SignalTracker
from veri_yasam_dongusu import run_storage_maintenance
from binance_mum_arsivi import (
    CandleArchive, current_candle_open_ms, find_missing_ranges,
    history_window_start_ms, next_candle_open_ms,
)

REST_BASES = (
    # Public market-data host first; keep official API hosts as ordered fallbacks.
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
)
WS_BASES = (
    # This scanner consumes public market data only; use Binance's dedicated market-data stream first.
    "wss://data-stream.binance.vision:443/stream?streams=",
    "wss://stream.binance.com:443/stream?streams=",
    "wss://stream.binance.com:9443/stream?streams=",
)
TIMEFRAMES = {
    "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h",
    "4h": "4h", "1d": "1d", "1w": "1w", "1M": "1M",
}
BOOTSTRAP_LIMIT = 90
MIN_STORAGE_MAINTENANCE_INTERVAL_SECONDS = 3600
MAX_STORAGE_MAINTENANCE_INTERVAL_SECONDS = 30 * 24 * 60 * 60


def _storage_maintenance_interval_seconds(
    settings: Any, *, logger: Any | None = None,
) -> int:
    """Return a safe maintenance interval without letting a bad setting interrupt scans."""
    default_seconds = 21600
    if not isinstance(settings, dict) or "storage_maintenance_interval_seconds" not in settings:
        return default_seconds

    raw_value = settings.get("storage_maintenance_interval_seconds")
    try:
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise ValueError("sayısal tam sayı değil")
        numeric_value = float(raw_value)
        if not math.isfinite(numeric_value) or not numeric_value.is_integer():
            raise ValueError("sonlu tam sayı değil")
        if numeric_value > MAX_STORAGE_MAINTENANCE_INTERVAL_SECONDS:
            if logger is not None:
                logger.warning(
                    "storage_maintenance_interval_seconds üst sınırı aşıldı; "
                    "%s saniyeye sınırlandırılacak.",
                    MAX_STORAGE_MAINTENANCE_INTERVAL_SECONDS,
                )
            return MAX_STORAGE_MAINTENANCE_INTERVAL_SECONDS
        return max(MIN_STORAGE_MAINTENANCE_INTERVAL_SECONDS, int(numeric_value))
    except (TypeError, ValueError, OverflowError):
        if logger is not None:
            logger.warning(
                "storage_maintenance_interval_seconds geçersiz; 21600 saniye varsayılanı kullanılacak."
            )
        return default_seconds
DEFAULT_SCAN_SECONDS = 15
DEFAULT_UNIVERSE_REFRESH_SECONDS = 900
DEFAULT_UNIVERSE_RETRY_SECONDS = 10
DEFAULT_BOOTSTRAP_RETRY_SECONDS = 60
MAX_BOOTSTRAP_RETRY_SECONDS = 300
SHARD_SYMBOLS = 20  # Kısa birleşik WS URL'leri ve bağlantı başına yönetilebilir akış sayısı.
REST_MAX_CONCURRENT_REQUESTS = 8
REST_MIN_REQUEST_INTERVAL_SECONDS = 0.075
_active_rest_base: str | None = None
_rest_base_lock = threading.Lock()
_rest_request_semaphore = threading.BoundedSemaphore(REST_MAX_CONCURRENT_REQUESTS)
_rest_rate_lock = threading.Lock()
_last_rest_request_started: float | None = None
_rest_cooldown_until = 0.0


class BinanceRateLimitError(RuntimeError):
    """The API returned an IP-wide 429/418; don\'t immediately retry another hostname."""


def _websocket_age_seconds_by_shard(
    now: float, timestamps: dict[int, float], shard_ids: Any,
) -> dict[str, float | None]:
    """Return non-negative elapsed seconds for each shard, or None until its timestamp exists."""
    ages: dict[str, float | None] = {}
    for shard_id in shard_ids:
        stamp = timestamps.get(shard_id)
        ages[str(shard_id)] = round(max(0.0, now - stamp), 1) if stamp is not None else None
    return ages


def _settings_snapshot_changed(
    loaded: dict[str, Any], current: dict[str, Any]
) -> bool:
    """Detect settings file changes or availability/parse changes since engine start."""
    if not isinstance(loaded, dict) or not isinstance(current, dict):
        return True
    return (
        loaded.get("settings_sha256") != current.get("settings_sha256")
        or loaded.get("settings_parse_status") != current.get("settings_parse_status")
        or loaded.get("settings_file_exists") != current.get("settings_file_exists")
    )


def _age_seconds_from_utc_timestamp(value: Any, *, now: datetime | None = None) -> float | None:
    """Return the age of a saved UTC timestamp; never trust a cached age field."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        return max(0.0, (current - stamp.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _history_bootstrap_is_ready(
    *, done: bool, total: int, completed: int, errors: int, successful: int,
) -> bool:
    """Do not call history ready unless every requested symbol/timeframe has usable data."""
    return bool(done and total > 0 and completed >= total and errors == 0 and successful >= total)


def _is_rest_transport_failure(error: BaseException | str) -> bool:
    """Recognize shared transport failures without treating bad symbols/HTTP 4xx as outages."""
    message = str(error).lower()
    return any(marker in message for marker in (
        "tls wrong_version_number", "wrong version number", "nameresolutionerror",
        "name resolution", "temporary failure in name resolution",
        "failed to establish a new connection", "connection refused",
        "connection reset", "connecttimeout", "readtimeout",
        "max retries exceeded with url",
    ))


def _websocket_streams_have_fresh_data(
    statuses: dict[int, str], last_message: dict[int, float], *,
    now: float, stale_limit: float,
) -> bool:
    """A TCP/WebSocket handshake is not live market data: require a fresh kline on every shard."""
    return bool(statuses) and all(
        status == "BAĞLI"
        and shard_id in last_message
        and 0.0 <= now - last_message[shard_id] <= stale_limit
        for shard_id, status in statuses.items()
    )


def _rate_limited_public_get(
    url: str, *, params: dict[str, Any], timeout: tuple[int, int],
    headers: dict[str, str],
):
    """Bound concurrent kline requests and space request starts across all WS shards."""
    global _last_rest_request_started
    global _rest_cooldown_until
    with _rest_request_semaphore:
        with _rest_rate_lock:
            now = time.monotonic()
            spacing_wait = (
                REST_MIN_REQUEST_INTERVAL_SECONDS - (now - _last_rest_request_started)
                if _last_rest_request_started is not None else 0.0
            )
            cooldown_wait = _rest_cooldown_until - now
            wait = max(0.0, spacing_wait, cooldown_wait)
            if wait > 0:
                time.sleep(wait)
            _last_rest_request_started = time.monotonic()
        try:
            return public_get(url, params=params, timeout=timeout, headers=headers)
        except requests.exceptions.HTTPError as exc:
            response = exc.response
            status_code = getattr(response, "status_code", None)
            if status_code not in (418, 429):
                raise
            header = getattr(response, "headers", {}) or {}
            try:
                retry_after = max(1.0, float(header.get("Retry-After", 0) or 0))
            except (TypeError, ValueError):
                retry_after = 0.0
            if retry_after <= 0:
                retry_after = 60.0 if status_code == 418 else 5.0
            with _rest_rate_lock:
                _rest_cooldown_until = max(
                    _rest_cooldown_until, time.monotonic() + retry_after
                )
            raise BinanceRateLimitError(
                f"Binance HTTP {status_code}; Retry-After={retry_after:g} saniye. "
                "IP tabanlı sınır nedeniyle alternatif hostlar peş peşe denenmeyecek."
            ) from exc


def higher_timeframe_context_rank(row: dict[str, Any]) -> tuple[int, int, int, int]:
    """Rank equal-phase candidates using known 4h/daily direction, not price recency."""
    context = row.get("higher_timeframe_context")
    if not isinstance(context, dict):
        return (0, 0, 0, 0)
    known = []
    for timeframe in ("4h", "1d", "1w", "1M"):
        item = context.get(timeframe)
        if (
            isinstance(item, dict)
            and isinstance(item.get("above_sma20"), bool)
            and isinstance(item.get("last_candle_up"), bool)
        ):
            known.append(item)
    aligned = sum(item["above_sma20"] and item["last_candle_up"] for item in known)
    above_average = sum(item["above_sma20"] for item in known)
    rising_closes = sum(item["last_candle_up"] for item in known)
    return (len(known), aligned, above_average, rising_closes)


CANDIDATE_DECISION_ORDER = {
    "GÜÇLÜ FIRSAT": 6,
    "ERKEN ADAY": 5,
    "KIRILIM BEKLENİYOR": 4,
    "İZLEMEDE": 3,
    "FIRSAT GEÇERSİZ": 2,
    "İŞLEM YOK": 1,
}


def candidate_priority_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """One explicit UI/radar ordering: freshness, class, alarm eligibility, score, phase and context."""
    decision = row.get("final_decision")
    score = row.get("opportunity_score")
    score_value = (
        float(score)
        if isinstance(score, (int, float)) and not isinstance(score, bool)
        and math.isfinite(float(score))
        else -1.0
    )
    phase_order = {"C": 3, "B": 2, "A": 1, None: 0}
    raw_evidence = row.get("evidence_groups")
    evidence_count = len(set(raw_evidence)) if isinstance(raw_evidence, (list, tuple, set)) else 0
    return (
        row.get("data_freshness") == "CANLI AKIŞ GÜNCEL",
        CANDIDATE_DECISION_ORDER.get(decision, 0),
        row.get("strong_alarm_eligible") is True,
        score_value,
        phase_order.get(row.get("phase") or row.get("last_known_phase"), 0),
        higher_timeframe_context_rank(row),
        evidence_count,
    )


def _strict_boolean_flag(container: Any, key: str, *, default: bool = False) -> bool:
    """Read a permission flag only when its value is an actual boolean True."""
    if not isinstance(container, dict):
        return default
    return container.get(key, default) is True


def _strong_alarm_permission(pair_info: Any, *, single_engine: bool) -> bool:
    """Malformed/missing single-engine pair permission fails closed."""
    return _strict_boolean_flag(
        pair_info, "strong_alarm_eligible", default=not single_engine
    )


def _annotate_group_leadership(
    candidates: list[dict[str, Any]],
    settings: dict[str, Any] | None,
) -> dict[str, Any]:
    """Score only explicitly verified category groups with at least three live comparable coins."""
    cfg = settings if isinstance(settings, dict) else {}
    raw_map = cfg.get("coin_group_categories")
    source = cfg.get("coin_group_categories_source")
    mapping_verified = (
        cfg.get("coin_group_categories_verified") is True
        and isinstance(source, str) and bool(source.strip())
        and isinstance(raw_map, dict) and bool(raw_map)
    )
    normalized_map: dict[str, str] = {}
    if mapping_verified:
        for raw_base, raw_category in raw_map.items():
            base = str(raw_base).strip().upper()
            category = str(raw_category).strip() if isinstance(raw_category, str) else ""
            if (
                not base or not base.isalnum() or len(base) > 24
                or not category or len(category) > 80
                or (base in normalized_map and normalized_map[base].casefold() != category.casefold())
            ):
                mapping_verified = False
                normalized_map = {}
                break
            normalized_map[base] = category

    groups: dict[str, list[tuple[dict[str, Any], float]]] = {}
    for row in candidates:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("base_asset") or row.get("symbol") or "").removesuffix("USDT").strip().upper()
        category = normalized_map.get(symbol) if mapping_verified else None
        row.update({
            "group_category": category,
            "group_category_verified": bool(category),
            "group_category_source": str(source).strip() if category else None,
            "group_comparable_count": 0,
            "group_leadership_score": 0,
            "group_leadership_basis": (
                "Güvenilir kategori eşlemesi ayarlarda açıkça doğrulanmadı."
                if not mapping_verified else
                "Aynı grubun güncel 1h BTC göreceli güç verileri bekleniyor."
            ),
            "group_leadership_summary": None,
        })
        if not category:
            continue
        if (
            row.get("btc_market_context_freshness") is not None
            and row.get("btc_market_context_freshness") != "CANLI AKIŞ GÜNCEL"
        ):
            row["group_leadership_basis"] = (
                "BTC canlı bağlamı eski/eksik; grup göreceli gücü hesaplanmadı."
            )
            continue
        if row.get("strong_alarm_eligible") is not True:
            row["group_leadership_basis"] = (
                "Coin güçlü alarm uygunluk filtresinden geçmedi; grup liderliği karşılaştırmasına alınmadı."
            )
            continue
        if row.get("data_freshness") != "CANLI AKIŞ GÜNCEL":
            row["group_leadership_basis"] = (
                "Coinin güncel veri akışı doğrulanmadı; grup liderliği karşılaştırmasına alınmadı."
            )
            continue
        relative = row.get("relative_strength_vs_btc_pct_points")
        value = relative.get("1h") if isinstance(relative, dict) else None
        if (
            isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value))
        ):
            groups.setdefault(category.casefold(), []).append((row, float(value)))

    groups_with_minimum = 0
    comparable_symbols = 0
    for members in groups.values():
        values = sorted(value for _row, value in members)
        count = len(values)
        for row, _value in members:
            row["group_comparable_count"] = count
        if count < 3:
            for row, _value in members:
                row["group_leadership_basis"] = (
                    f"Karşılaştırılabilir güncel coin sayısı {count}; en az 3 gerekli."
                )
            continue

        groups_with_minimum += 1
        comparable_symbols += count
        middle = count // 2
        group_median = (
            values[middle] if count % 2
            else (values[middle - 1] + values[middle]) / 2.0
        )
        best = values[-1]
        best_count = sum(1 for value in values if math.isclose(value, best, rel_tol=0.0, abs_tol=1e-12))
        for row, value in members:
            if value > group_median:
                score = 4 if math.isclose(value, best, rel_tol=0.0, abs_tol=1e-12) and best_count == 1 else 2
            else:
                score = 0
            row["group_leadership_score"] = score
            row["group_leadership_basis"] = (
                "1h mumlarından hesaplanan yaklaşık 24 saatlik BTC göreceli güç farkının "
                f"{count} güncel grup üyesi arasındaki sıralaması; grup medyanı {group_median:+.4f} yüzde puan."
            )
            if score == 4:
                row["group_leadership_summary"] = (
                    f"{row['group_category']} grubunda göreceli performans lideri."
                )
            elif score == 2:
                row["group_leadership_summary"] = (
                    f"{row['group_category']} grubunun medyan performansının üzerinde."
                )
            if row["group_leadership_summary"]:
                findings = row.get("findings")
                note = "Grup liderliği: " + row["group_leadership_summary"]
                if isinstance(findings, list) and note not in findings:
                    findings.append(note)

    return {
        "enabled": bool(mapping_verified),
        "source": str(source).strip() if mapping_verified else None,
        "mapped_asset_count": len(normalized_map) if mapping_verified else 0,
        "groups_with_at_least_three_comparable_coins": groups_with_minimum,
        "comparable_coin_count": comparable_symbols,
        "status": (
            "DOĞRULANMIŞ GRUP EŞLEŞMESİ KULLANILIYOR"
            if mapping_verified else
            "GRUP PUANI KAPALI — AYARLARDA DOĞRULANMIŞ EŞLEŞME YOK"
        ),
    }


def _apply_btc_context_freshness(
    context: dict[str, Any],
    ages_by_timeframe: dict[str, float | None],
    *,
    stale_seconds: float,
) -> tuple[dict[str, Any], bool, str | None]:
    """Prevent stale BTC candles from contributing direction, level or volatility scores."""
    output = dict(context) if isinstance(context, dict) else {}
    output["stream_freshness_by_timeframe"] = {
        timeframe: round(float(age), 1)
        if isinstance(age, (int, float)) and not isinstance(age, bool)
        and math.isfinite(float(age)) and float(age) >= 0
        else None
        for timeframe, age in ages_by_timeframe.items()
    }
    required = ("1h", "4h")
    fresh = (
        isinstance(stale_seconds, (int, float))
        and not isinstance(stale_seconds, bool)
        and math.isfinite(float(stale_seconds))
        and float(stale_seconds) > 0
        and all(
            isinstance(ages_by_timeframe.get(timeframe), (int, float))
            and not isinstance(ages_by_timeframe.get(timeframe), bool)
            and math.isfinite(float(ages_by_timeframe[timeframe]))
            and 0.0 <= float(ages_by_timeframe[timeframe]) <= float(stale_seconds)
            for timeframe in required
        )
    )
    if fresh:
        output["stream_freshness"] = "CANLI AKIŞ GÜNCEL"
        return output, True, None

    warning = (
        "BTC 1h/4h canlı mum akışının güncelliği doğrulanmadı; "
        "BTC yön, seviye ve oynaklık puanları sıfırlandı."
    )
    output.update({
        "direction_score": 0.0,
        "critical_level_score": 0.0,
        "volatility_score": 0.0,
        "total_score": 0.0,
        "bullish_timeframes": 0,
        "support_holding_timeframes": 0,
        "critical_level_loss_timeframes": [],
        "relative_volatility_ratio": None,
        "timeframes": {
            timeframe: {
                "available": False,
                "data_sufficient": False,
                "reason": "BTC canlı mum güncelliği doğrulanmadı; önceki seviyeler güncel kabul edilmiyor.",
                "last_stream_update_age_seconds": output["stream_freshness_by_timeframe"].get(timeframe),
            }
            for timeframe in required
        },
        "risk_warnings": [],
        "data_quality_warnings": list(dict.fromkeys([
            *(
                item for item in output.get("data_quality_warnings", [])
                if isinstance(item, str) and item
            ),
            warning,
        ])),
        "data_completeness": "EKSİK",
        "status": "BTC VERİSİ ESKİ/EKSİK",
        "stream_freshness": "ESKİ/EKSİK",
    })
    return output, False, warning


def _quarantine_btc_relative_metrics(
    candidate: dict[str, Any],
    *,
    reason: str,
) -> None:
    """Stop stale BTC candles from contributing relative-strength/correlation values."""
    candidate["relative_strength_vs_btc_pct_points"] = {
        timeframe: None for timeframe in ("15m", "1h", "4h")
    }
    raw_correlation = candidate.get("btc_return_correlation")
    sanitized_correlation: dict[str, Any] = {}
    if isinstance(raw_correlation, dict):
        for timeframe, row in raw_correlation.items():
            if not isinstance(row, dict):
                sanitized_correlation[str(timeframe)] = {
                    "value": None, "status": "BTC canlı verisi eski/eksik",
                    "current": False, "unavailable_reason": reason,
                }
                continue
            sanitized_correlation[str(timeframe)] = {
                **row,
                "value": None,
                "current": False,
                "status": "BTC canlı verisi eski/eksik",
                "unavailable_reason": reason,
            }
    candidate["btc_return_correlation"] = sanitized_correlation
    findings = candidate.get("findings")
    if isinstance(findings, list):
        candidate["findings"] = [
            item for item in findings
            if not (
                isinstance(item, str)
                and ("göreceli güç pozitif" in item.casefold()
                     or "btc'ye göre" in item.casefold() and "göreceli güç" in item.casefold())
            )
        ]
    missing = candidate.get("missing_checks")
    missing_items = [item for item in missing if isinstance(item, str)] if isinstance(missing, list) else []
    if reason not in missing_items:
        missing_items.append(reason)
    candidate["missing_checks"] = sorted(set(missing_items))


def _btc_candidate_conflict_note(
    candidate: dict[str, Any],
    context: dict[str, Any],
    *,
    context_fresh: bool,
) -> str | None:
    """Describe a positive B/C coin setup that coexists with explicit BTC risk warnings."""
    if not context_fresh or candidate.get("phase") not in ("B", "C"):
        return None
    warnings = context.get("risk_warnings")
    if not isinstance(warnings, list):
        return None
    usable = [item for item in warnings if isinstance(item, str) and item.strip()]
    if not usable:
        return None
    return (
        "Coinin kendi B/C fiyat yapısı mevcut; ancak BTC piyasa bağlamında risk uyarısı var: "
        + "; ".join(usable[:2])
    )


def _build_binance_only_universe(reason: str) -> dict[str, Any]:
    """BtcTurk ortak-parite API'si erişilemiyorsa Binance taramasını çalışır tut."""
    symbols = fetch_binance_usdt_spot()
    settings = load_settings()
    fan_skip = {str(value).upper() for value in settings.get("fan_token_bases_to_skip", [])}
    pairs = []
    for base, item in sorted(symbols.items()):
        if base in fan_skip:
            continue
        pairs.append({
            "base_asset": base,
            "quote_asset": "USDT",
            "binance_symbol": item["symbol"],
            "btcturk_symbol": None,
            "identity_match": "BINANCE_ONLY_NOT_CROSS_CHECKED",
            "category_status": "BtcTurk ortaklığı bu bağlantıda doğrulanamadı",
        })
    if not pairs:
        raise RuntimeError("Binance-only yedek evreni oluşturulamadı; uygun aktif Binance USDT Spot paritesi bulunamadı.")
    short_reason = str(reason)[:500]
    warning = (
        "BtcTurk ortak-parite doğrulaması bu internet bağlantısında alınamadı. "
        "Binance radarı yalnızca Binance'in aktif USDT Spot paritelerini tarıyor; "
        "bu coinlerin BtcTurk'te aktif/ortak olduğu doğrulanmış değildir. "
        f"İlk hata: {short_reason}"
    )
    return {
        "generated_at_utc": utc_now(),
        "source": "Binance Spot exchangeInfo only; BtcTurk validation unavailable",
        "universe_mode": "BINANCE_ONLY_FALLBACK",
        "binance_active_usdt_count": len(symbols),
        "btcturk_active_usdt_count": None,
        "common_pair_count_before_local_exclusions": None,
        "common_pair_count": None,
        "scan_symbol_count": len(pairs),
        "pairs": pairs,
        "warning": warning,
        "fallback_reason": short_reason,
    }


def _get_klines(
    symbol: str,
    interval: str,
    limit: int = BOOTSTRAP_LIMIT,
    *,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
) -> list[dict[str, Any]]:
    """Mumları resmî Binance REST adreslerinden ilk başarılı kaynaktan alır."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("Binance mum limit değeri 1 ile 1000 arasında tamsayı olmalı.")
    if start_time_ms is not None and (
        isinstance(start_time_ms, bool) or not isinstance(start_time_ms, int) or start_time_ms < 0
    ):
        raise ValueError("start_time_ms negatif olmayan tamsayı milisaniye olmalı.")
    if end_time_ms is not None and (
        isinstance(end_time_ms, bool) or not isinstance(end_time_ms, int) or end_time_ms < 0
    ):
        raise ValueError("end_time_ms negatif olmayan tamsayı milisaniye olmalı.")
    if start_time_ms is not None and end_time_ms is not None and end_time_ms < start_time_ms:
        raise ValueError("end_time_ms, start_time_ms değerinden küçük olamaz.")
    params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_time_ms is not None:
        params["startTime"] = start_time_ms
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    global _active_rest_base
    available_bases = get_binance_rest_bases()
    with _rest_base_lock:
        active = _active_rest_base
    bases = (([active] if active in available_bases else []) +
             [base for base in available_bases if base != active])
    errors: list[str] = []
    raw = None
    for base in bases:
        try:
            response = _rate_limited_public_get(
                f"{base}/api/v3/klines",
                params=params,
                timeout=(4, 8),
                headers={"User-Agent": "IkiRadarliSpotTrade/1.1"},
            )
            candidate = response.json()
            if not isinstance(candidate, list):
                raise ValueError("Mum cevabı beklenen liste yapısında değil.")
            raw = candidate
            with _rest_base_lock:
                _active_rest_base = base
            break
        except BinanceRateLimitError as exc:
            errors.append(f"{base}: {exc}")
            # 429/418 IP based: trying api1/api2/etc immediately would bypass no limit.
            break
        except Exception as exc:
            errors.append(f"{base}: {exc}")
    if raw is None:
        raise RuntimeError(f"Binance mum verisi alınamadı ({symbol} {interval}). " + " | ".join(errors[-3:]))
    now_ms = int(time.time() * 1000)
    bars = []
    for k in raw:
        if not isinstance(k, list) or len(k) < 9:
            continue
        bars.append(normalize_bar(k[0], k[1], k[2], k[3], k[4], k[5],
                                  k[7], k[8], closed=int(k[6]) < now_ms))
    return bars


def _get_klines_range(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    *,
    should_stop: Any = None,
) -> list[dict[str, Any]]:
    """Download one bounded historical range in Binance's 1,000-candle pages."""
    if start_ms <= 0 or end_ms < start_ms:
        raise ValueError("Geçersiz Binance mum aralığı.")
    cursor = start_ms
    collected: dict[int, dict[str, Any]] = {}
    # A 30-day window is far below 100 pages even for 5m candles. The upper bound
    # also protects the live motor from an unexpected non-advancing REST response.
    for _page in range(100):
        if cursor >= end_ms or (callable(should_stop) and should_stop()):
            break
        rows = valid_bars(
            _get_klines(
                symbol, interval, limit=1000,
                start_time_ms=cursor, end_time_ms=end_ms - 1,
            ),
            closed_only=False,
        )
        rows = [
            row for row in rows
            if cursor <= int(row["t"]) < end_ms
        ]
        if not rows:
            break
        for row in rows:
            collected[int(row["t"])] = row
        latest_open = max(collected)
        next_cursor = next_candle_open_ms(latest_open, interval)
        if next_cursor <= cursor:
            raise RuntimeError(
                f"Binance tarihsel mum sayfalaması ilerlemedi: {symbol} {interval}."
            )
        cursor = next_cursor
    else:
        raise RuntimeError(
            f"Binance tarihsel mum sayfalaması güvenlik sınırına ulaştı: {symbol} {interval}."
        )
    return [collected[key] for key in sorted(collected)]


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 and math.isfinite(number) else None


def _parse_binance_quote_volumes(
    payload: Any,
    allowed_symbols: set[str],
    *,
    sampled_at_epoch: float,
) -> dict[str, dict[str, Any]]:
    """Parse 24h Binance statistics, keeping only symbols in the verified common universe."""
    if not isinstance(payload, list):
        raise ValueError("Binance 24h ticker yanıtı liste biçiminde değil.")
    output: dict[str, dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol not in allowed_symbols:
            continue
        quote_volume = _finite_positive(row.get("quoteVolume"))
        last_price = _finite_positive(row.get("lastPrice"))
        if quote_volume is None or last_price is None:
            continue
        output[symbol] = {
            "quote_volume_24h": quote_volume,
            "last_price": last_price,
            "quote_volume_timestamp_epoch": float(sampled_at_epoch),
        }
    return output


def _parse_binance_depth_measurement(
    payload: Any,
    *,
    symbol: str,
    sampled_at_epoch: float,
) -> dict[str, Any]:
    """Measure the spread and the USDT depth within 1% of the midpoint."""
    if not isinstance(payload, dict):
        raise ValueError("Binance depth yanıtı nesne biçiminde değil.")
    bids, asks = payload.get("bids"), payload.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
        raise ValueError("Binance depth içinde alış/satış kademesi eksik.")
    valid_bids: list[tuple[float, float]] = []
    valid_asks: list[tuple[float, float]] = []
    for target, rows in ((valid_bids, bids), (valid_asks, asks)):
        for level in rows:
            if not isinstance(level, (list, tuple)) or len(level) < 2:
                continue
            price, quantity = _finite_positive(level[0]), _finite_positive(level[1])
            if price is not None and quantity is not None:
                target.append((price, quantity))
    if not valid_bids or not valid_asks:
        raise ValueError("Binance depth içinde geçerli alış/satış kademesi yok.")
    best_bid = max(price for price, _ in valid_bids)
    best_ask = min(price for price, _ in valid_asks)
    if best_bid >= best_ask:
        raise ValueError("Binance emir defteri çapraz veya kilitli; spread doğrulanamadı.")
    mid = (best_bid + best_ask) / 2.0
    if not math.isfinite(mid) or mid <= 0:
        raise ValueError("Emir defteri orta fiyatı geçersiz.")
    bid_depth = sum(price * qty for price, qty in valid_bids if price >= mid * 0.99)
    ask_depth = sum(price * qty for price, qty in valid_asks if price <= mid * 1.01)
    spread_pct = (best_ask - best_bid) / mid * 100.0
    if not all(math.isfinite(value) and value >= 0 for value in (bid_depth, ask_depth, spread_pct)):
        raise ValueError("Emir defteri derinlik/spread hesabı geçersiz.")
    return {
        "symbol": str(symbol).upper(),
        "timestamp_epoch": float(sampled_at_epoch),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid_price": mid,
        "spread_pct": spread_pct,
        "bid_depth_usdt_1pct": bid_depth,
        "ask_depth_usdt_1pct": ask_depth,
    }


def _assess_liquidity_snapshot(
    market: dict[str, Any] | None,
    samples: list[dict[str, Any]] | None,
    *,
    now_epoch: float,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Separate incomplete measurements (None) from a measured liquidity failure (False)."""
    cfg = settings or {}
    market = market if isinstance(market, dict) else {}
    samples = samples if isinstance(samples, list) else []
    volume_min = max(0.0, float(cfg.get("liquidity_min_quote_volume_24h", 1_000_000)))
    max_spread = max(0.0, float(cfg.get("liquidity_max_spread_pct", 0.25)))
    min_depth = max(0.0, float(cfg.get("liquidity_min_depth_usdt_1pct", 10_000)))
    volume_max_age = max(30.0, float(cfg.get("liquidity_quote_volume_fresh_seconds", 180)))
    sample_max_age = max(30.0, float(cfg.get("liquidity_sample_fresh_seconds", 45)))
    sample_window = max(sample_max_age, float(cfg.get("liquidity_sample_window_seconds", 75)))
    required_samples = max(3, int(cfg.get("liquidity_min_depth_samples", 3)))
    minimum_span = max(30.0, float(cfg.get("liquidity_min_sample_span_seconds", 30)))
    failures: list[str] = []
    hard_failures: list[str] = []

    quote_volume = _finite_positive(market.get("quote_volume_24h"))
    volume_stamp = market.get("quote_volume_timestamp_epoch")
    volume_age = (
        float(now_epoch) - float(volume_stamp)
        if isinstance(volume_stamp, (int, float)) and math.isfinite(float(volume_stamp))
        else None
    )
    quote_volume_quality_passed = bool(
        quote_volume is not None
        and volume_age is not None
        and 0.0 <= volume_age <= volume_max_age
        and quote_volume >= volume_min
    )
    if quote_volume is None:
        failures.append("24 saatlik Binance USDT hacmi alınamadı.")
    elif volume_age is None or volume_age < 0 or volume_age > volume_max_age:
        failures.append("24 saatlik hacim verisi eski veya zamanı doğrulanamadı.")
    elif quote_volume < volume_min:
        reason = f"24 saatlik USDT hacmi {volume_min:,.0f} USDT eşiğinin altında."
        failures.append(reason)
        hard_failures.append(reason)

    good_samples = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        stamp = sample.get("timestamp_epoch")
        if not isinstance(stamp, (int, float)) or not math.isfinite(float(stamp)):
            continue
        age = float(now_epoch) - float(stamp)
        if age < 0 or age > sample_window:
            continue
        spread = sample.get("spread_pct")
        bid_depth = sample.get("bid_depth_usdt_1pct")
        ask_depth = sample.get("ask_depth_usdt_1pct")
        if not all(
            isinstance(value, (int, float)) and math.isfinite(float(value))
            for value in (spread, bid_depth, ask_depth)
        ):
            continue
        if min(float(spread), float(bid_depth), float(ask_depth)) < 0:
            continue
        good_samples.append({
            "timestamp_epoch": float(stamp), "age_seconds": age,
            "spread_pct": float(spread),
            "bid_depth_usdt_1pct": float(bid_depth),
            "ask_depth_usdt_1pct": float(ask_depth),
        })
    good_samples.sort(key=lambda sample: sample["timestamp_epoch"])
    if good_samples and good_samples[-1]["age_seconds"] > sample_max_age:
        failures.append("En son emir defteri ölçümü güncel değil.")
    if len(good_samples) < required_samples:
        failures.append(
            f"Likidite kararlılığı için {required_samples} taze emir defteri ölçümü gerekiyor."
        )
    else:
        selected = good_samples[-required_samples:]
        span = selected[-1]["timestamp_epoch"] - selected[0]["timestamp_epoch"]
        latest_age = selected[-1]["age_seconds"]
        if span < minimum_span:
            failures.append(
                f"Emir defteri ölçümleri en az {minimum_span:.0f} saniyeye yayılmalı."
            )
        if latest_age > sample_max_age:
            failures.append("En son emir defteri ölçümü güncel değil.")
        if any(sample["spread_pct"] > max_spread for sample in selected):
            reason = f"Spread ölçümlerinden biri %{max_spread:g} eşiğini aşıyor."
            failures.append(reason)
            hard_failures.append(reason)
        if any(
            sample["bid_depth_usdt_1pct"] < min_depth
            or sample["ask_depth_usdt_1pct"] < min_depth
            for sample in selected
        ):
            reason = f"Alış/satış derinliği ölçümlerinden biri {min_depth:,.0f} USDT altında."
            failures.append(reason)
            hard_failures.append(reason)

        spreads = [sample["spread_pct"] for sample in selected]
        spread_median = sorted(spreads)[len(spreads) // 2]
        if max(spreads) - min(spreads) > max(0.05, spread_median * 0.5):
            reason = "Spread ölçümleri birbirleriyle yeterince tutarlı değil."
            failures.append(reason)
            hard_failures.append(reason)
        for field in ("bid_depth_usdt_1pct", "ask_depth_usdt_1pct"):
            depths = [sample[field] for sample in selected]
            if max(depths) > max(min_depth, min(depths)) * 3.0:
                reason = "Emir defteri derinliği ölçümleri yeterince tutarlı değil."
                failures.append(reason)
                hard_failures.append(reason)
                break

    # Puan only comes from independently valid evidence. A stale volume figure or
    # an incomplete order-book sample series must not earn liquidity points.
    spread_quality_passed = False
    depth_quality_passed = False
    if len(good_samples) >= required_samples:
        quality_samples = good_samples[-required_samples:]
        quality_span = quality_samples[-1]["timestamp_epoch"] - quality_samples[0]["timestamp_epoch"]
        quality_latest_age = quality_samples[-1]["age_seconds"]
        sample_series_fresh = quality_span >= minimum_span and quality_latest_age <= sample_max_age
        if sample_series_fresh:
            spreads = [sample["spread_pct"] for sample in quality_samples]
            spread_median = sorted(spreads)[len(spreads) // 2]
            spread_quality_passed = (
                all(value <= max_spread for value in spreads)
                and max(spreads) - min(spreads) <= max(0.05, spread_median * 0.5)
            )
            depth_quality_passed = all(
                sample["bid_depth_usdt_1pct"] >= min_depth
                and sample["ask_depth_usdt_1pct"] >= min_depth
                for sample in quality_samples
            )
            for field in ("bid_depth_usdt_1pct", "ask_depth_usdt_1pct"):
                depths = [sample[field] for sample in quality_samples]
                if max(depths) > max(min_depth, min(depths)) * 3.0:
                    depth_quality_passed = False
                    break

    latest_sample = good_samples[-1] if good_samples else {}
    if not failures:
        passed: bool | None = True
    elif hard_failures:
        passed = False
    else:
        passed = None
    return {
        "passed": passed,
        "status": "DOĞRULANDI" if passed is True else "EŞİK BAŞARISIZ" if passed is False else "ÖLÇÜM BEKLENİYOR",
        "quote_volume_quality_passed": quote_volume_quality_passed,
        "spread_quality_passed": spread_quality_passed,
        "depth_quality_passed": depth_quality_passed,
        "quote_volume_24h": quote_volume,
        "quote_volume_age_seconds": round(volume_age, 1) if volume_age is not None else None,
        "spread_pct": latest_sample.get("spread_pct"),
        "bid_depth_usdt_1pct": latest_sample.get("bid_depth_usdt_1pct"),
        "ask_depth_usdt_1pct": latest_sample.get("ask_depth_usdt_1pct"),
        "liquidity_sample_count": len(good_samples),
        "liquidity_sample_span_seconds": (
            round(good_samples[-1]["timestamp_epoch"] - good_samples[0]["timestamp_epoch"], 1)
            if len(good_samples) >= 2 else 0.0
        ),
        "liquidity_sample_age_seconds": (
            round(latest_sample["age_seconds"], 1) if latest_sample else None
        ),
        "failed_gates": list(dict.fromkeys(failures)),
        "sampled_at_epoch": latest_sample.get("timestamp_epoch"),
    }



class BinanceRadar:
    def __init__(self, stop_file: str, *, single_engine: bool = False):
        self.stop_file = Path(stop_file)
        self.single_engine = bool(single_engine)
        self._storage_maintenance_lock = threading.Lock()
        self._storage_maintenance_running = False
        self.logger = setup_logger("binance_radar", LOG_DIR / "binance_radar.log")
        self.network_diagnostics = collect_network_diagnostics()
        self.logger.info(
            "Ağ çalışma ortamı: Python=%s; OpenSSL=%s; HTTPS proxy/TLS tanısı=%s",
            sys.version.split()[0], ssl.OPENSSL_VERSION,
            json.dumps(self.network_diagnostics, ensure_ascii=False, sort_keys=True),
        )
        self.lock = threading.RLock()
        self.universe: dict[str, Any] = {}
        self.bars: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self.candle_archive = CandleArchive(DATA_DIR / "binance_ohlcv_history.sqlite3")
        self._history_storage_warnings: list[str] = []
        self.ws_apps: list[websocket.WebSocketApp] = []
        self.ws_apps_by_shard: dict[int, websocket.WebSocketApp] = {}
        self.ws_status: dict[int, str] = {}
        self.connected_at_by_shard: dict[int, float] = {}
        self.last_message: dict[int, float] = {}
        self.kline_message_count_by_shard: dict[int, int] = {}
        self.ever_connected_shards: set[int] = set()
        self.last_heartbeat_log = 0.0
        self.last_rest_refresh = 0.0
        self.last_history_write = 0.0
        self.bootstrap_total = 0
        self.bootstrap_completed = 0
        self.bootstrap_error_count = 0
        self.bootstrap_success_count = 0
        self.bootstrap_skipped_count = 0
        self.bootstrap_retry_attempts = 0
        self.bootstrap_retry_at = 0.0
        self.bootstrap_retry_seconds = 0
        self.bootstrap_done = threading.Event()
        self.bootstrap_done.set()
        self.bootstrap_thread: threading.Thread | None = None
        self.settings, self.settings_snapshot = load_settings_snapshot()
        self.audit_interval_seconds = max(60, int(self.settings.get("candidate_audit_seconds", 300)))
        self.api_warnings: list[str] = []
        self.last_symbol_update: dict[tuple[str, str], float] = {}
        self.last_symbol_event_ms: dict[tuple[str, str], int] = {}
        self.ws_threads: list[threading.Thread] = []
        self.rebuild_event = threading.Event()
        self.scan_seconds = max(5, int(self.settings.get("scan_refresh_seconds", DEFAULT_SCAN_SECONDS)))
        self.universe_refresh_seconds = max(60, int(self.settings.get("universe_refresh_seconds", DEFAULT_UNIVERSE_REFRESH_SECONDS)))
        self.signal_tracker = SignalTracker(
            self.settings.get("signal_inactive_after_missing_cycles", 3),
            self.settings.get("signal_snapshot_seconds", 60))
        self._liquidity_market_cache: dict[str, dict[str, Any]] = {}
        self._liquidity_depth_samples: dict[str, list[dict[str, Any]]] = {}
        self._liquidity_last_depth_request: dict[str, float] = {}

    def _get_liquidity_json(self, path: str, *, params: dict[str, Any]) -> Any:
        errors: list[str] = []
        for base in get_binance_rest_bases():
            try:
                response = _rate_limited_public_get(
                    f"{base}{path}", params=params, timeout=(4, 8),
                    headers={"User-Agent": "IkiRadarliSpotTrade/1.1"},
                )
                return response.json()
            except BinanceRateLimitError:
                raise
            except Exception as exc:
                errors.append(f"{base}: {type(exc).__name__}: {exc}")
        raise RuntimeError(
            f"Binance likidite uç noktası yanıt vermedi ({path}). " + " | ".join(errors[-3:])
        )

    def _refresh_candidate_liquidity(
        self, candidates: list[dict[str, Any]], *, now_epoch: float,
    ) -> None:
        """Measure liquidity for the strongest fresh B/C candidates within a bounded REST budget."""
        if not getattr(self, "single_engine", False):
            return
        config = self.settings if isinstance(getattr(self, "settings", None), dict) else {}
        if not isinstance(getattr(self, "_liquidity_market_cache", None), dict):
            self._liquidity_market_cache = {}
        if not isinstance(getattr(self, "_liquidity_depth_samples", None), dict):
            self._liquidity_depth_samples = {}
        if not isinstance(getattr(self, "_liquidity_last_depth_request", None), dict):
            self._liquidity_last_depth_request = {}
        if not isinstance(getattr(self, "api_warnings", None), list):
            self.api_warnings = []
        if getattr(self, "logger", None) is None:
            self.logger = setup_logger("binance_radar", LOG_DIR / "binance_radar.log")
        depth_limit = max(1, min(10, int(config.get("liquidity_depth_candidate_limit", 5))))
        depth_refresh = max(10.0, float(config.get("liquidity_depth_refresh_seconds", 15)))
        sample_window = max(45.0, float(config.get("liquidity_sample_window_seconds", 75)))
        ranked = [
            row for row in candidates
            if row.get("phase") in ("B", "C")
            and row.get("data_freshness") == "CANLI AKIŞ GÜNCEL"
            and row.get("strong_alarm_eligible") is True
            and str(row.get("symbol") or "").strip().upper().endswith("USDT")
        ]
        ranked.sort(
            key=lambda row: (
                float(row.get("opportunity_score", 0) or 0),
                {"C": 2, "B": 1}.get(row.get("phase"), 0),
            ),
            reverse=True,
        )
        selected = ranked[:depth_limit]
        selected_symbols = {
            str(row.get("symbol") or "").strip().upper() for row in selected
        }
        if not selected_symbols:
            return

        symbols_needing_volume = []
        max_quote_age = max(30.0, float(config.get("liquidity_quote_volume_refresh_seconds", 60)))
        for symbol in sorted(selected_symbols):
            cached = self._liquidity_market_cache.get(symbol, {})
            stamp = cached.get("quote_volume_timestamp_epoch")
            age = now_epoch - float(stamp) if isinstance(stamp, (int, float)) else float("inf")
            if age < 0 or age > max_quote_age or _finite_positive(cached.get("quote_volume_24h")) is None:
                symbols_needing_volume.append(symbol)

        if symbols_needing_volume:
            try:
                payload = self._get_liquidity_json(
                    "/api/v3/ticker/24hr",
                    params={"symbols": json.dumps(symbols_needing_volume, separators=(",", ":"))},
                )
                observations = _parse_binance_quote_volumes(
                    payload, set(symbols_needing_volume), sampled_at_epoch=time.time()
                )
                self._liquidity_market_cache.update(observations)
                missing = set(symbols_needing_volume) - set(observations)
                for symbol in sorted(missing):
                    self.logger.warning(
                        "Likidite 24h istatistiği kullanılabilir değil: %s; güçlü fırsat kapısı kapalı.",
                        symbol,
                    )
            except Exception as exc:
                warning = f"Binance 24h likidite istatistiği alınamadı: {type(exc).__name__}: {exc}"
                if warning not in self.api_warnings:
                    self.api_warnings.append(warning)
                self.logger.warning("%s", warning)

        for row in selected:
            symbol = str(row.get("symbol") or "").strip().upper()
            last_request = self._liquidity_last_depth_request.get(symbol, 0.0)
            if now_epoch - last_request < depth_refresh:
                continue
            self._liquidity_last_depth_request[symbol] = now_epoch
            try:
                payload = self._get_liquidity_json(
                    "/api/v3/depth", params={"symbol": symbol, "limit": 100}
                )
                sample = _parse_binance_depth_measurement(
                    payload, symbol=symbol, sampled_at_epoch=time.time()
                )
                history = self._liquidity_depth_samples.setdefault(symbol, [])
                if not history or sample["timestamp_epoch"] > history[-1]["timestamp_epoch"]:
                    history.append(sample)
                history[:] = [
                    item for item in history
                    if 0 <= time.time() - float(item.get("timestamp_epoch", 0)) <= sample_window
                ][-8:]
            except Exception as exc:
                warning = f"{symbol} için güncel Binance emir defteri ölçümü alınamadı: {type(exc).__name__}: {exc}"
                if warning not in self.api_warnings:
                    self.api_warnings.append(warning)
                self.logger.warning("%s", warning)

        for row in selected:
            symbol = str(row.get("symbol") or "").strip().upper()
            market = self._liquidity_market_cache.get(symbol)
            samples = self._liquidity_depth_samples.get(symbol, [])
            assessment = _assess_liquidity_snapshot(
                market, samples, now_epoch=time.time(), settings=config
            )
            assessment["failed_gates"] = list(assessment.get("failed_gates", []))
            if len(samples) == 0:
                assessment["failed_gates"].append("Henüz geçerli Binance emir defteri ölçümü yok.")
            row["liquidity_assessment"] = assessment

    def refresh_universe(self) -> bool:
        # Throttle failed refreshes too; do not retry on every ordinary scan cycle.
        self.last_rest_refresh = time.time()
        cache_path = DATA_DIR / "common_universe.json"
        if getattr(self, "single_engine", False):
            # BtcTurk listesi yalnızca kullanıcı paneldeki düğmeyle istediğinde güncellenir.
            # Normal başlangıç ve evren yenilemesi kayıtlı listeyi ağ erişimi olmadan okur.
            try:
                new_universe = build_single_engine_universe(
                    settings=getattr(self, "settings", None)
                )
            except Exception as build_error:
                if isinstance(build_error, NoActiveCachedIntersectionError):
                    # A live Binance listing proved that every cached common pair is gone.
                    # Never reinstate the previous in-memory pair list in this specific case.
                    fallback_reason = str(build_error)[:700]
                    new_universe = {
                        "generated_at_utc": utc_now(),
                        "source": "Binance Spot güncel aktif USDT listesi; eski ortak evrende aktif parite kalmadı",
                        "universe_mode": "NO_ACTIVE_CACHED_INTERSECTION",
                        "binance_universe_source_verified": True,
                        "local_list_generated_at_utc": None,
                        "local_list_age_seconds": None,
                        "local_list_source": None,
                        "local_list_legacy": False,
                        "btcturk_universe_mode": "LOCAL_LIST_UNAVAILABLE",
                        "btcturk_universe_generated_at_utc": None,
                        "btcturk_universe_age_seconds": None,
                        "btcturk_list_active_status_verified": False,
                        "strong_alerts_enabled": False,
                        "alert_filter_warning": fallback_reason,
                        "common_pair_count": 0,
                        "scan_symbol_count": 0,
                        "pairs": [],
                        "fallback_reason": fallback_reason,
                        "btcturk_universe_warning": fallback_reason,
                        "warning": fallback_reason,
                    }
                    self.logger.error(
                        "Güncel Binance listesinde kayıtlı ortak evrenden aktif parite kalmadı; "
                        "eski bellek evreni kullanıma kapatıldı: %s", fallback_reason,
                    )
                else:
                    previous = getattr(self, "universe", {})
                    previous_pairs = previous.get("pairs", []) if isinstance(previous, dict) else []
                    if isinstance(previous_pairs, list) and previous_pairs:
                        new_universe = dict(previous)
                        fallback_reason = str(build_error)
                        fallback_warning = (
                            "Yeni tarama evreni kayıtlı veriden hazırlanamadı; Binance motoru "
                            "bellekteki son geçerli evreni kullanmaya devam ediyor. "
                            f"Son hata: {fallback_reason[:400]}"
                        )
                        new_universe["universe_mode"] = "CACHED_LAST_GOOD_UNIVERSE"
                        new_universe["btcturk_universe_mode"] = "CACHED_LAST_SUCCESS"
                        new_universe["fallback_reason"] = fallback_reason[:500]
                        new_universe["btcturk_universe_warning"] = fallback_warning
                        old_warning = str(new_universe.get("warning") or "").strip()
                        new_universe["warning"] = f"{old_warning} {fallback_warning}".strip()
                        self.logger.warning("%s", fallback_warning)
                    else:
                        details = (
                            "Tarama evreni hazırlanamadı; tek motor, yerel BtcTurk USDT "
                            "listesi ile güncel Binance Spot USDT listesinin ortak paritelerini "
                            "gerektirir. Aşağıdaki ayrıntı, hangi kaynağın başarısız olduğunu "
                            "belirtir. Başlangıçta BtcTurk API'sine otomatik istek gönderilmedi. "
                            f"Evren kurulum hatası: {build_error}."
                        )
                        raise RuntimeError(details) from build_error
            if new_universe.get("local_list_legacy") is True:
                # Eski common_universe kaydı güncel BtcTurk aktiflik kanıtı değildir.
                new_universe["btcturk_universe_mode"] = "LEGACY_COMMON_CACHE"
        else:
            try:
                new_universe = fetch_common_usdt_symbols()
                new_universe.setdefault("universe_mode", "COMMON_VERIFIED")
                new_universe["scan_symbol_count"] = len(new_universe.get("pairs", []))
            except Exception as common_error:
                # A fresh extraction has no cache; an existing cache may contain the last
                # successfully cross-checked list. Preserve it, but label it as historical.
                cached = load_json(cache_path, {}) or {}
                cached_pairs = cached.get("pairs", []) if isinstance(cached, dict) else []
                cached_mode = cached.get("universe_mode", "COMMON_VERIFIED") if isinstance(cached, dict) else ""
                if (isinstance(cached_pairs, list) and cached_pairs
                        and cached_mode == "COMMON_VERIFIED"):
                    new_universe = dict(cached)
                    new_universe["universe_mode"] = "CACHED_COMMON_FALLBACK"
                    new_universe["scan_symbol_count"] = len(cached_pairs)
                    new_universe["fallback_reason"] = str(common_error)[:500]
                    old_warning = str(new_universe.get("warning") or "").strip()
                    fallback_warning = (
                        "BtcTurk ortak-parite API'sine şu anda erişilemedi. Binance taraması "
                        "son başarıyla doğrulanmış ortak listeyle sürüyor; BtcTurk eşleşmesi güncel değil."
                    )
                    new_universe["warning"] = f"{old_warning} | {fallback_warning}".strip(" |")
                    self.logger.warning("%s Son doğrulanmış ortak liste yedek olarak kullanılacak: %s parite.",
                                        fallback_warning, len(cached_pairs))
                else:
                    new_universe = _build_binance_only_universe(str(common_error))
                    self.logger.warning(
                        "BtcTurk ortak-parite doğrulaması alınamadı; Binance radarı Binance-only yedek evrenle çalışıyor. "
                        "BtcTurk eşleşmesi doğrulanmış sayılmayacak. Sebep: %s",
                        str(common_error)[:500],
                    )

        mode = new_universe.get("universe_mode", "COMMON_VERIFIED")
        with self.lock:
            old_symbols = {p["binance_symbol"] for p in self.universe.get("pairs", [])}
            old_mode = self.universe.get("universe_mode") if self.universe else None
            new_symbols = {p["binance_symbol"] for p in new_universe.get("pairs", [])}
            changed = old_symbols != new_symbols or (old_mode is not None and old_mode != mode)
            self.universe = new_universe
            for sym in new_symbols:
                self.bars.setdefault(sym, {tf: [] for tf in TIMEFRAMES})
            self.last_rest_refresh = time.time()

        # Tek motorun doğrulanmış ortak evren önbelleği build_single_engine_universe içinde yönetilir.
        if mode == "COMMON_VERIFIED":
            atomic_json(cache_path, new_universe)
            self.logger.info("Doğrulanmış ortak evren yenilendi: %s parite; yeni=%s, çıkan=%s",
                             len(new_symbols), len(new_symbols - old_symbols), len(old_symbols - new_symbols))
        elif mode == "SINGLE_ENGINE_LOCAL_LIST":
            self.logger.info(
                "Tek motor evreni hazır: Binance canlı parite listesi + yerel BtcTurk sembol listesi; "
                "ortak=%s, yerel liste zamanı=%s, yerel liste yaşı=%ss.",
                len(new_symbols), new_universe.get("local_list_generated_at_utc"),
                new_universe.get("local_list_age_seconds"))
            if new_universe.get("warning"):
                self.logger.warning("%s", new_universe["warning"])
        elif mode == "CACHED_LAST_VERIFIED_COMMON_UNIVERSE":
            self.logger.warning(
                "Son doğrulanmış Binance/BtcTurk ortak evren önbelleği yedek kullanılıyor. "
                "Önbellek kayıt zamanı=%s, kayıtlı_yaş_saniye=%s, tarama_paritesi=%s. "
                "Güçlü fırsat alarmları kapalı. Uyarı=%s",
                new_universe.get("single_engine_universe_cache_generated_at_utc"),
                new_universe.get("single_engine_universe_cache_age_seconds"),
                len(new_symbols), new_universe.get("warning"))
        elif mode in ("CACHED_BTCTURK_FALLBACK", "CACHED_LAST_GOOD_UNIVERSE", "CACHED_LEGACY_UNIVERSE", "CACHED_BINANCE_SYMBOL_FALLBACK"):
            self.logger.warning(
                "Son geçerli tarama evreni yedek olarak kullanılıyor. BtcTurk kayıt zamanı=%s, yaş_saniye=%s, "
                "tarama_paritesi=%s, mod=%s.",
                new_universe.get("btcturk_universe_generated_at_utc"),
                new_universe.get("btcturk_universe_age_seconds"), len(new_symbols), mode)
        else:
            self.logger.info("Tarama evreni: mod=%s, Binance paritesi=%s; BtcTurk ortaklığı güncel doğrulanmadı.",
                             mode, len(new_symbols))

        snapshot_modes = {
            "COMMON_VERIFIED",
            "SINGLE_ENGINE_LOCAL_LIST",
            "CACHED_LAST_VERIFIED_COMMON_UNIVERSE",
            "CACHED_BTCTURK_FALLBACK",
            "CACHED_LAST_GOOD_UNIVERSE",
            "CACHED_LEGACY_UNIVERSE",
            "CACHED_BINANCE_SYMBOL_FALLBACK",
            "CACHED_COMMON_FALLBACK",
        }
        if mode in snapshot_modes and new_symbols:
            source_parts = [f"motor evren snapshot; mode={mode}"]
            source_timestamp = (
                new_universe.get("btcturk_universe_generated_at_utc")
                or new_universe.get("local_list_generated_at_utc")
            )
            source_age = (
                new_universe.get("btcturk_universe_age_seconds")
                if new_universe.get("btcturk_universe_age_seconds") is not None
                else new_universe.get("local_list_age_seconds")
            )
            if source_timestamp:
                source_parts.append(f"BtcTurk liste zamanı={source_timestamp}")
            if source_age is not None:
                source_parts.append(f"BtcTurk liste yaşı saniye={source_age}")
            warning = str(new_universe.get("warning") or "").strip()
            if warning:
                source_parts.append(f"uyarı={warning[:250]}")
            observed_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            try:
                append_universe_snapshot(
                    new_universe,
                    "; ".join(source_parts),
                    observed_at_utc=observed_at,
                )
            except Exception as archive_error:
                # Historical logging must never interrupt a valid live scan.
                self.logger.warning(
                    "Parite evreni kullanılmaya devam ediyor; tarihsel snapshot yazılamadı: %s: %s",
                    type(archive_error).__name__, str(archive_error)[:300],
                )
        return changed

    def _schedule_bootstrap_retry(self, *, success: bool) -> int:
        """Retry incomplete REST history with bounded exponential backoff (kademeli bekleme)."""
        if success:
            self.bootstrap_retry_attempts = 0
            self.bootstrap_retry_at = 0.0
            self.bootstrap_retry_seconds = 0
            return 0
        attempts = int(getattr(self, "bootstrap_retry_attempts", 0)) + 1
        settings = getattr(self, "settings", {})
        base_seconds = max(15, int(settings.get("bootstrap_retry_seconds", DEFAULT_BOOTSTRAP_RETRY_SECONDS)))
        max_seconds = max(base_seconds, int(settings.get(
            "bootstrap_retry_max_seconds", MAX_BOOTSTRAP_RETRY_SECONDS
        )))
        delay = min(max_seconds, base_seconds * (2 ** min(attempts - 1, 4)))
        self.bootstrap_retry_attempts = attempts
        self.bootstrap_retry_seconds = int(delay)
        self.bootstrap_retry_at = time.monotonic() + delay
        return int(delay)

    def _history_storage_warning(self, message: str) -> None:
        warnings = getattr(self, "_history_storage_warnings", None)
        if not isinstance(warnings, list):
            warnings = []
            self._history_storage_warnings = warnings
        if message in warnings:
            return
        warnings.append(message)
        logger = getattr(self, "logger", None)
        if logger is not None:
            logger.warning("Kalıcı mum arşivi uyarısı: %s", message)

    def _merge_bar_series(
        self, symbol: str, timeframe: str, rows: list[dict[str, Any]],
    ) -> None:
        """Merge by candle-open time, preserving newer live values and the 140-bar RAM cap."""
        if not rows:
            return
        with self.lock:
            series = self.bars.setdefault(symbol, {key: [] for key in TIMEFRAMES})
            existing = series.setdefault(timeframe, [])
            by_time = {
                int(row["t"]): row for row in existing
                if isinstance(row, dict) and isinstance(row.get("t"), int)
                and not isinstance(row.get("t"), bool)
            }
            for row in rows:
                if not isinstance(row, dict) or isinstance(row.get("t"), bool):
                    continue
                try:
                    timestamp = int(row["t"])
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                previous = by_time.get(timestamp)
                if previous is None or (
                    row.get("closed") is True and previous.get("closed") is not True
                ):
                    by_time[timestamp] = row
            series[timeframe] = [by_time[key] for key in sorted(by_time)][-140:]

    def _load_repair_history(
        self, symbol: str, timeframe: str, interval: str,
    ) -> list[dict[str, Any]]:
        """Load the archive, repair the latest 30-day window, and return recent bars."""
        archive = getattr(self, "candle_archive", None)
        if archive is None:
            # Compatibility path for narrow, isolated legacy callers; production
            # BinanceRadar instances always receive the persistent archive in __init__.
            rows = valid_bars(_get_klines(symbol, interval), closed_only=False)
            if not rows:
                raise RuntimeError(
                    f"Binance {symbol} {interval}: geçerli geçmiş mum bulunamadı."
                )
            return rows

        now_ms = int(time.time() * 1000)
        start_ms = history_window_start_ms(timeframe, now_ms=now_ms)
        end_ms = current_candle_open_ms(timeframe, now_ms=now_ms)
        if end_ms <= start_ms:
            raise RuntimeError(f"{symbol} {interval}: geçmiş mum aralığı boş veya ters.")

        try:
            timestamps, oldest_overall = archive.window_status(
                symbol, timeframe, since_ms=start_ms, until_ms=end_ms,
            )
            # Repair a leading hole too. If a symbol was listed later than the
            # window start, Binance simply returns no candles for that prefix;
            # verification below distinguishes this from a missing middle range.
            fill_prefix = True
            missing_ranges = find_missing_ranges(
                timestamps, timeframe, start_ms, end_ms, fill_prefix=fill_prefix,
            )
        except Exception as exc:
            timestamps = []
            oldest_overall = None
            fill_prefix = False
            missing_ranges = [(start_ms, end_ms)]
            self._history_storage_warning(
                f"Arşiv okunamadı ({type(exc).__name__}); Binance verisiyle yeniden oluşturma denenecek."
            )

        fetched: list[dict[str, Any]] = []
        for gap_start, gap_end in missing_ranges:
            if stop_requested(self.stop_file) or getattr(self, "rebuild_event", threading.Event()).is_set():
                break
            fetched.extend(_get_klines_range(
                symbol, interval, gap_start, gap_end,
                should_stop=lambda: (
                    stop_requested(self.stop_file)
                    or getattr(self, "rebuild_event", threading.Event()).is_set()
                ),
            ))

        archive_writable = True
        try:
            if fetched:
                archive.upsert_bars(symbol, timeframe, fetched)
                self.last_history_write = time.time()
        except Exception as exc:
            archive_writable = False
            self._history_storage_warning(
                f"Arşive yazılamadı ({type(exc).__name__}); canlı tarama korunuyor, veri sonraki açılışta yeniden alınacak."
            )

        recent_archive: list[dict[str, Any]] = []
        try:
            recent_archive = archive.load_bars(symbol, timeframe, limit=140)
        except Exception as exc:
            self._history_storage_warning(
                f"Arşiv yeniden okunamadı ({type(exc).__name__}); mevcut REST verisi bellekte kullanılacak."
            )

        if not archive_writable:
            # Cached bars are still available in memory, but persistence failure must
            # not be counted as successful historical preparation for strong alerts.
            raise RuntimeError(
                f"{symbol} {interval}: kapanmış mumlar kalıcı arşive yazılamadı; "
                "geçmiş hazırlığı başarılı sayılmayacak."
            )

        if archive_writable and missing_ranges:
            # The first status check is sufficient when no repair was needed;
            # verify the archive again only after a non-empty repair window.
            try:
                current_timestamps, current_oldest = archive.window_status(
                    symbol, timeframe, since_ms=start_ms, until_ms=end_ms,
                )
                remaining = find_missing_ranges(
                    current_timestamps,
                    timeframe,
                    start_ms,
                    end_ms,
                    fill_prefix=current_oldest is not None and current_oldest < start_ms,
                )
                if remaining:
                    first_start, first_end = remaining[0]
                    raise RuntimeError(
                        f"{symbol} {interval}: Binance'ten tamamlanamayan mum aralığı var "
                        f"({len(remaining)} boşluk; ilk aralık {first_start}–{first_end} ms)."
                    )
            except RuntimeError:
                raise
            except Exception as exc:
                self._history_storage_warning(
                    f"Arşiv bütünlük/boşluk denetimi yapılamadı ({type(exc).__name__}); REST verisi korunuyor."
                )

        merged = {int(row["t"]): row for row in recent_archive if isinstance(row, dict) and "t" in row}
        for row in fetched:
            if not isinstance(row, dict) or isinstance(row.get("t"), bool):
                continue
            try:
                timestamp = int(row["t"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            previous = merged.get(timestamp)
            if previous is None or (row.get("closed") is True and previous.get("closed") is not True):
                merged[timestamp] = row
        recent = [merged[key] for key in sorted(merged)][-140:]
        if not recent:
            raise RuntimeError(f"Binance {symbol} {interval}: kullanılabilir arşiv veya REST mumu yok.")
        return valid_bars(recent, closed_only=False)


    def bootstrap_history(self) -> None:
        """Load history safely; a shared REST outage must not fan out to every symbol."""
        with self.lock:
            pairs = list(self.universe.get("pairs", []))
        work = [(pair["binance_symbol"], tf, interval)
                for pair in pairs for tf, interval in TIMEFRAMES.items()]
        total = len(work)
        with self.lock:
            self.bootstrap_total = total
            self.bootstrap_completed = 0
            self.bootstrap_error_count = 0
            self.bootstrap_success_count = 0
            self.bootstrap_skipped_count = 0
        self.logger.info(
            "Geçmiş mumlar hazırlanıyor: %s parite x %s zaman dilimi (%s istek).",
            len(pairs), len(TIMEFRAMES), total,
        )
        errors: list[str] = []
        archive = getattr(self, "candle_archive", None)
        if archive is not None:
            # Load saved closed candles before testing REST connectivity. Cached bars
            # remain available for context during an outage, but do not make bootstrap
            # or strong-alert readiness successful.
            try:
                for (symbol, timeframe), saved in archive.iter_latest_bars(
                    [(symbol, timeframe) for symbol, timeframe, _interval in work],
                    limit=140,
                ):
                    if saved:
                        self._merge_bar_series(symbol, timeframe, saved)
            except Exception as exc:
                self._history_storage_warning(
                    f"Başlangıç arşivi topluca okunamadı ({type(exc).__name__}); canlı REST yüklemesi denenecek."
                )
        completed = 0
        successful = 0
        last_progress_log = 0
        aborted = False
        rest_circuit_open = threading.Event()
        try:
            if not work:
                errors.append("Tarama evreninde geçmiş mum hazırlığı için parite bulunamadı.")
                self.api_warnings = errors
                with self.lock:
                    self.bootstrap_error_count = 1
                    self.bootstrap_skipped_count = 0
                delay = self._schedule_bootstrap_retry(success=False)
                self.logger.warning("Geçmiş mum hazırlığı beklemede; parite yok. %s sn sonra yeniden denenecek.", delay)
                return

            # Probe one known, widely traded symbol first. If REST/TLS is down, avoid
            # issuing up to 1,432 x seven hostname attempts for the same network failure.
            try:
                probe_rows = valid_bars(
                    _get_klines("BTCUSDT", "5m", limit=5), closed_only=False
                )
                if not probe_rows:
                    raise RuntimeError("BTCUSDT 5m bağlantı ön kontrolünde kullanılabilir mum dönmedi.")
            except Exception as exc:
                errors.append(f"Binance REST bağlantı ön kontrolü başarısız (BTCUSDT 5m): {exc}")
                self.api_warnings = (errors + getattr(self, "_history_storage_warnings", []))[:8]
                with self.lock:
                    self.bootstrap_error_count = 1
                    self.bootstrap_success_count = 0
                    self.bootstrap_skipped_count = total
                delay = self._schedule_bootstrap_retry(success=False)
                self.logger.error(
                    "REST bağlantısı ön kontrolde başarısız; %s geçmiş isteği başlatılmadı. "
                    "Güçlü alarm kapalı kalacak; %s sn sonra tekrar denenecek. Hata: %s",
                    total, delay, errors[0][:700],
                )
                return

            def task(item: tuple[str, str, str]):
                # Workers that have not started yet should honor a circuit opened by
                # transport failures already observed by the coordinator thread.
                if rest_circuit_open.is_set():
                    return None
                symbol, tf, interval = item
                rows = self._load_repair_history(symbol, tf, interval)
                if not rows:
                    raise RuntimeError(
                        f"Binance {symbol} {interval}: arşiv/REST onarımında kullanılabilir mum yok."
                    )
                return symbol, tf, rows

            transport_failure_streak = 0
            circuit_open = False
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(task, item) for item in work]
                for future in as_completed(futures):
                    if future.cancelled():
                        continue
                    if stop_requested(self.stop_file) or self.rebuild_event.is_set():
                        aborted = True
                        for pending in futures:
                            if not pending.done():
                                pending.cancel()
                        continue
                    try:
                        result = future.result()
                        if result is None:
                            continue
                        symbol, tf, rows = result
                        successful += 1
                        transport_failure_streak = 0
                        # Merge history by timestamp; newer live data wins for the same candle.
                        self._merge_bar_series(symbol, tf, rows)
                    except Exception as exc:
                        errors.append(str(exc))
                        transport_failure_streak = (
                            transport_failure_streak + 1
                            if _is_rest_transport_failure(exc) else 0
                        )
                        if transport_failure_streak >= 2 and not circuit_open:
                            circuit_open = True
                            rest_circuit_open.set()
                    completed += 1
                    percent = int(completed * 100 / total) if total else 100
                    with self.lock:
                        self.bootstrap_completed = completed
                        self.bootstrap_error_count = len(errors)
                        self.bootstrap_success_count = successful
                        self.bootstrap_skipped_count = max(0, total - completed)
                    if percent >= last_progress_log + 10 or completed == total:
                        self.logger.info(
                            "Geçmiş mum ilerlemesi: %s/%s istek (%s%%); hata=%s; atlanan=%s.",
                            completed, total, percent, len(errors), max(0, total-completed),
                        )
                        last_progress_log = percent
                    if transport_failure_streak >= 2 and not circuit_open:
                        circuit_open = True
                        self.logger.error(
                            "REST bağlantı kesicisi açıldı: art arda iki ortak taşıma/TLS hatası. "
                            "Bekleyen geçmiş istekleri iptal ediliyor; sırada yalnızca sınırlı sayıdaki "
                            "çalışan istek tamamlanacak."
                        )
                        for pending in futures:
                            if not pending.done():
                                pending.cancel()
            with self.lock:
                self.bootstrap_completed = completed
                self.bootstrap_error_count = len(errors)
                self.bootstrap_success_count = successful
                self.bootstrap_skipped_count = max(0, total - completed)
            self.api_warnings = (
                errors + getattr(self, "_history_storage_warnings", [])
            )[:8]
            full_success = (
                not aborted and completed >= total and not errors and successful >= total
            )
            if full_success:
                self._schedule_bootstrap_retry(success=True)
                self.logger.info("Geçmiş mum hazırlığı tamamlandı.")
            else:
                delay = self._schedule_bootstrap_retry(success=False) if not aborted else 0
                if errors:
                    self.logger.warning(
                        "Geçmiş mum hazırlığı eksik (%s/%s tamamlandı; %s hata; %s atlandı). "
                        "Eksik veriler güçlü alarm için yeterli sayılmayacak.",
                        completed, total, len(errors), max(0, total-completed),
                    )
                    for err in errors[:5]:
                        self.logger.warning("Mum verisi hatası: %s", err[:700])
                if not aborted:
                    self.logger.warning(
                        "Geçmiş mum hazırlığı %s sn sonra yeniden denenecek.", delay
                    )
        finally:
            self.bootstrap_done.set()

    def _start_bootstrap_history_async(self) -> bool:
        current = self.bootstrap_thread
        if current is not None and current.is_alive():
            self.logger.info("Geçmiş mum hazırlığı zaten sürüyor; ikinci hazırlık açılmadı.")
            return False
        self.bootstrap_done.clear()
        thread = threading.Thread(target=self.bootstrap_history, daemon=True,
                                  name="binance-history-bootstrap")
        self.bootstrap_thread = thread
        thread.start()
        return True

    def _stream_url(self, symbols: list[str], base: str | None = None) -> str:
        stream_names = []
        for sym in symbols:
            lower = sym.lower()
            for interval in TIMEFRAMES.values():
                stream_names.append(f"{lower}@kline_{interval}")
        return (base or WS_BASES[0]) + "/".join(stream_names)

    def _backfill_all_timeframes(self, symbols: list[str]) -> None:
        """Restore candle history for all eight frames after a stream interruption.

        REST backfill is not evidence of a live WebSocket update; strong-alert freshness
        still requires new messages for every timeframe.
        """
        for symbol in symbols:
            if stop_requested(self.stop_file) or self.rebuild_event.is_set():
                return
            for tf, interval in TIMEFRAMES.items():
                if stop_requested(self.stop_file) or self.rebuild_event.is_set():
                    return
                try:
                    if getattr(self, "candle_archive", None) is None:
                        rows = _get_klines(symbol, interval, limit=BOOTSTRAP_LIMIT)
                    else:
                        rows = self._load_repair_history(symbol, tf, interval)
                    self._merge_bar_series(symbol, tf, rows)
                except Exception as exc:
                    self.logger.warning(
                        "Reconnect candle backfill failed for %s %s: %s",
                        symbol, tf, exc,
                    )

    def start_ws_shards(self) -> None:
        with self.lock:
            symbols = [p["binance_symbol"] for p in self.universe.get("pairs", [])]
        shards = [symbols[i:i + SHARD_SYMBOLS] for i in range(0, len(symbols), SHARD_SYMBOLS)]
        self.logger.info("Canlı mum akışı: %s WebSocket parçası, parça başına en fazla %s parite.",
                         len(shards), SHARD_SYMBOLS)
        for shard_id, shard in enumerate(shards):
            if stop_requested(self.stop_file):
                break
            thread = threading.Thread(target=self._run_shard, args=(shard_id, shard), daemon=True,
                                      name=f"binance-ws-{shard_id}")
            self.ws_threads.append(thread)
            thread.start()
            time.sleep(0.35)  # Eş zamanlı bağlantı fırtınasını önler.

    def _run_shard(self, shard_id: int, symbols: list[str]) -> None:
        endpoint_index = 0
        # Önce doğrudan bağlantıyı dene; başarısızlıkta ortam-proxy yolunu da dönüşümlü sınayacağız.
        bypass_env_proxy = True
        consecutive_failures = 0
        while not stop_requested(self.stop_file) and not self.rebuild_event.is_set():
            app: websocket.WebSocketApp | None = None
            connection_error = ""
            connected_at: float | None = None
            endpoints = list(get_binance_ws_bases())
            endpoint_index %= len(endpoints)
            endpoint = endpoints[endpoint_index]
            try:
                with self.lock:
                    self.ws_status[shard_id] = "BAĞLANTI DENENİYOR"

                def on_open(ws):
                    nonlocal connected_at
                    connected_at = time.monotonic()
                    with self.lock:
                        reconnecting = shard_id in self.ever_connected_shards
                        self.ever_connected_shards.add(shard_id)
                        self.ws_status[shard_id] = "BAĞLI"
                        self.connected_at_by_shard[shard_id] = time.time()
                        # A new handshake must not inherit a previous socket\'s last-data timestamp.
                        self.last_message.pop(shard_id, None)
                    self.logger.info("Binance WebSocket #%s bağlı (%s parite, %s).",
                                     shard_id + 1, len(symbols), endpoint.split("?", 1)[0])
                    if reconnecting:
                        threading.Thread(target=self._backfill_all_timeframes, args=(list(symbols),),
                                         daemon=True, name=f"binance-backfill-{shard_id}").start()

                def on_message(ws, message: str):
                    try:
                        payload = json.loads(message)
                        data = payload.get("data", payload)
                        if not isinstance(data, dict):
                            return
                        if data.get("e") == "serverShutdown":
                            self.logger.warning("Binance sunucu kapanış bildirimi; yedek bağlantı denenecek.")
                            ws.close()
                            return
                        if data.get("e") != "kline":
                            return
                        with self.lock:
                            self.kline_message_count_by_shard[shard_id] = (
                                self.kline_message_count_by_shard.get(shard_id, 0) + 1)
                        k = data.get("k", {})
                        sym = str(k.get("s", "")).upper()
                        interval = str(k.get("i", ""))
                        tf = next((key for key, value in TIMEFRAMES.items() if value == interval), None)
                        if not sym or not tf or not k:
                            return
                        bar = normalize_bar(k.get("t"), k.get("o"), k.get("h"), k.get("l"), k.get("c"),
                                            k.get("v"), k.get("q"), k.get("n"), closed=bool(k.get("x")))
                        now_ms = int(time.time() * 1000)
                        event_ms = int(data.get("E") or now_ms)
                        fresh_event = -5000 <= now_ms - event_ms <= int(float(self.settings.get(
                            "websocket_stale_seconds_binance", 45)) * 1000)
                        with self.lock:
                            arr = self.bars.setdefault(sym, {key: [] for key in TIMEFRAMES}).setdefault(tf, [])
                            bar_time = int(bar["t"])
                            if arr and int(arr[-1]["t"]) == bar_time:
                                arr[-1] = bar
                            elif not arr or int(arr[-1]["t"]) < bar_time:
                                arr.append(bar)
                                del arr[:-140]
                            else:
                                # Eski mum cache'i geriye taşımaz; yalnızca aynı mum varsa güncellenir.
                                for idx in range(len(arr) - 1, -1, -1):
                                    if int(arr[idx]["t"]) == bar_time:
                                        arr[idx] = bar
                                        break
                            key = (sym, tf)
                            prior_event = self.last_symbol_event_ms.get(key, 0)
                            if fresh_event and event_ms >= prior_event:
                                self.last_symbol_event_ms[key] = event_ms
                                self.last_symbol_update[key] = time.time()
                                self.last_message[shard_id] = time.time()
                        # Persist only completed candles. An unfinished WebSocket
                        # update must never replace a durable, closed candle.
                        if bar.get("closed") is True and getattr(self, "candle_archive", None) is not None:
                            try:
                                self.candle_archive.upsert_bars(sym, tf, [bar])
                                self.last_history_write = time.time()
                            except Exception as archive_exc:
                                self._history_storage_warning(
                                    f"Canlı kapanmış mum arşivlenemedi ({type(archive_exc).__name__}); akış sürecek."
                                )
                    except Exception as exc:
                        self.logger.debug("WebSocket mesaj ayrıştırma sorunu: %s", exc)

                def on_error(ws, error):
                    nonlocal connection_error
                    connection_error = str(error)
                    with self.lock:
                        self.ws_status[shard_id] = "HATA"
                    self.logger.warning("Binance WebSocket #%s (%s): %s", shard_id + 1, endpoint, error)

                def on_close(ws, status_code, message):
                    with self.lock:
                        self.ws_status[shard_id] = "KAPALI"
                        self.connected_at_by_shard.pop(shard_id, None)
                    self.logger.info("Binance WebSocket #%s kapandı (%s).", shard_id + 1, status_code)

                app = websocket.WebSocketApp(self._stream_url(symbols, endpoint),
                                             on_open=on_open, on_message=on_message,
                                             on_error=on_error, on_close=on_close)
                with self.lock:
                    self.ws_apps.append(app)
                    self.ws_apps_by_shard[shard_id] = app
                app.run_forever(ping_interval=20, ping_timeout=10, reconnect=0,
                                http_no_proxy=["*"] if bypass_env_proxy else None)
            except Exception as exc:
                connection_error = str(exc)
                with self.lock:
                    self.ws_status[shard_id] = "HATA"
                self.logger.warning("Binance WebSocket #%s bağlantı döngüsü (%s): %s", shard_id + 1, endpoint, exc)
            finally:
                if app is not None:
                    with self.lock:
                        if app in self.ws_apps:
                            self.ws_apps.remove(app)
                        if self.ws_apps_by_shard.get(shard_id) is app:
                            self.ws_apps_by_shard.pop(shard_id, None)
            if self.rebuild_event.is_set():
                return
            if connected_at is not None and time.monotonic() - connected_at >= 60.0:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
            lower_error = connection_error.lower()
            if connection_error:
                bypass_env_proxy = not bypass_env_proxy
                mode = "proxy atlanarak doğrudan" if bypass_env_proxy else "ortam-proxy/ağ yolu kullanılarak"
                if "wrong_version_number" in lower_error or "wrong version number" in lower_error:
                    self.logger.warning(
                        "Binance WebSocket TLS WRONG_VERSION_NUMBER hatası; sonraki deneme %s yapılacak.", mode)
                else:
                    if "timeout" in lower_error or "timed out" in lower_error:
                        error_kind = "zaman aşımı"
                    elif "proxy" in lower_error:
                        error_kind = "proxy bağlantı sorunu"
                    elif "ssl" in lower_error or "tls" in lower_error:
                        error_kind = "TLS/SSL hatası"
                    else:
                        error_kind = "bağlantı hatası"
                    self.logger.warning(
                        "Binance WebSocket %s; sonraki deneme %s yapılacak.", error_kind, mode,
                    )
            endpoint_index = (endpoint_index + 1) % len(endpoints)
            if not stop_requested(self.stop_file):
                # Binance limits connection attempts per IP. Back off on repeated failures,
                # cap the wait, and stagger shards so outages don't create a reconnect storm.
                delay = min(60.0, 3.0 * (2 ** min(max(0, consecutive_failures - 1), 5)))
                delay += 0.25 * (shard_id % SHARD_SYMBOLS)
                self.logger.warning(
                    "Binance WebSocket #%s yeniden bağlantı beklemesi: %.2f sn (ardışık hata=%s).",
                    shard_id + 1, delay, consecutive_failures,
                )
                time.sleep(delay)

    def stop_ws_shards(self) -> None:
        with self.lock:
            apps = list(self.ws_apps)
            threads = list(self.ws_threads)
        for app in apps:
            try:
                app.close()
            except Exception:
                pass
        for thread in threads:
            if thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=2.0)
        with self.lock:
            self.ws_threads.clear()
            self.ws_apps.clear()
            self.ws_status.clear()
            self.last_message.clear()
            self.kline_message_count_by_shard.clear()
            self.connected_at_by_shard.clear()
            self.ws_apps_by_shard.clear()
            self.ever_connected_shards.clear()

    def watchdog(self) -> None:
        while not stop_requested(self.stop_file):
            time.sleep(0.8)
        with self.lock:
            apps = list(self.ws_apps)
        for app in apps:
            try:
                app.close()
            except Exception:
                pass

    def _candidate_rows(self) -> list[dict[str, Any]]:
        with self.lock:
            pairs = list(self.universe.get("pairs", []))
            bars_snapshot = {sym: {tf: list(rows) for tf, rows in map_tf.items()}
                             for sym, map_tf in self.bars.items()}
            symbol_updates = dict(self.last_symbol_update)
        pair_map = {p["binance_symbol"]: p for p in pairs}
        btc_bars = bars_snapshot.get("BTCUSDT", {})
        threshold = float(self.settings.get("websocket_stale_seconds_binance", 45))
        now = time.time()
        btc_ages = {
            timeframe: (
                now - symbol_updates[("BTCUSDT", timeframe)]
                if ("BTCUSDT", timeframe) in symbol_updates else None
            )
            for timeframe in ("1h", "4h")
        }
        btc_context, btc_context_fresh, btc_context_warning = _apply_btc_context_freshness(
            score_btc_market_context(btc_bars),
            btc_ages,
            stale_seconds=threshold,
        )
        self.btc_market_context = btc_context
        self.btc_market_context_freshness = (
            "CANLI AKIŞ GÜNCEL" if btc_context_fresh else "ESKİ/EKSİK"
        )
        self.btc_market_context_warning = btc_context_warning
        self.btc_context_strong_alert_gate = assess_btc_strong_opportunity_gate(
            btc_context,
            freshness=self.btc_market_context_freshness,
            require_measurements=True,
        )
        self.btc_market_context_last_update_age_seconds_by_timeframe = (
            btc_context.get("stream_freshness_by_timeframe", {})
        )
        results: list[dict[str, Any]] = []
        for pair in pairs:
            symbol = pair["binance_symbol"]
            tf_ages = {tf: (now - symbol_updates[(symbol, tf)]) if (symbol, tf) in symbol_updates else None
                       for tf in TIMEFRAMES}
            candidate = evaluate_binance_candidate(symbol, bars_snapshot.get(symbol, {}),
                                                    btc_bars, pair, self.settings)
            latest = next((rows[-1] for tf in ("5m", "15m", "30m", "1h")
                           if (rows := bars_snapshot.get(symbol, {}).get(tf))), None)
            live_price = float(latest["c"]) if latest and latest.get("c") is not None else None
            if candidate is None:
                continue
            candidate["latest_price"] = live_price if live_price is not None else candidate.get("latest_price")
            pair_info = pair_map.get(symbol, {})
            candidate["strong_alarm_eligible"] = _strong_alarm_permission(
                pair_info, single_engine=getattr(self, "single_engine", False) is True
            )
            candidate["strong_alarm_block_reason"] = pair_info.get("strong_alarm_block_reason")
            candidate["websocket_age_seconds_by_timeframe"] = {
                tf: round(age, 1) if age is not None else None for tf, age in tf_ages.items()}
            # Every configured timeframe must have a recent stream update before the
            # mixed-age assessment can be presented as a current opportunity.
            fresh_required = [tf_ages.get(tf) for tf in TIMEFRAMES]
            live_ok = all(age is not None and 0.0 <= age <= threshold for age in fresh_required)
            # İleri performans kayıtlarına yalnızca güncel canlı mum fiyatı ver;
            # eski cache fiyatı 30m/1h/4h/24h sonucu gibi kaydedilmemeli.
            self.price_by_base[pair["base_asset"]] = live_price if live_ok else None
            # Ham analiz aşamasını sakla; canlı veri eskidiğinde bunu aktif aşama
            # gibi sunma, ancak arayüzde gri "son aşama" bilgisi gösterebil.
            candidate["last_known_phase"] = candidate.get("phase")
            candidate["data_freshness"] = "CANLI AKIŞ GÜNCEL" if live_ok else "CANLI VERİ ESKİ/EKSİK"
            if not live_ok:
                candidate["missing_checks"] = sorted(set(candidate.get("missing_checks", []) +
                    ["5m/15m/30m/1h/4h/1d/1w/1M canlı mum güncellemelerinden biri eksik/eski; aşama güncel fırsat sayılmamalı"]))
                candidate["phase"] = None
                candidate["state"] = "VERİ EKSİK — CANLI AKIŞ GÜNCEL DEĞİL"
            candidate["last_stream_update_age_seconds"] = min(
                [age for age in fresh_required if age is not None], default=None)
            # Recompute after applying per-symbol freshness and the freshest available candle.
            # Otherwise a stale B/C result could carry an old numeric plan into the panel.
            candidate["btc_market_context"] = btc_context
            candidate["btc_market_context_freshness"] = self.btc_market_context_freshness
            if not btc_context_fresh:
                btc_missing_note = (
                    btc_context_warning
                    or "BTC piyasa bağlamı eski/eksik; güncel BTC puanı kullanılamıyor."
                )
                _quarantine_btc_relative_metrics(candidate, reason=btc_missing_note)
            else:
                conflict_note = _btc_candidate_conflict_note(
                    candidate, btc_context, context_fresh=btc_context_fresh
                )
                if conflict_note:
                    candidate["btc_context_conflict"] = True
                    candidate["btc_context_conflict_note"] = conflict_note
                    findings = candidate.get("findings")
                    if isinstance(findings, list) and conflict_note not in findings:
                        findings.append(conflict_note)
            candidate["risk_plan"] = build_trade_plan(candidate, settings=self.settings)
            candidate.update(score_opportunity(candidate, btc_context=btc_context))
            results.append(candidate)

        # Group points require an explicit, operator-verified asset/category map and
        # at least three comparable live members. Re-score before choosing the liquidity shortlist.
        self.group_leadership_diagnostics = _annotate_group_leadership(results, self.settings)
        for candidate in results:
            candidate.update(score_opportunity(candidate, btc_context=btc_context))

        # First pass ranks technical setups; expensive depth checks run only for a bounded B/C shortlist.
        self._refresh_candidate_liquidity(results, now_epoch=time.time())
        for candidate in results:
            # Rebuild the technical plan after the live spread/depth assessment arrives.
            candidate["risk_plan"] = build_trade_plan(candidate, settings=self.settings)
            candidate.update(score_opportunity(
                candidate, btc_context=btc_context
            ))

        results.sort(key=candidate_priority_key, reverse=True)
        return results

    def write_candidate_history(self, candidates: list[dict[str, Any]]) -> None:
        """Append a same-timestamp decision snapshot using a schema-versioned CSV."""
        day = time.strftime("%Y%m%d", time.gmtime())
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        fields = [
            "history_schema_version", "timestamp_utc", "symbol", "phase", "state",
            "phase_timeframe", "price", "data_freshness", "final_decision",
            "opportunity_score", "strong_opportunity_qualified", "strong_alarm_eligible",
            "strong_alarm_block_reason", "decision_reason", "strong_opportunity_gate_reasons_json",
            "score_components_json", "evidence_groups", "findings", "missing_checks",
            "risk_plan_json", "btc_market_context_json", "liquidity_assessment_json",
            "relative_strength_vs_btc_json", "btc_return_correlation_json", "timeframes_metrics_json",
            "group_category", "group_category_verified", "group_category_source",
            "group_comparable_count", "group_leadership_score", "group_leadership_basis",
            "group_leadership_summary",
        ]
        schema_version = 3
        while True:
            path = DATA_DIR / f"binance_candidates_history_{day}_v{schema_version}.csv"
            new_file = not path.exists() or path.stat().st_size == 0
            if new_file:
                break
            try:
                with path.open("r", newline="", encoding="utf-8-sig") as existing_handle:
                    existing_fields = next(csv.reader(existing_handle), [])
            except (OSError, UnicodeError, csv.Error):
                existing_fields = []
            if existing_fields == fields:
                break
            schema_version += 1

        with path.open("a", newline="", encoding="utf-8-sig" if new_file else "utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            if new_file:
                writer.writeheader()
            snapshot_time = utc_now()
            # Aday olanlar yanında aday olmayan/eksik verili tüm ortak pariteler kaydedilir.
            # Decision, plan and context fields are captured together so a later replay does
            # not have to reconstruct the decision from a newer scan.
            for row in candidates:
                metrics_by_tf = {
                    tf: data.get("metrics", {})
                    for tf, data in row.get("timeframes", {}).items()
                    if isinstance(data, dict)
                }
                writer.writerow({
                    "history_schema_version": schema_version,
                    "timestamp_utc": snapshot_time,
                    "symbol": row.get("symbol"),
                    "phase": row.get("phase"),
                    "state": row.get("state"),
                    "phase_timeframe": row.get("phase_timeframe"),
                    "price": row.get("latest_price"),
                    "data_freshness": row.get("data_freshness"),
                    "final_decision": row.get("final_decision"),
                    "opportunity_score": row.get("opportunity_score"),
                    "strong_opportunity_qualified": row.get("strong_opportunity_qualified"),
                    "strong_alarm_eligible": row.get("strong_alarm_eligible"),
                    "strong_alarm_block_reason": row.get("strong_alarm_block_reason"),
                    "decision_reason": row.get("decision_reason"),
                    "strong_opportunity_gate_reasons_json": json.dumps(
                        row.get("strong_opportunity_gate_reasons", []), ensure_ascii=False,
                        separators=(",", ":"), allow_nan=False
                    ),
                    "score_components_json": json.dumps(
                        row.get("score_components", {}), ensure_ascii=False, separators=(",", ":"),
                        allow_nan=False
                    ),
                    "evidence_groups": " | ".join(row.get("evidence_groups", [])),
                    "findings": " | ".join(row.get("findings", [])),
                    "missing_checks": " | ".join(row.get("missing_checks", [])),
                    "risk_plan_json": json.dumps(
                        row.get("risk_plan"), ensure_ascii=False, separators=(",", ":"), allow_nan=False
                    ),
                    "btc_market_context_json": json.dumps(
                        row.get("btc_market_context"), ensure_ascii=False, separators=(",", ":"), allow_nan=False
                    ),
                    "liquidity_assessment_json": json.dumps(
                        row.get("liquidity_assessment"), ensure_ascii=False, separators=(",", ":"), allow_nan=False
                    ),
                    "relative_strength_vs_btc_json": json.dumps(
                        row.get("relative_strength_vs_btc_pct_points", {}),
                        ensure_ascii=False, separators=(",", ":"), allow_nan=False
                    ),
                    "btc_return_correlation_json": json.dumps(
                        row.get("btc_return_correlation", {}),
                        ensure_ascii=False, separators=(",", ":"), allow_nan=False
                    ),
                    "timeframes_metrics_json": json.dumps(
                        metrics_by_tf, ensure_ascii=False, separators=(",", ":"), allow_nan=False
                    ),
                    "group_category": row.get("group_category"),
                    "group_category_verified": row.get("group_category_verified"),
                    "group_category_source": row.get("group_category_source"),
                    "group_comparable_count": row.get("group_comparable_count"),
                    "group_leadership_score": row.get("group_leadership_score"),
                    "group_leadership_basis": row.get("group_leadership_basis"),
                    "group_leadership_summary": row.get("group_leadership_summary"),
                })

    def _wait_for_initial_universe(self) -> bool:
        """Try startup once; report a stable wait state if no usable universe is available."""
        if stop_requested(self.stop_file):
            return False
        try:
            self.refresh_universe()
            pairs = self.universe.get("pairs", []) if isinstance(self.universe, dict) else []
            if not isinstance(pairs, list) or not pairs:
                waiting_warning = str(
                    (self.universe.get("warning") if isinstance(self.universe, dict) else None)
                    or "Geçerli tarama evreni yok; BtcTurk parite listesini güncelleyip motoru yeniden başlatın."
                )
                waiting_state = {
                    "radar": "Tek Motor — Binance Spot",
                    "source": "Binance aktif USDT listesi ile önceki ortak evren kesişimi",
                    "generated_at_utc": utc_now(),
                    "status": "TARAMA EVRENİ BEKLENİYOR",
                    "universe_mode": (
                        self.universe.get("universe_mode", "WAITING_FOR_VALID_UNIVERSE")
                        if isinstance(self.universe, dict) else "WAITING_FOR_VALID_UNIVERSE"
                    ),
                    "scan_symbol_count": 0,
                    "common_pair_count": 0,
                    "strong_alerts_enabled": False,
                    "runtime_diagnostics": collect_network_diagnostics(),
                    "error": waiting_warning,
                    "universe_warning": waiting_warning,
                    "automatic_retry_enabled": False,
                    "candidates": [],
                    "important_note": (
                        "Güncel Binance listesinde önceki ortak evrenden aktif parite kalmadı. "
                        "Eski pariteler taranmıyor. Panelden 'Parite listesini güncelle' düğmesini "
                        "kullanın ve motoru yeniden başlatın."
                    ),
                }
                try:
                    atomic_json(DATA_DIR / "binance_state.json", waiting_state)
                except Exception as state_exc:
                    self.logger.exception("Evren bekleme durumu yazılamadı: %s", state_exc)
                return False
            return True
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"[:1000]
            self.logger.error(
                "Başlangıç tarama evreni tek denemede hazırlanamadı; otomatik tekrar kapalı. Hata: %s",
                error_text,
            )
            waiting_state = {
                "radar": "Tek Motor — Binance Spot",
                "source": "Binance fiyat/mum analizi; kayıtlı sembol evreni hazırlanıyor",
                "generated_at_utc": utc_now(),
                "status": "TARAMA EVRENİ BEKLENİYOR",
                "universe_mode": "WAITING_FOR_BTCTURK_UNIVERSE",
                "scan_symbol_count": 0,
                "strong_alerts_enabled": False,
                    "runtime_diagnostics": collect_network_diagnostics(),
                "error": error_text,
                "retry_seconds": 0,
                "automatic_retry_enabled": False,
                "candidates": [],
                "important_note": (
                    "Başlangıçta bir kez denendi; aynı bağlantı otomatik olarak tekrarlanmayacak. "
                    "Önceki kayıt bulunamadıysa panelde 'Parite listesini güncelle' düğmesini kullanın "
                    "ve motoru yeniden başlatın. Güncel Binance fiyat/mum verisi yoksa fırsat veya "
                    "güçlü alarm gösterilmez."
                ),
            }
            try:
                atomic_json(DATA_DIR / "binance_state.json", waiting_state)
            except Exception as state_exc:
                self.logger.exception("Evren bekleme durumu yazılamadı: %s", state_exc)
            return False

    def _start_storage_maintenance(self) -> None:
        """Run archive/cleanup work off the live scan loop and prevent overlapping runs."""
        if getattr(self, "settings", {}).get("storage_maintenance_enabled", True) is False:
            return
        with self._storage_maintenance_lock:
            if self._storage_maintenance_running:
                return
            self._storage_maintenance_running = True

        def worker() -> None:
            try:
                result = run_storage_maintenance(
                    DATA_DIR, LOG_DIR, RUN_DIR, DATA_DIR.parent / "reports",
                    settings=getattr(self, "settings", {}),
                )
                if any(result.get(key) for key in (
                    "candidate_archives_created", "candidate_source_files_deleted",
                    "candidate_rows_archived", "stale_temp_files_deleted",
                )):
                    self.logger.info(
                        "Depolama bakımı: arşiv=%s, silinen eski CSV=%s, arşiv satırı=%s, "
                        "geçici dosya=%s.",
                        result["candidate_archives_created"],
                        result["candidate_source_files_deleted"],
                        result["candidate_rows_archived"],
                        result["stale_temp_files_deleted"],
                    )
                for warning in result.get("warnings", []):
                    self.logger.warning("Depolama bakımı uyarısı: %s", warning)
            except Exception as exc:
                self.logger.exception(
                    "Depolama bakımı canlı taramayı durdurmadı: %s: %s",
                    type(exc).__name__, str(exc)[:350],
                )
            finally:
                with self._storage_maintenance_lock:
                    self._storage_maintenance_running = False

        maintenance_thread = threading.Thread(
            target=worker, daemon=True, name="storage-maintenance"
        )
        try:
            maintenance_thread.start()
        except Exception as exc:
            with self._storage_maintenance_lock:
                self._storage_maintenance_running = False
            self.logger.exception(
                "Depolama bakımı iş parçacığı başlatılamadı; canlı tarama devam edecek: %s: %s",
                type(exc).__name__, str(exc)[:300],
            )

    def run(self) -> int:
        self.price_by_base: dict[str, float | None] = {}
        self.logger.info("Binance Erken Fırsat Radarı başlatılıyor. A/B/C aşamaları emir değildir.")
        watcher = threading.Thread(target=self.watchdog, daemon=True, name="binance-stop-watcher")
        watcher.start()
        self._start_storage_maintenance()
        maintenance_interval = _storage_maintenance_interval_seconds(
            self.settings, logger=self.logger
        )
        last_storage_maintenance = time.monotonic()
        try:
            if self.single_engine:
                if not self._wait_for_initial_universe():
                    return 0
            else:
                self.refresh_universe()
            if stop_requested(self.stop_file):
                return 0
            self.start_ws_shards()
            self._start_bootstrap_history_async()
            while not stop_requested(self.stop_file):
                try:
                    if time.monotonic() - last_storage_maintenance >= maintenance_interval:
                        self._start_storage_maintenance()
                        last_storage_maintenance = time.monotonic()
                    refresh_flag = RUN_DIR / "single_engine_refresh.flag"
                    refresh_requested = self.single_engine and refresh_flag.exists()
                    if refresh_requested:
                        try:
                            refresh_flag.unlink(missing_ok=True)
                        except OSError:
                            pass
                    if refresh_requested or time.time() - self.last_rest_refresh >= self.universe_refresh_seconds:
                        changed = self.refresh_universe()
                        if changed:
                            self.logger.info("Ortak evren değişti; abonelikler ve geçmiş mumlar yenileniyor.")
                            self.rebuild_event.set()
                            self.stop_ws_shards()
                            self.rebuild_event.clear()
                            if not stop_requested(self.stop_file):
                                self.start_ws_shards()
                                if self.bootstrap_done.is_set():
                                    self._start_bootstrap_history_async()
                                else:
                                    self.logger.warning("Geçmiş mum hazırlığı tamamlanmadı; eşzamanlı ikinci hazırlık açılmadı.")
                    candidates = self._candidate_rows()
                    now = time.time()
                    with self.lock:
                        statuses = dict(self.ws_status)
                        messages = dict(self.last_message)
                        connected_at = dict(self.connected_at_by_shard)
                        apps_by_shard = dict(self.ws_apps_by_shard)
                    connected = sum(v == "BAĞLI" for v in statuses.values())
                    socket_count = len(statuses)
                    message_ages = {sid: (now - messages[sid] if sid in messages else None)
                                    for sid in statuses}
                    stale_limit = float(self.settings.get("websocket_stale_seconds_binance", 45)) * 2
                    stale_shards = []
                    for sid, status_value in statuses.items():
                        if status_value != "BAĞLI":
                            continue
                        last_valid_message = messages.get(sid)
                        opened_at = connected_at.get(sid)
                        reference_time = last_valid_message if last_valid_message is not None else opened_at
                        if reference_time is not None and now - reference_time > stale_limit:
                            stale_shards.append(sid)
                    for sid in stale_shards:
                        app = apps_by_shard.get(sid)
                        if app is not None:
                            self.logger.warning("Binance WebSocket #%s veri göndermiyor; yedek bağlantıya geçilecek.", sid + 1)
                            try:
                                app.close()
                            except Exception:
                                pass
                    ws_healthy = (
                        connected == socket_count
                        and _websocket_streams_have_fresh_data(
                            statuses, messages, now=now, stale_limit=stale_limit)
                    )
                    with self.lock:
                        bootstrap_completed = self.bootstrap_completed
                        bootstrap_total = self.bootstrap_total
                        bootstrap_errors = self.bootstrap_error_count
                    with self.lock:
                        bootstrap_successful = self.bootstrap_success_count
                    history_ready = _history_bootstrap_is_ready(
                        done=self.bootstrap_done.is_set(), total=bootstrap_total,
                        completed=bootstrap_completed, errors=bootstrap_errors,
                        successful=bootstrap_successful,
                    )
                    bootstrap_in_progress = (
                        not self.bootstrap_done.is_set()
                        or (bootstrap_total > 0 and bootstrap_completed < bootstrap_total)
                    )
                    bootstrap_percent = (
                        int(bootstrap_completed * 100 / bootstrap_total) if bootstrap_total else 100
                    )
                    # Bağlantı açıkken günlük sessiz kalmasın: gerçek kline mesajı
                    # sayısını ve her parçanın son veri yaşını aralıklı olarak yaz.
                    with self.lock:
                        counts = dict(self.kline_message_count_by_shard)
                    if now - self.last_heartbeat_log >= 30:
                        age_text = ", ".join(
                            f"#{sid + 1}:{age:.0f}s" if age is not None else f"#{sid + 1}:henüz veri yok"
                            for sid, age in sorted(message_ages.items())) or "henüz mesaj yok"
                        total_kline = sum(counts.values())
                        self.logger.info(
                            "Canlı akış kontrolü: bağlı %s/%s parça; toplam kline mesajı=%s; son veri yaşı [%s]; durum=%s",
                            connected, socket_count, total_kline, age_text,
                            "GÜNCEL" if ws_healthy else "UYARI")
                        self.last_heartbeat_log = now
                    self.signal_tracker.record("Binance", candidates, self.price_by_base,
                                               source_complete=ws_healthy)
                    _current_settings, current_settings_snapshot = load_settings_snapshot()
                    loaded_settings_snapshot = getattr(
                        self, "settings_snapshot", current_settings_snapshot
                    )
                    settings_changed_since_load = _settings_snapshot_changed(
                        loaded_settings_snapshot, current_settings_snapshot
                    )
                    settings_warning = (
                        "ayarlar.json motor başlatıldıktan sonra değişti veya erişilemez oldu; "
                        "değişiklikler uygulanmış sayılmıyor. Güncel ayarları kullanmak için "
                        "Binance motorunu durdurup yeniden başlatın."
                        if settings_changed_since_load else None
                    )
                    state = {
                        "application_version": APP_VERSION,
                        "radar": "Tek Motor — Binance Spot" if self.single_engine else "Binance Erken Fırsat Radarı",
                        "source": ("Binance Spot public market data; yerel BtcTurk listesi yalnızca sembol evreni için kullanılır"
                                   if self.single_engine else "Binance Spot public market data"),
                        "generated_at_utc": utc_now(), "generated_at_local": time.strftime("%Y-%m-%d %H:%M:%S %z"),
                        "status": (
                            "TARAMA EVRENİ BEKLENİYOR" if self.single_engine and not self.universe.get("pairs") else
                            "BAĞLANTI/VERİ UYARISI" if settings_changed_since_load else
                            "CANLI AKIŞ GÜNCEL" if ws_healthy and history_ready else
                            "BAŞLANGIÇ MUM VERİLERİ ALINIYOR" if bootstrap_in_progress else
                            "BAĞLANTI/VERİ UYARISI"
                        ),
                        "bootstrap_completed": bootstrap_completed,
                        "bootstrap_total": bootstrap_total,
                        "bootstrap_progress_pct": bootstrap_percent,
                        "bootstrap_errors": bootstrap_errors,
                        "bootstrap_successful": bootstrap_successful,
                        "bootstrap_skipped": self.bootstrap_skipped_count,
                        "bootstrap_retry_seconds": (
                            max(0, int(self.bootstrap_retry_at - time.monotonic()))
                            if not history_ready and self.bootstrap_retry_at > 0 else 0
                        ),
                        "bootstrap_ready": history_ready,
                        "btc_market_context": getattr(self, "btc_market_context", {
                            "status": "BTC VERİSİ ESKİ/EKSİK", "data_completeness": "EKSİK",
                            "direction_score": 0.0, "critical_level_score": 0.0,
                            "volatility_score": 0.0, "total_score": 0.0,
                            "timeframes": {}, "risk_warnings": [],
                            "data_quality_warnings": ["BTC piyasa bağlamı henüz hesaplanmadı."],
                        }),
                        "btc_market_context_freshness": getattr(
                            self, "btc_market_context_freshness", "ESKİ/EKSİK"
                        ),
                        "btc_market_context_warning": getattr(
                            self, "btc_market_context_warning",
                            "BTC piyasa bağlamı henüz doğrulanmadı.",
                        ),
                        "btc_market_context_last_update_age_seconds_by_timeframe": getattr(
                            self, "btc_market_context_last_update_age_seconds_by_timeframe", {}
                        ),
                        "btc_strong_alert_gate": getattr(self, "btc_context_strong_alert_gate", {
                            "eligible": False,
                            "fresh": False,
                            "complete": False,
                            "critical_level_loss_timeframes": [],
                            "relative_volatility_ratio": None,
                            "extreme_volatility": False,
                            "reasons": ["BTC güçlü fırsat/alarm kapısı henüz doğrulanmadı."],
                        }),
                        "peer_group_leadership": getattr(self, "group_leadership_diagnostics", {
                            "enabled": False,
                            "status": "GRUP PUANI KAPALI — DOĞRULANMIŞ EŞLEŞME YOK",
                            "mapped_asset_count": 0,
                            "groups_with_at_least_three_comparable_coins": 0,
                            "comparable_coin_count": 0,
                        }),
                        "universe_generated_at_utc": self.universe.get("generated_at_utc"),
                        "btcturk_universe_generated_at_utc": self.universe.get("btcturk_universe_generated_at_utc"),
                        "btcturk_universe_age_seconds": (
                            _age_seconds_from_utc_timestamp(
                                self.universe.get("btcturk_universe_generated_at_utc")
                                or self.universe.get("local_list_generated_at_utc")
                            )
                        ),
                        "local_list_age_seconds": _age_seconds_from_utc_timestamp(
                            self.universe.get("local_list_generated_at_utc")
                        ),
                        "single_engine_universe_cache_generated_at_utc": self.universe.get("single_engine_universe_cache_generated_at_utc"),
                        "single_engine_universe_cache_age_seconds": _age_seconds_from_utc_timestamp(
                            self.universe.get("single_engine_universe_cache_generated_at_utc")
                        ),
                        "single_engine_universe_cache_warning": self.universe.get("single_engine_universe_cache_warning"),
                        "btcturk_universe_mode": self.universe.get("btcturk_universe_mode"),
                        "btcturk_universe_warning": self.universe.get("btcturk_universe_warning"),
                        "universe_mode": self.universe.get("universe_mode", "COMMON_VERIFIED"),
                        "universe_warning": self.universe.get("warning") if self.universe.get("universe_mode", "COMMON_VERIFIED") != "COMMON_VERIFIED" else None,
                        "strong_alerts_enabled": (
                            (_strict_boolean_flag(
                                self.universe, "strong_alerts_enabled", default=False
                            ) if self.single_engine else True)
                            and not settings_changed_since_load
                            and _strict_boolean_flag(
                                getattr(self, "btc_context_strong_alert_gate", {}),
                                "eligible",
                                default=False,
                            )
                        ),
                        "binance_universe_source_verified": self.universe.get("binance_universe_source_verified", True),
                        "alert_filter_warning": self.universe.get("alert_filter_warning"),
                        "fan_token_filter_valid": self.universe.get("fan_token_filter_valid"),
                        "stablecoin_filter_valid": self.universe.get("stablecoin_filter_valid"),
                        "fan_token_list_count": self.universe.get("fan_token_list_count"),
                        "stablecoin_list_count": self.universe.get("stablecoin_list_count"),
                        "settings_path": current_settings_snapshot.get("settings_path"),
                        "settings_file_exists": current_settings_snapshot.get("settings_file_exists"),
                        "settings_file_size_bytes": current_settings_snapshot.get("settings_file_size_bytes"),
                        "settings_modified_at_utc": current_settings_snapshot.get("settings_modified_at_utc"),
                        "settings_sha256": current_settings_snapshot.get("settings_sha256"),
                        "settings_parse_status": current_settings_snapshot.get("settings_parse_status"),
                        "settings_parse_error": current_settings_snapshot.get("settings_parse_error"),
                        "settings_loaded_sha256": loaded_settings_snapshot.get("settings_sha256"),
                        "settings_loaded_modified_at_utc": loaded_settings_snapshot.get("settings_modified_at_utc"),
                        "settings_loaded_parse_status": loaded_settings_snapshot.get("settings_parse_status"),
                        "settings_changed_since_load": settings_changed_since_load,
                        "settings_warning": settings_warning,
                        "common_pair_count": len(self.universe.get("pairs", [])) if self.universe.get("universe_mode", "COMMON_VERIFIED") in ("COMMON_VERIFIED", "SINGLE_ENGINE_LOCAL_LIST", "CACHED_BTCTURK_FALLBACK", "CACHED_LAST_GOOD_UNIVERSE", "CACHED_LEGACY_UNIVERSE", "CACHED_BINANCE_SYMBOL_FALLBACK", "CACHED_LAST_VERIFIED_COMMON_UNIVERSE") else None,
                        "scan_symbol_count": len(self.universe.get("pairs", [])),
                        "websocket_connected_shards": connected, "websocket_total_shards": socket_count,
                        "websocket_stale_seconds_binance": float(self.settings.get("websocket_stale_seconds_binance", 45)),
                        "websocket_last_message_age_seconds": _websocket_age_seconds_by_shard(
                            now, messages, statuses
                        ),
                        "websocket_connected_age_seconds": _websocket_age_seconds_by_shard(
                            now, connected_at, statuses
                        ),
                        "websocket_kline_message_count_by_shard": {str(k): v for k, v in counts.items()},
                        "runtime_diagnostics": {
                            "python_version": sys.version.split()[0],
                            "openssl_version": ssl.OPENSSL_VERSION,
                            **collect_network_diagnostics(),
                        },
                        "api_warnings": self.api_warnings,
                        "signal_history_database": "data/sinyal_gecmisi.sqlite3",
                        "important_note": "Fırsat puanı 8 temel teknik/bağlamsal bileşen ve gerektiğinde BTC korelasyon risk düzeltmesi içerir; nihai sınıf güçlü fırsat kapılarıyla ayrı hesaplanır. A/B/C araştırma aşamalarıdır; otomatik AL/emir değildir.",
                        "audit_symbol_count": len(candidates),
                        # Preserve every detected phase candidate so the panel and
                        # BtcTurk supplement cannot miss a valid strong opportunity due to a UI cap.
                        "candidates": [row for row in candidates
                                       if row.get("phase") in ("A", "B", "C")
                                       or row.get("last_known_phase") in ("A", "B", "C")],
                    }
                    atomic_json(DATA_DIR / "binance_state.json", state)
                    retry_thread = getattr(self, "bootstrap_thread", None)
                    if (
                        not history_ready
                        and self.bootstrap_done.is_set()
                        and self.bootstrap_retry_at > 0
                        and time.monotonic() >= self.bootstrap_retry_at
                        and not stop_requested(self.stop_file)
                        and not self.rebuild_event.is_set()
                        and (retry_thread is None or not retry_thread.is_alive())
                    ):
                        self.logger.info("Eksik/eski geçmiş mumlar için otomatik yeniden deneme başlatılıyor.")
                        self._start_bootstrap_history_async()
                    if now - self.last_history_write >= self.audit_interval_seconds:
                        if self.universe.get("universe_mode", "COMMON_VERIFIED") in ("COMMON_VERIFIED", "SINGLE_ENGINE_LOCAL_LIST", "CACHED_BTCTURK_FALLBACK", "CACHED_LAST_GOOD_UNIVERSE", "CACHED_LEGACY_UNIVERSE", "CACHED_BINANCE_SYMBOL_FALLBACK", "CACHED_LAST_VERIFIED_COMMON_UNIVERSE"):
                            self.write_candidate_history(candidates)
                        else:
                            self.logger.info("Aday geçmişi ortak-evren denetim CSV'sine yazılmadı; tarama evreni BtcTurk ile güncel doğrulanmadı.")
                        self.last_history_write = now
                except Exception as exc:
                    self.logger.exception("Radar döngüsü hatası: %s", exc)
                for _ in range(self.scan_seconds * 2):
                    if stop_requested(self.stop_file):
                        break
                    time.sleep(0.5)
        except Exception as exc:
            self.logger.exception("Radar başlatılamadı: %s", exc)
            try:
                atomic_json(DATA_DIR / "binance_state.json", {
                    "application_version": APP_VERSION,
                    "radar": "Binance Erken Fırsat Radarı", "status": "BAŞLATMA HATASI",
                    "generated_at_utc": utc_now(), "error": str(exc), "candidates": []})
            except Exception as state_exc:
                self.logger.exception("Başlatma hatası durum dosyasına yazılamadı: %s", state_exc)
            return 1
        finally:
            self.stop_ws_shards()
            try:
                latest_state = load_json(DATA_DIR / "binance_state.json", {}) or {}
                # Do not overwrite a startup failure with DURDURULDU: the UI must
                # retain the concrete reason that prevented the engine from running.
                if latest_state.get("status") in ("BAŞLATMA HATASI", "TARAMA EVRENİ BEKLENİYOR"):
                    latest_state["generated_at_utc"] = utc_now()
                    latest_state["stop_note"] = (
                        "Tarama evreni beklemede; otomatik tekrar kapalı."
                        if latest_state.get("status") == "TARAMA EVRENİ BEKLENİYOR"
                        else "Başlatma başarısız oldu; asıl hata korunuyor."
                    )
                else:
                    latest_state.update({"status": "DURDURULDU", "generated_at_utc": utc_now(),
                                         "stop_note": "Radar durduruldu; son adaylar tarihsel anlık görüntüdür."})
                atomic_json(DATA_DIR / "binance_state.json", latest_state)
            except Exception as state_exc:
                self.logger.exception("Kapanış durumu yazılamadı; radar süreci kapanışı sürdürülüyor: %s", state_exc)
            self.logger.info("Binance Erken Fırsat Radarı durduruldu.")
        return 0


def main() -> int:
    configure_utf8_console()
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop-file", required=True)
    parser.add_argument(
        "--single-engine",
        action="store_true",
        help="Yalnızca Binance analiz motorunu çalıştır; BtcTurk verisini yalnızca yerel sembol listesi olarak kullan.",
    )
    args = parser.parse_args()
    return BinanceRadar(args.stop_file, single_engine=args.single_engine).run()


if __name__ == "__main__":
    raise SystemExit(main())
