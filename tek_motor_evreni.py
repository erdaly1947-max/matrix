"""Tek motorlu sürüm için yerel BtcTurk sembol listesi ve Binance ortak evreni.

BtcTurk yalnızca sembol listesinin kaynağıdır. Normal taramada BtcTurk fiyatı,
mum, hacim veya emir defteri verisi çağrılmaz.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ortak_piyasa import (
    BTCTURK_UNIVERSE_CACHE_PATH,
    SETTINGS_PATH,
    fetch_binance_usdt_spot,
    fetch_btcturk_usdt_spot,
)
from radar_core import atomic_json, utc_now

LOCAL_LIST_MAX_AGE_SECONDS = 14 * 24 * 60 * 60
FUTURE_TIMESTAMP_TOLERANCE_SECONDS = 5 * 60
# A separately persisted, previously verified Binance/BtcTurk intersection.
# The BtcTurk source list remains in its own file.
SINGLE_ENGINE_UNIVERSE_CACHE_PATH = BTCTURK_UNIVERSE_CACHE_PATH.parent / "single_engine_common_universe.json"


class NoActiveCachedIntersectionError(RuntimeError):
    """The current verified Binance listing contains none of the cached common pairs."""


def _load_cached_single_engine_pairs(
    cache_path: str | Path | None = None,
    *,
    now_epoch: float | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Load the last persisted common intersection without treating it as freshly verified."""
    path = Path(cache_path) if cache_path is not None else SINGLE_ENGINE_UNIVERSE_CACHE_PATH
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("Kayıtlı ortak evren önbelleğinin kökü nesne değil.")

    generated_at = str(payload.get("generated_at_utc") or "").strip()
    timestamp = _parse_utc(generated_at)
    now = time.time() if now_epoch is None else float(now_epoch)
    raw_age = now - timestamp.timestamp()
    if raw_age < -FUTURE_TIMESTAMP_TOLERANCE_SECONDS:
        raise ValueError("Kayıtlı ortak evren zaman damgası gelecekte; önbellek reddedildi.")

    raw_pairs = payload.get("pairs")
    if not isinstance(raw_pairs, list):
        raise ValueError("Kayıtlı ortak evrende pairs listesi bulunamadı.")

    pairs: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_pairs:
        if not isinstance(item, dict):
            continue
        base = str(item.get("base_asset") or "").strip().upper()
        quote = str(item.get("quote_asset") or "").strip().upper()
        binance_symbol = str(item.get("binance_symbol") or "").strip().upper()
        btcturk_symbol = str(item.get("btcturk_symbol") or "").strip().upper()
        if (
            not base or quote != "USDT"
            or binance_symbol != f"{base}USDT"
            or btcturk_symbol != f"{base}USDT"
            or base in seen
        ):
            continue
        pairs.append({
            "base_asset": base,
            "quote_asset": "USDT",
            "binance_symbol": binance_symbol,
            "btcturk_symbol": btcturk_symbol,
        })
        seen.add(base)

    if not pairs:
        raise ValueError("Kayıtlı ortak evrende doğrulanabilir USDT paritesi yok.")

    return pairs, {
        "generated_at_utc": generated_at,
        "age_seconds": round(max(0.0, raw_age), 1),
        "count": len(pairs),
        "source": str(payload.get("source") or "Son doğrulanmış Binance/BtcTurk ortak evreni"),
        "path": str(path),
    }


