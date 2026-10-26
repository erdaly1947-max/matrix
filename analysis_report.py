"""Compact, compressed analysis reports for the Fırsat-Kontrol Paneli.

This module intentionally excludes engine diagnostics and raw candle archives.
It preserves candidate decisions, scoring, technical evidence, selected indicator
metrics, BTC context, and conditional entry/stop/target plans.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

CONFIG_NAME = "chatgpt_baglanti.local.json"
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
TIMEFRAME_ORDER = ("5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M")

METRIC_FIELDS = (
    "candle_start_ms", "close_time_ms", "close",
    "one_bar_change_pct", "three_bar_change_pct", "positive_return_z",
    "current_volume", "volume_q60_history", "volume_q75_history",
    "volume_measurement_source", "volume_history_complete", "volume_history_sample_count",
    "current_volume_valid", "volume_persistence_history_complete", "recent_volume_window_complete",
    "volume_early", "volume_unusual", "volume_persistence_count",
    "directional_structure", "breakout_level", "previous_resistance",
    "previous_support", "typical_candle_range", "distance_to_resistance_typical_range",
    "distance_to_resistance_atr", "compression_ratio", "compression", "rising_lows",
    "near_resistance", "continuity", "continuity_volume_confirmed", "retest_hold",
    "ema_fast_period", "ema_slow_period", "ema_fast", "ema_slow", "ema_bullish",
    "ema_fast_slope_up", "ema_slow_slope_up", "price_above_ema_fast", "price_above_ema_slow",
    "ema_confirmed_bullish", "ema_cross_up", "macd_fast_period", "macd_slow_period",
    "macd_signal_period", "macd_line", "macd_signal", "macd_histogram", "macd_histogram_rising",
    "rsi_period", "rsi_14", "rsi_zone", "atr_period", "atr_14", "adx_period",
    "plus_di_14", "minus_di_14", "adx_14", "dmi_direction", "trend_direction",
    "confirmed_pivot_count", "support_level", "resistance_level", "nearest_support",
    "nearest_resistance", "fib_support", "fib_resistance", "volume_ratio", "relative_volume",
    "volume_participation", "momentum_score", "trend_score",
)

CANDIDATE_FIELDS = (
    "symbol", "base_asset", "quote_asset", "source", "phase", "state",
    "phase_timeframe", "latest_price", "latest_bar_start_ms", "findings",
    "evidence_groups", "higher_timeframe_context",
    "relative_strength_vs_btc_pct_points", "btc_return_correlation",
    "missing_checks", "source_market_pair", "btcturk_market_pair",
    "category_status", "generated_at_utc", "data_note", "risk_plan",
    "strong_alarm_eligible", "strong_alarm_block_reason", "last_known_phase",
    "data_freshness", "last_stream_update_age_seconds", "opportunity_score",
    "score_0_100", "score_components", "btc_correlation_assessment",
    "final_decision", "decision_class", "decision_reason",
    "strong_opportunity_qualified", "strong_opportunity_gate_reasons",
    "group_category", "group_category_verified", "group_category_source",
    "group_comparable_count", "group_leadership_score", "group_leadership_basis",
    "group_leadership_summary", "liquidity_assessment",
)

def _copy_known(source: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    return {key: source[key] for key in fields if key in source}

def _compact_timeframes(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for timeframe in TIMEFRAME_ORDER:
        row = value.get(timeframe)
        if not isinstance(row, dict):
            continue
        compact = _copy_known(
            row,
            ("timeframe", "phase", "state", "data_sufficient", "history_contiguous",
             "closed_bars", "required_closed_bars", "findings", "missing_checks",
             "evidence_groups"),
        )
        metrics = row.get("metrics")
        if isinstance(metrics, dict):
            selected = {
                key: metrics[key]
                for key in METRIC_FIELDS
                if key in metrics and not isinstance(metrics[key], (dict, list, tuple, set))
            }
            fib = metrics.get("fibonacci_levels")
            if isinstance(fib, dict):
                selected["fibonacci_levels"] = {
                    str(k): v for k, v in list(fib.items())[:20]
                    if isinstance(v, (str, int, float, bool)) or v is None
                }
            # Preserve bounded, decision-relevant nested structures from the real engine schema.
            zones = metrics.get("support_resistance_zones")
            if isinstance(zones, list):
                compact_zones = []
                zone_fields = (
                    "kind", "center", "lower", "upper", "touch_count", "strong",
                    "first_touch_ms", "last_touch_ms", "pivot_count", "timeframe",
                )
                for zone in zones[:16]:
                    if isinstance(zone, dict):
                        compact_zone = _copy_known(zone, zone_fields)
                        if compact_zone:
                            compact_zones.append(compact_zone)
                if compact_zones:
                    selected["support_resistance_zones"] = compact_zones

            channel = metrics.get("confirmed_channel")
            if isinstance(channel, dict):
                compact_channel = _copy_known(
                    channel,
                    (
                        "status", "available", "direction", "upper_now", "lower_now",
                        "upper_slope_per_bar", "lower_slope_per_bar", "position_0_to_1",
                        "pivot_high_count", "pivot_low_count", "slope_divergence_atr", "timeframe",
                    ),
                )
                if compact_channel:
                    selected["confirmed_channel"] = compact_channel

            fib = metrics.get("fibonacci")
            if isinstance(fib, dict):
                compact_fib = _copy_known(
                    fib,
                    (
                        "status", "available", "direction", "swing_low", "swing_high",
                        "swing_range", "low_timestamp_ms", "high_timestamp_ms", "timeframe",
                    ),
                )
                for nested_name in ("retracements", "extensions"):
                    levels = fib.get(nested_name)
                    if isinstance(levels, dict):
                        compact_fib[nested_name] = {
                            str(key): value for key, value in list(levels.items())[:12]
                            if isinstance(value, (str, int, float, bool)) or value is None
                        }
                if compact_fib:
                    selected["fibonacci"] = compact_fib

            if selected:
                compact["metrics"] = selected
        result[timeframe] = compact
    return result

def _compact_candidate(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        return {}
    result = _copy_known(candidate, CANDIDATE_FIELDS)
    result["timeframes"] = _compact_timeframes(candidate.get("timeframes"))
    # Raw candle arrays and repeated per-coin BTC context are deliberately omitted.
    return result

def build_analysis_report(state: Any) -> dict[str, Any]:
    """Build analysis-only data; no diagnostic payload or raw candle history."""
    if not isinstance(state, dict):
        state = {}
    raw_candidates = state.get("candidates")
    if not isinstance(raw_candidates, list):
        raw_candidates = []
    candidates = [
        compact for item in raw_candidates
        if (compact := _compact_candidate(item))
    ]
    return {
        "report_type": "analysis",
        "schema_version": 1,
        "application": "FIRSAT-KONTROL PANELİ",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_state_generated_at_utc": state.get("generated_at_utc"),
        "application_version": state.get("application_version"),
        "radar": state.get("radar"),
        "source": state.get("source"),
        "universe": {
            key: state.get(key)
            for key in (
                "universe_mode", "common_pair_count", "scan_symbol_count",
                "universe_generated_at_utc", "btcturk_universe_generated_at_utc",
                "btcturk_universe_mode", "universe_warning", "btcturk_universe_warning",
            )
            if key in state
        },
        "market_context": state.get("btc_market_context"),
        "market_context_freshness": state.get("btc_market_context_freshness"),
        "market_context_warning": state.get("btc_market_context_warning"),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "interpretation_limits": [
            "A/B/C araştırma aşamalarıdır; emir veya kârlılık garantisi değildir.",
            "Giriş, stop ve hedefler koşullu teknik senaryolardır.",
            "Komisyon ve kayma hesaplanmaz; otomatik emir gönderilmez.",
        ],
    }

def compress_analysis_report(payload: dict[str, Any]) -> bytes:
    raw = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    if len(compressed) > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"Sıkıştırılmış analiz raporu sınırı aşıyor: {len(compressed)} bayt "
            f"(üst sınır {MAX_UPLOAD_BYTES} bayt)."
        )
    return compressed

def load_connection_config(root: str | Path) -> dict[str, str] | None:
    """Read ignored local credentials; never read secrets from tracked settings."""
    path = Path(root) / CONFIG_NAME
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            config = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(config, dict):
        return None
    upload_url = config.get("upload_url")
    upload_token = config.get("upload_token")
    if not isinstance(upload_url, str) or not isinstance(upload_token, str):
        return None
    parsed = urllib.parse.urlsplit(upload_url)
    if parsed.scheme != "https" or not parsed.netloc or not upload_token.strip():
        return None
    read_url = config.get("read_url", "")
    return {
        "upload_url": upload_url,
        "upload_token": upload_token,
        "read_url": read_url if isinstance(read_url, str) else "",
    }

def upload_analysis_report(config: dict[str, str], compressed: bytes) -> dict[str, Any]:
    """POST gzip JSON over HTTPS with the upload token in an Authorization header."""
    if not isinstance(compressed, bytes) or not compressed:
        raise ValueError("Gönderilecek sıkıştırılmış rapor boş.")
    if len(compressed) > MAX_UPLOAD_BYTES:
        raise ValueError("Sıkıştırılmış rapor boyut sınırını aşıyor.")
    url = config.get("upload_url", "")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Yükleme adresi geçerli bir HTTPS adresi olmalıdır.")
    request = urllib.request.Request(
        url,
        data=compressed,
        method="POST",
        headers={
            "Authorization": f"Bearer {config['upload_token']}",
            "Content-Type": "application/json; charset=utf-8",
            "Content-Encoding": "gzip",
            "Accept": "application/json",
            "User-Agent": "Firsat-Kontrol-Paneli/00",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            response_body = response.read(256 * 1024).decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read(2048).decode("utf-8", errors="replace")
        raise RuntimeError(f"Sunucu HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Sunucu bağlantısı başarısız: {exc}") from exc
    try:
        body_json = json.loads(response_body) if response_body else {}
    except json.JSONDecodeError:
        body_json = {}
    if status < 200 or status >= 300 or body_json.get("ok") is not True:
        raise RuntimeError(body_json.get("error") or f"Sunucu beklenmeyen yanıt verdi (HTTP {status}).")
    return {
        "ok": True,
        "read_url": body_json.get("read_url") or config.get("read_url", ""),
        "candidate_count": body_json.get("candidate_count"),
        "compressed_bytes": len(compressed),
    }