def _parse_utc(value: Any) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Yerel BtcTurk listesinde zaman damgası yok.")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _candidate_local_list_paths(cache_path: str | Path | None = None) -> list[Path]:
    """Find the current cache first, then compatible caches beside older portable installs."""
    if cache_path is not None:
        # An explicit path is deterministic and is primarily used by offline tests.
        return [Path(cache_path)]

    primary = Path(BTCTURK_UNIVERSE_CACHE_PATH)
    root = primary.parent.parent
    candidates = [
        primary,
        # Accept the checked-in starter list at the project root when data/ is new.
        root / primary.name,
        primary.parent / "common_universe.json",
        root.parent / "data" / primary.name,
        root.parent / "data" / "common_universe.json",
        Path.cwd() / "data" / primary.name,
        Path.cwd() / "data" / "common_universe.json",
    ]
    # Portable upgrades are sometimes extracted beside, rather than over, the old folder.
    try:
        for sibling in sorted(root.parent.iterdir(), key=lambda item: item.name.casefold()):
            if sibling == root or not sibling.is_dir():
                continue
            name = sibling.name.casefold()
            if not any(token in name for token in ("firsat", "radar", "surum", "version")):
                continue
            candidates.extend((
                sibling / "data" / primary.name,
                sibling / "data" / "common_universe.json",
            ))
    except OSError:
        pass

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve(strict=False)).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def load_local_btcturk_symbols(
    cache_path: str | Path | None = None,
    *,
    now_epoch: float | None = None,
) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    """Load a saved BtcTurk list or a historical common-universe cache without network access."""
    errors: list[str] = []
    for path in _candidate_local_list_paths(cache_path):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("kök JSON nesnesi bekleniyordu.")

            raw_symbols = payload.get("symbols")
            raw_pairs = payload.get("pairs")
            legacy = path.name.casefold() == "common_universe.json" or not isinstance(raw_symbols, dict)
            symbols: dict[str, dict[str, str]] = {}
            legacy_pairs: list[dict[str, str]] = []

            if isinstance(raw_symbols, dict):
                for raw_base, raw_item in raw_symbols.items():
                    if not isinstance(raw_item, dict):
                        continue
                    base = str(raw_base).strip().upper()
                    symbol = str(raw_item.get("symbol") or "").strip().upper()
                    quote = str(raw_item.get("quote") or "").strip().upper()
                    item_base = str(raw_item.get("base") or base).strip().upper()
                    if base and base == item_base and quote == "USDT" and symbol == f"{base}USDT":
                        symbols[base] = {"base": base, "quote": "USDT", "symbol": symbol}
                        legacy_pairs.append({
                            "base_asset": base, "quote_asset": "USDT",
                            "binance_symbol": f"{base}USDT", "btcturk_symbol": symbol,
                        })
            elif isinstance(raw_pairs, list):
                # Older releases persisted only the Binance/BtcTurk intersection.
                for item in raw_pairs:
                    if not isinstance(item, dict):
                        continue
                    base = str(item.get("base_asset") or "").strip().upper()
                    quote = str(item.get("quote_asset") or "").strip().upper()
                    btcturk_symbol = str(item.get("btcturk_symbol") or "").strip().upper()
                    binance_symbol = str(item.get("binance_symbol") or f"{base}USDT").strip().upper()
                    if (base and quote == "USDT" and btcturk_symbol == f"{base}USDT"
                            and binance_symbol == f"{base}USDT"):
                        symbols[base] = {"base": base, "quote": "USDT", "symbol": btcturk_symbol}
                        legacy_pairs.append({
                            "base_asset": base, "quote_asset": "USDT",
                            "binance_symbol": binance_symbol, "btcturk_symbol": btcturk_symbol,
                        })
            else:
                raise ValueError("symbols veya uyumlu eski pairs listesi bulunamadı.")

            if not symbols:
                raise ValueError("geçerli USDT Spot paritesi bulunamadı.")

            generated_at = str(payload.get("generated_at_utc") or payload.get("generated_at") or "").strip()
            if not generated_at and legacy:
                generated_at = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat(timespec="seconds")
            timestamp = _parse_utc(generated_at)
            now = time.time() if now_epoch is None else float(now_epoch)
            raw_age = now - timestamp.timestamp()
            if raw_age < -FUTURE_TIMESTAMP_TOLERANCE_SECONDS:
                raise ValueError(
                    "Yerel parite kaydı bilgisayar saatine göre gelecekte oluşturulmuş görünüyor; "
                    "zaman damgası doğrulanamadığı için liste reddedildi."
                )
            age = max(0.0, raw_age)

            active_status_verified = (
                payload.get("active_status_verified") is True
                and not legacy
                and age <= LOCAL_LIST_MAX_AGE_SECONDS
            )
            if legacy:
                cache_kind = "LEGACY_COMMON_UNIVERSE_CACHE"
                default_source = "Tarihsel eski Binance/BtcTurk ortak evren kaydı"
                warning = (
                    "Tarihsel ortak evren kaydı kullanılıyor; BtcTurk aktif işlem durumu bugün için "
                    "doğrulanmış değil. Güncel fiyat/mum verisi ayrıca doğrulanmadan fırsat veya güçlü "
                    "alarm üretilemez."
                )
            else:
                cache_kind = "BTCTURK_UNIVERSE_CACHE"
                default_source = "Yerel BtcTurk USDT Spot listesi"
                warning = None

            if age > LOCAL_LIST_MAX_AGE_SECONDS:
                age_warning = (
                    f"Kaydedilmiş parite listesi 14 günden eski (yaş {age / 86400:.1f} gün); "
                    "liste tarihsel kabul edilmelidir."
                )
                warning = f"{warning} {age_warning}".strip() if warning else age_warning
            if not active_status_verified:
                verification_warning = (
                    "BtcTurk aktif işlem durumu exchangeInfo üzerinden doğrulanmamış; "
                    "güçlü fırsat alarmları kapalı."
                )
                if verification_warning not in (warning or ""):
                    warning = f"{warning} {verification_warning}".strip() if warning else verification_warning

            return symbols, {
                "generated_at_utc": generated_at,
                "age_seconds": round(age, 1),
                "count": len(symbols),
                "source": str(payload.get("source") or default_source),
                "path": str(path),
                "cache_kind": cache_kind,
                "legacy_cache": legacy,
                "legacy_pairs": legacy_pairs if legacy else [],
                "active_status_verified": active_status_verified,
                "warning": warning,
            }
        except Exception as exc:
            errors.append(f"{path}: {type(exc).__name__}: {exc}")

    detail = " | ".join(errors) if errors else "uyumlu kayıt yolu bulunamadı"
    raise ValueError(
        "Yerel BtcTurk USDT parite listesi bulunamadı veya okunamadı. "
        "Panelde 'Parite listesini güncelle' düğmesini kullanın. "
        f"Denetlenen kayıtlar: {detail}"
    )


def build_single_engine_universe(
    cache_path: str | Path | None = None,
    *,
    now_epoch: float | None = None,
    binance_symbols: dict[str, dict[str, str]] | None = None,
    settings: dict[str, Any] | None = None,
    universe_cache_path: str | Path | None = None,
) -> dict[str, Any]:
    """Canlı Binance sembollerini yerel BtcTurk listesiyle kesiştirir."""
    cache_universe_path = (
        Path(universe_cache_path)
        if universe_cache_path is not None
        else SINGLE_ENGINE_UNIVERSE_CACHE_PATH
    )
    should_persist_universe = (
        universe_cache_path is not None
        or (cache_path is None and binance_symbols is None)
    )
    cached_universe_meta: dict[str, Any] | None = None
    binance_source_verified = True
    binance_fetch_error: str | None = None
    binance = binance_symbols
    force_cached_common_universe = False

    try:
        btcturk_symbols, local_meta = load_local_btcturk_symbols(
            cache_path, now_epoch=now_epoch
        )
    except Exception as local_list_error:
        # If the source list itself is unavailable, the last verified intersection is
        # the only safe fallback. Do not rebuild a universe from Binance-only symbols.
        try:
            cached_pairs, cached_universe_meta = _load_cached_single_engine_pairs(
                cache_universe_path, now_epoch=now_epoch
            )
        except Exception as cache_error:
            raise RuntimeError(
                "Yerel BtcTurk sembol listesi okunamadı ve kullanılabilir son doğrulanmış "
                "ortak evren önbelleği de yok; tarama başlatılmamalı. "
                f"BtcTurk listesi: {type(local_list_error).__name__}: {local_list_error}; "
                f"ortak evren önbelleği: {type(cache_error).__name__}: {cache_error}"
            ) from local_list_error

        force_cached_common_universe = True
        btcturk_symbols = {
            item["base_asset"]: {
                "base": item["base_asset"],
                "quote": "USDT",
                "symbol": item["btcturk_symbol"],
            }
            for item in cached_pairs
        }
        local_meta = {
            "generated_at_utc": cached_universe_meta["generated_at_utc"],
            "age_seconds": cached_universe_meta["age_seconds"],
            "count": cached_universe_meta["count"],
            "source": "Son doğrulanmış Binance/BtcTurk ortak evren önbelleği",
            "path": cached_universe_meta["path"],
            "cache_kind": "CACHED_COMMON_UNIVERSE",
            "legacy_cache": False,
            "legacy_pairs": [],
            "active_status_verified": False,
            "warning": (
                "Yerel BtcTurk aktif USDT Spot sembol listesi okunamadı; yeni BtcTurk listesi "
                "çekilmeden yalnızca önceki ortak evrende bulunan pariteler korunuyor. "
                "Kaynak önbelleği "
                f"({cached_universe_meta['generated_at_utc']}, "
                f"{cached_universe_meta['age_seconds'] / 86400.0:.1f} gün). "
                "BtcTurk aktiflik doğrulaması olmadığı için güçlü fırsat alarmları kapalı. "
                f"Kaynak liste hatası: {type(local_list_error).__name__}: {local_list_error}"
            ),
        }
        if binance_symbols is None:
            try:
                live_binance = fetch_binance_usdt_spot()
                if not isinstance(live_binance, dict) or not live_binance:
                    raise RuntimeError("Binance aktif USDT Spot parite listesi boş döndü.")
                binance = live_binance
                binance_source_verified = True
                local_meta["warning"] += (
                    " Binance aktif USDT Spot listesi güncel alındı; tarama yalnızca önceki "
                    "ortak evren ile bu listenin kesişiminde sürdürülecek."
                )
            except Exception as binance_error:
                binance_source_verified = False
                binance_fetch_error = f"{type(binance_error).__name__}: {binance_error}"
                binance = {
                    item["base_asset"]: {
                        "base": item["base_asset"],
                        "quote": "USDT",
                        "symbol": item["binance_symbol"],
                    }
                    for item in cached_pairs
                }
                local_meta["warning"] += (
                    " Binance aktif sembol listesi de doğrulanamadı; son ortak evren "
                    "önbelleği geçici ve doğrulanmamış yedek olarak korunuyor. "
                    f"Binance hatası: {binance_fetch_error[:300]}"
                )
        else:
            # A caller-supplied symbol map is current input for deterministic/offline use;
            # it still cannot introduce any pair outside the last saved intersection.
            binance = binance_symbols
            if not isinstance(binance, dict) or not binance:
                binance_source_verified = False
                binance_fetch_error = "Verilen Binance USDT Spot sembol haritası boş/geçersiz."
                binance = {
                    item["base_asset"]: {
                        "base": item["base_asset"],
                        "quote": "USDT",
                        "symbol": item["binance_symbol"],
                    }
                    for item in cached_pairs
                }
            else:
                binance_source_verified = True
                local_meta["warning"] += (
                    " Verilen Binance aktif USDT Spot listesi kullanılıyor; tarama önceki ortak "
                    "evren ile bu listenin kesişimiyle sınırlandırılacak."
                )

    if not force_cached_common_universe and binance_symbols is None:
        try:
            binance = fetch_binance_usdt_spot()
            if not isinstance(binance, dict) or not binance:
                raise RuntimeError("Binance aktif USDT Spot parite listesi boş döndü.")
        except Exception as exc:
            binance_source_verified = False
            binance_fetch_error = f"{type(exc).__name__}: {exc}"
            try:
                cached_pairs, cached_universe_meta = _load_cached_single_engine_pairs(
                    cache_universe_path, now_epoch=now_epoch
                )
            except Exception as cache_error:
                if local_meta.get("legacy_cache") and local_meta.get("legacy_pairs"):
                    # Compatibility path for older releases; this cache is explicitly unverified.
                    cached_pairs = [
                        item for item in local_meta["legacy_pairs"]
                        if isinstance(item, dict)
                        and str(item.get("base_asset") or "").strip()
                        and str(item.get("quote_asset") or "").upper() == "USDT"
                        and str(item.get("binance_symbol") or "").upper()
                            == f"{str(item.get('base_asset') or '').upper()}USDT"
                        and str(item.get("btcturk_symbol") or "").upper()
                            == f"{str(item.get('base_asset') or '').upper()}USDT"
                    ]
                    if not cached_pairs:
                        raise RuntimeError(
                            "Eski ortak evren önbelleğinde kullanılabilir USDT paritesi yok; "
                            "tarama başlatılmamalı."
                        ) from exc
                    binance = {
                        str(item["base_asset"]).upper(): {
                            "base": str(item["base_asset"]).upper(),
                            "quote": "USDT",
                            "symbol": str(item["binance_symbol"]).upper(),
                        }
                        for item in cached_pairs
                    }
                    btcturk_symbols = {
                        str(item["base_asset"]).upper(): {
                            "base": str(item["base_asset"]).upper(),
                            "quote": "USDT",
                            "symbol": str(item["btcturk_symbol"]).upper(),
                        }
                        for item in cached_pairs
                    }
                    local_meta = dict(local_meta)
                    local_meta["warning"] = (
                        f"{local_meta.get('warning') or ''} Binance güncel sembol evreni "
                        "doğrulanamadı; yalnızca tarihsel ortak evren yedeği kullanılmaktadır. "
                        "Güçlü fırsat alarmları kapalı."
                    ).strip()
                else:
                    raise RuntimeError(
                        "Binance aktif USDT Spot parite evreni doğrulanamadı. "
                        "BtcTurk sembol listesi tek başına ortak tarama evreni oluşturamaz; "
                        "son geçerli ortak evren önbelleği bulunamadığı için tarama başlatılmamalı. "
                        f"Binance hatası: {binance_fetch_error}; ortak evren önbelleği: {cache_error}"
                    ) from exc
            else:
                # Reuse only the saved intersection; do not expand it into a Binance-only
                # universe or into every pair currently present in the local BtcTurk list.
                binance = {
                    item["base_asset"]: {
                        "base": item["base_asset"],
                        "quote": "USDT",
                        "symbol": item["binance_symbol"],
                    }
                    for item in cached_pairs
                }
                btcturk_symbols = {
                    item["base_asset"]: {
                        "base": item["base_asset"],
                        "quote": "USDT",
                        "symbol": item["btcturk_symbol"],
                    }
                    for item in cached_pairs
                }
                cached_count = len(cached_pairs)
                local_meta = dict(local_meta)
                prior_warning = str(local_meta.get("warning") or "").strip()
                cache_warning = (
                    "Binance güncel sembol evreni doğrulanamadı; önceki doğrulanmış "
                    f"ortak evren önbelleği ({cached_universe_meta['generated_at_utc']}, "
                    f"{cached_universe_meta['age_seconds'] / 86400.0:.1f} gün; "
                    f"{cached_count} parite) yedek olarak kullanılıyor. "
                    "Güçlü fırsat alarmları bu durumda kapalıdır."
                )
                local_meta["warning"] = f"{prior_warning} {cache_warning}".strip()
    settings_path = Path(SETTINGS_PATH)
    settings_file_exists: bool | None = None
    settings_file_size_bytes: int | None = None
    settings_modified_at_utc: str | None = None
    settings_sha256: str | None = None
    settings_parse_error: str | None = None
    if settings is None:
        cfg: dict[str, Any] = {}
        config_readable = False
        settings_file_exists = settings_path.is_file()
        settings_parse_status = "NOT_READ"
        try:
            settings_bytes = settings_path.read_bytes()
            settings_file_exists = True
            settings_file_size_bytes = len(settings_bytes)
            settings_sha256 = hashlib.sha256(settings_bytes).hexdigest()
            stat = settings_path.stat()
            settings_modified_at_utc = datetime.fromtimestamp(
                stat.st_mtime, timezone.utc
            ).isoformat(timespec="seconds")
            cfg_value = json.loads(settings_bytes.decode("utf-8-sig"))
            if isinstance(cfg_value, dict):
                cfg = cfg_value
                config_readable = True
                settings_parse_status = "OK"
            else:
                settings_parse_status = "ROOT_NOT_OBJECT"
                settings_parse_error = "JSON kökü bir nesne/sözlük değil."
        except FileNotFoundError:
            settings_parse_status = "MISSING"
            settings_parse_error = "ayarlar.json dosyası bulunamadı."
        except UnicodeDecodeError as exc:
            settings_parse_status = "INVALID_ENCODING"
            settings_parse_error = f"{type(exc).__name__}: {exc}"[:300]
        except json.JSONDecodeError as exc:
            settings_parse_status = "INVALID_JSON"
            settings_parse_error = (
                f"{exc.msg} (satır {exc.lineno}, sütun {exc.colno})"
            )[:300]
        except OSError as exc:
            settings_parse_status = "READ_ERROR"
            settings_parse_error = f"{type(exc).__name__}: {exc}"[:300]
    else:
        cfg = settings
        config_readable = isinstance(settings, dict)
        settings_parse_status = (
            "EXPLICIT_SETTINGS" if config_readable else "EXPLICIT_SETTINGS_INVALID"
        )
        if not config_readable:
            settings_parse_error = "Çağıran işlev geçerli bir sözlük sağlamadı."

    def _is_text_list(value: Any) -> bool:
        return isinstance(value, list) and bool(value) and all(
            isinstance(item, str) and bool(item.strip()) for item in value
        )

    raw_fan_tokens = cfg.get("fan_token_bases_to_skip") if config_readable else None
    raw_stablecoins = cfg.get("stablecoin_bases_no_strong_alarm") if config_readable else None
    fan_filter_valid = config_readable and _is_text_list(raw_fan_tokens)
    stablecoin_filter_valid = config_readable and _is_text_list(raw_stablecoins)
    excluded_bases = {
        item.strip().upper() for item in raw_fan_tokens
        if isinstance(item, str) and item.strip()
    } if fan_filter_valid else set()
    stablecoin_bases = {
        item.strip().upper() for item in raw_stablecoins
        if isinstance(item, str) and item.strip()
    } if stablecoin_filter_valid else set()
    # A legacy local list without source-status proof can be scanned, but must not trigger strong alerts.
    active_status_verified = local_meta.get("active_status_verified") is True
    alert_filter_warnings = []
    if not fan_filter_valid:
        alert_filter_warnings.append(
            "Fan token dışlama listesi okunamadı veya geçersiz; dışlama uygulanmış sayılmıyor ve güçlü alarmlar kapalı."
        )
    if not stablecoin_filter_valid:
        alert_filter_warnings.append(
            "Sabit değerli varlık listesi okunamadı veya geçersiz; bu nedenle güçlü fırsat alarmları kapalı."
        )
    alert_filter_warning = " ".join(alert_filter_warnings)
    pairs: list[dict[str, Any]] = []
    exclusions: dict[str, str] = {}
    for base in sorted(set(binance).intersection(btcturk_symbols)):
        if base in excluded_bases:
            exclusions[base] = "Yapılandırılmış fan token dışlama listesi"
            continue
        b = binance[base]
        t = btcturk_symbols[base]
        if (
            not isinstance(b, dict)
            or str(b.get("base") or base).upper() != base
            or str(b.get("quote") or "USDT").upper() != "USDT"
            or str(b.get("symbol") or "").upper() != f"{base}USDT"
            or t["symbol"] != f"{base}USDT"
        ):
            continue
        stablecoin_base = base in stablecoin_bases
        strong_eligible = (binance_source_verified and active_status_verified
                           and fan_filter_valid and stablecoin_filter_valid and not stablecoin_base)
        if not fan_filter_valid:
            category_status = "Fan token dışlama listesi doğrulanamadı; filtre uygulanmamış sayılıyor."
        else:
            category_status = "Fan token dışlama listesi doğrulandı; diğer kategoriler bağımsız doğrulanmadı."
        if stablecoin_base:
            category_status += " Sabit değerli varlık: güçlü alarm uygun değil."
        if not active_status_verified:
            category_status += " BtcTurk aktif işlem durumu doğrulanmadı."
        block_reasons = []
        if not fan_filter_valid:
            block_reasons.append("Fan token dışlama listesi doğrulanamadı")
        if not stablecoin_filter_valid:
            block_reasons.append("Sabit değerli varlık listesi doğrulanamadı")
        if stablecoin_base:
            block_reasons.append("Sabit değerli varlık; güçlü momentum alarmı kapalı")
        if not active_status_verified:
            block_reasons.append("BtcTurk aktif işlem durumu doğrulanmadı; güçlü alarm kapalı")
        pairs.append({
            "base_asset": base,
            "quote_asset": "USDT",
            "binance_symbol": f"{base}USDT",
            "btcturk_symbol": t["symbol"],
            "identity_match": "LOCAL_BTCTURK_BASE_AND_QUOTE_MATCH",
            "category_status": category_status,
            "stablecoin_base": stablecoin_base,
            "strong_alarm_eligible": strong_eligible,
            "strong_alarm_block_reason": "; ".join(block_reasons) or None,
        })

    if not pairs:
        if force_cached_common_universe and binance_source_verified:
            raise NoActiveCachedIntersectionError(
                "Güncel Binance aktif USDT Spot listesinde son doğrulanmış ortak evrenden "
                "hiçbir parite kalmadı. Eski pariteler taranmaya devam edilmeyecek; "
                "BtcTurk listesini panelden güncelleyip motoru yeniden başlatın."
            )
        raise RuntimeError(
            "Yerel BtcTurk listesi ile Binance'in aktif Spot USDT pariteleri arasında "
            "tarama yapılabilecek ortak parite bulunamadı."
        )

    active_status_verified = local_meta.get("active_status_verified") is True
    if not active_status_verified:
        alert_filter_warnings.append(
            "Yerel BtcTurk parite listesinin aktif işlem durumu doğrulanmadı; güçlü fırsat alarmları kapalı."
        )
    alert_filter_warning = " ".join(alert_filter_warnings)
    warning_parts = [part for part in (local_meta.get("warning"), alert_filter_warning) if part]
    if binance_fetch_error:
        warning_parts.append(
            "Binance güncel Spot sembol evreni alınamadı; kayıtlı sembol listesi geçici kaynak olarak kullanılıyor. "
            "Güçlü alarm için fiyat/mum ve WebSocket tazeliği ayrıca doğrulanmalıdır. Hata: "
            + binance_fetch_error[:350]
        )
    warning = " ".join(warning_parts) or None
    if force_cached_common_universe:
        universe_mode = "CACHED_LAST_VERIFIED_COMMON_UNIVERSE"
        source = (
            "Son doğrulanmış Binance/BtcTurk ortak evreni; "
            "güncel Binance listesiyle kesişim yapıldı" if binance_source_verified else
            "Son doğrulanmış Binance/BtcTurk ortak evren önbelleği; Binance/BtcTurk güncelliği yeniden doğrulanmadı"
        )
    elif not binance_source_verified and cached_universe_meta is not None:
        universe_mode = "CACHED_LAST_VERIFIED_COMMON_UNIVERSE"
        source = "Son doğrulanmış Binance/BtcTurk ortak evren önbelleği; güncellik yeniden doğrulanmadı"
    elif not binance_source_verified:
        universe_mode = "CACHED_BINANCE_SYMBOL_FALLBACK"
        source = "Tarihsel kayıtlı ortak evren; Binance güncel sembol evreni doğrulanamadı"
    elif local_meta.get("legacy_cache"):
        universe_mode = "CACHED_LEGACY_UNIVERSE"
        source = "Binance Spot exchangeInfo + tarihsel eski ortak evren kaydı"
    else:
        universe_mode = "SINGLE_ENGINE_LOCAL_LIST"
        source = "Binance Spot exchangeInfo + yerel kaydedilmiş BtcTurk USDT parite listesi"
    result = {
        "generated_at_utc": utc_now(),
        "source": source,
        "universe_mode": universe_mode,
        "binance_universe_source_verified": binance_source_verified,
        "local_list_generated_at_utc": local_meta["generated_at_utc"],
        "local_list_age_seconds": local_meta["age_seconds"],
        "local_list_source": local_meta["source"],
        "local_list_cache_kind": local_meta["cache_kind"],
        "local_list_legacy": local_meta["legacy_cache"],
        "btcturk_universe_mode": "LOCAL_SAVED_LIST",
        "btcturk_universe_generated_at_utc": local_meta["generated_at_utc"],
        "btcturk_universe_age_seconds": local_meta["age_seconds"],
        "btcturk_universe_count": local_meta["count"],
        "btcturk_list_active_status_verified": active_status_verified,
        "btcturk_universe_warning": warning,
        "btcturk_active_usdt_count": local_meta["count"],
        "binance_active_usdt_count": len(binance) if binance_source_verified else None,
        "common_pair_count_before_local_exclusions": len(set(binance).intersection(btcturk_symbols)),
        "excluded_common_assets": exclusions,
        "fan_token_filter_valid": fan_filter_valid,
        "stablecoin_filter_valid": stablecoin_filter_valid,
        "fan_token_list_count": len(raw_fan_tokens) if fan_filter_valid else None,
        "stablecoin_list_count": len(raw_stablecoins) if stablecoin_filter_valid else None,
        "settings_path": str(settings_path.resolve(strict=False)) if settings is None else None,
        "settings_file_exists": settings_file_exists,
        "settings_file_size_bytes": settings_file_size_bytes,
        "settings_modified_at_utc": settings_modified_at_utc,
        "settings_sha256": settings_sha256,
        "settings_parse_status": settings_parse_status,
        "settings_parse_error": settings_parse_error,
        "strong_alerts_enabled": (binance_source_verified and active_status_verified
                                  and fan_filter_valid and stablecoin_filter_valid),
        "alert_filter_warning": alert_filter_warning,
        "stablecoin_base_count_in_scan": sum(1 for pair in pairs if pair["stablecoin_base"]),
        "common_pair_count": len(pairs),
        "scan_symbol_count": len(pairs),
        "single_engine_universe_cache_path": str(cache_universe_path),
        "single_engine_universe_cache_generated_at_utc": (
            cached_universe_meta.get("generated_at_utc") if cached_universe_meta else None
        ),
        "single_engine_universe_cache_age_seconds": (
            cached_universe_meta.get("age_seconds") if cached_universe_meta else None
        ),
        "single_engine_universe_cache_warning": (
            local_meta.get("warning") if cached_universe_meta else None
        ),
        "pairs": pairs,
        "warning": warning,
    }
    # Refresh this cache only after a live Binance symbol universe has been validated.
    # Failure to save diagnostics must not invalidate the current in-memory universe.
    if (should_persist_universe and binance_source_verified
            and local_meta.get("active_status_verified") is True):
        try:
            atomic_json(cache_universe_path, {
                "schema_version": 1,
                "generated_at_utc": result["generated_at_utc"],
                "source": "Binance Spot exchangeInfo + BtcTurk exchangeInfo verified intersection",
                "pairs": [
                    {
                        "base_asset": pair["base_asset"],
                        "quote_asset": pair["quote_asset"],
                        "binance_symbol": pair["binance_symbol"],
                        "btcturk_symbol": pair["btcturk_symbol"],
                    }
                    for pair in pairs
                ],
            })
            result["single_engine_universe_cache_generated_at_utc"] = result["generated_at_utc"]
            result["single_engine_universe_cache_age_seconds"] = 0
            result["single_engine_universe_cache_warning"] = None
        except Exception as cache_write_error:
            cache_write_warning = (
                "Güncel ortak evren bellekte hazır, ancak son geçerli evren diske kaydedilemedi: "
                f"{type(cache_write_error).__name__}: {cache_write_error}"
            )
            result["single_engine_universe_cache_warning"] = cache_write_warning
            result["warning"] = " ".join(
                value for value in (result.get("warning"), cache_write_warning) if value
            )
    return result


def update_local_btcturk_list(
    cache_path: str | Path | None = None,
    *,
    fetcher: Callable[[], dict[str, dict[str, str]]] | None = None,
) -> dict[str, Any]:
    """Kullanıcının düğme ile istediği liste güncellemesini gerçekleştirir."""
    path = Path(cache_path) if cache_path is not None else BTCTURK_UNIVERSE_CACHE_PATH
    request_symbols = (
        (lambda: fetch_btcturk_usdt_spot(allow_unverified_cache=False))
        if fetcher is None else fetcher
    )
    symbols = request_symbols()
    if not isinstance(symbols, dict) or not symbols:
        raise RuntimeError("BtcTurk API geçerli USDT Spot sembol listesi döndürmedi.")
    if any(
        isinstance(item, dict)
        and item.get("pair_status") == "TICKER_SNAPSHOT_FALLBACK_NOT_EXCHANGEINFO_VERIFIED"
        for item in symbols.values()
    ):
        raise RuntimeError(
            "BtcTurk exchangeInfo doğrulaması alınamadı; ticker yedeği aktif işlem durumunu "
            "kanıtlamadığı için yerel liste güncellenmedi ve önceki kayıt korundu."
        )

    normalized: dict[str, dict[str, str]] = {}
    for raw_base, raw_item in symbols.items():
        if not isinstance(raw_item, dict):
            continue
        base = str(raw_base).strip().upper()
        symbol = str(raw_item.get("symbol") or "").strip().upper()
        quote = str(raw_item.get("quote") or "").strip().upper()
        item_base = str(raw_item.get("base") or base).strip().upper()
        if base and item_base == base and quote == "USDT" and symbol == f"{base}USDT":
            normalized[base] = {"base": base, "quote": "USDT", "symbol": symbol}

    if not normalized:
        raise RuntimeError("BtcTurk liste yanıtında doğrulanabilir USDT Spot paritesi yok.")

    payload = {
        "generated_at_utc": utc_now(),
        "source": "BtcTurk exchangeInfo — aktif TRADING USDT Spot pariteleri",
        "active_status_verified": True,
        "symbols": normalized,
    }
    atomic_json(path, payload)
    return {
        "path": str(path),
        "generated_at_utc": payload["generated_at_utc"],
        "count": len(normalized),
        "source": payload["source"],
        "active_status_verified": True,
    }
