"""BtcTurk Spot ve Binance Spot ortak, güncel ve aktif USDT parite evreni.

Coin listesi sabit değildir. Yalnızca kamuya açık piyasa uç noktaları kullanılır.
Bir API başarısız olursa eski evren güncelmiş gibi kullanılmaz.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import logging
import shutil
import subprocess
import sys
from typing import Any
import json
import hashlib
import csv
import os
import socket
import ssl
import threading
import time
import urllib.request
from urllib.parse import urlsplit
import requests

from radar_core import ROOT
SETTINGS_PATH = ROOT / "ayarlar.json"
BINANCE_REST_BASES = (
    # Public market-data endpoint is attempted early because it is specifically intended for public market data.
    "https://data-api.binance.vision",
    "https://api.binance.com",
    "https://api-gcp.binance.com",
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
)
BTCTURK_EXCHANGE_INFO = "https://api.btcturk.com/api/v2/server/exchangeinfo"
BTCTURK_UNIVERSE_CACHE_PATH = ROOT / "data" / "btcturk_usdt_spot.json"
_active_binance_rest_base: str | None = None
_binance_base_lock = threading.Lock()
_btcturk_cache_lock = threading.Lock()
USER_AGENT = "IkiRadarliSpotTrade/1.1 (public-market-data-only; no-account-access)"


def load_settings_snapshot(
    path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load one exact settings-file snapshot and return its bytes' metadata."""
    target = Path(path) if path is not None else SETTINGS_PATH
    metadata: dict[str, Any] = {
        "settings_path": str(target.resolve(strict=False)),
        "settings_file_exists": target.is_file(),
        "settings_file_size_bytes": None,
        "settings_modified_at_utc": None,
        "settings_sha256": None,
        "settings_parse_status": "MISSING",
        "settings_parse_error": None,
    }
    try:
        raw = target.read_bytes()
        stat = target.stat()
        metadata.update({
            "settings_file_exists": True,
            "settings_file_size_bytes": len(raw),
            "settings_modified_at_utc": datetime.fromtimestamp(
                stat.st_mtime, timezone.utc
            ).isoformat(timespec="seconds"),
            "settings_sha256": hashlib.sha256(raw).hexdigest(),
        })
        value = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(value, dict):
            metadata["settings_parse_status"] = "ROOT_NOT_OBJECT"
            metadata["settings_parse_error"] = "JSON kökü bir nesne/sözlük değil."
            return {}, metadata
        metadata["settings_parse_status"] = "OK"
        return value, metadata
    except FileNotFoundError:
        metadata["settings_file_exists"] = False
        metadata["settings_parse_status"] = "MISSING"
        metadata["settings_parse_error"] = "ayarlar.json dosyası bulunamadı."
    except UnicodeDecodeError as exc:
        metadata["settings_parse_status"] = "INVALID_ENCODING"
        metadata["settings_parse_error"] = f"{type(exc).__name__}: {exc}"[:300]
    except json.JSONDecodeError as exc:
        metadata["settings_parse_status"] = "INVALID_JSON"
        metadata["settings_parse_error"] = (
            f"{exc.msg} (satır {exc.lineno}, sütun {exc.colno})"
        )[:300]
    except OSError as exc:
        metadata["settings_parse_status"] = "READ_ERROR"
        metadata["settings_parse_error"] = f"{type(exc).__name__}: {exc}"[:300]
    return {}, metadata


def load_settings() -> dict[str, Any]:
    """Backward-compatible settings loader."""
    settings, _snapshot = load_settings_snapshot()
    return settings



_network_diagnostics_lock = threading.Lock()
_network_diagnostics_cache: dict[str, Any] | None = None


def _safe_proxy_endpoint(value: Any) -> str | None:
    """Summarize a proxy endpoint without exposing credentials, URL paths, or query values."""
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text if "://" in text else f"//{text}"
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return "configured (format not parsed)"
    if not hostname:
        return "configured (format not parsed)"
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    scheme = parsed.scheme.lower() if parsed.scheme else "scheme-unspecified"
    return f"{scheme}://{hostname}" + (f":{port}" if port is not None else "")


def _windows_internet_proxy_flags() -> dict[str, Any]:
    """Read only enable/presence flags from Windows Internet Settings."""
    if not sys.platform.startswith("win"):
        return {"available": False}
    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            def read_value(name: str) -> Any:
                try:
                    return winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    return None

            proxy_enable = read_value("ProxyEnable")
            proxy_server = read_value("ProxyServer")
            auto_config_url = read_value("AutoConfigURL")
            auto_detect = read_value("AutoDetect")
        return {
            "available": True,
            "registry_key_found": True,
            "proxy_enabled": bool(proxy_enable) if proxy_enable is not None else None,
            "proxy_server_configured": bool(str(proxy_server or "").strip()),
            "auto_config_url_configured": bool(str(auto_config_url or "").strip()),
            "auto_detect_enabled": bool(auto_detect) if auto_detect is not None else None,
        }
    except FileNotFoundError:
        return {"available": True, "registry_key_found": False}
    except Exception as exc:
        return {"available": True, "query_error": type(exc).__name__}


def _winhttp_proxy_status() -> str:
    """Return a privacy-safe summary of Windows WinHTTP proxy settings."""
    if not sys.platform.startswith("win"):
        return "not_applicable"
    try:
        executable = shutil.which("netsh")
        if not executable:
            return "netsh_not_found"
        completed = subprocess.run(
            [executable, "winhttp", "show", "proxy"],
            capture_output=True,
            timeout=2.0,
            check=False,
        )
    except Exception as exc:
        # Some unit tests emulate win32 while running on a non-Windows host;
        # diagnostics must never prevent the verified curl fallback from running.
        return f"query_failed:{type(exc).__name__}"
    if completed.returncode != 0:
        return f"query_failed:exit_{completed.returncode}"
    output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace").casefold()
    direct_phrases = (
        ("direct access", "no proxy"),
        ("doğrudan erişim", "proxy sunucusu yok"),
        ("doğrudan erişim", "proxy yok"),
    )
    if any(all(phrase in output for phrase in group) for group in direct_phrases):
        return "direct_no_proxy"
    return "proxy_configured_or_unrecognized"


def _classify_tls_first_response(response: bytes) -> str:
    """Classify initial TCP response bytes without logging content or headers."""
    if not response:
        return "no_data_after_client_hello"
    if response.startswith(b"HTTP/"):
        first_line = response.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        parts = first_line.split()
        status = " ".join(parts[:2]) if len(parts) >= 2 else "HTTP response"
        return f"plain_http_response_instead_of_tls:{status}"
    if (
        len(response) >= 5
        and response[0] in (0x14, 0x15, 0x16, 0x17)
        and response[1] == 0x03
    ):
        return (
            "tls_record_header_received:"
            f"content_type=0x{response[0]:02x}:version=0x{response[1]:02x}{response[2]:02x}"
        )
    return f"non_tls_or_unknown_response:first8_hex={response[:8].hex()}"


def _probe_direct_tls_first_response(host: str, timeout: float = 3.0) -> str:
    """Send a TLS ClientHello directly to TCP/443 and summarize the first response."""
    try:
        with socket.create_connection((host, 443), timeout=timeout) as connection:
            connection.settimeout(timeout)
            incoming = ssl.MemoryBIO()
            outgoing = ssl.MemoryBIO()
            client = ssl.create_default_context().wrap_bio(
                incoming, outgoing, server_side=False, server_hostname=host
            )
            try:
                client.do_handshake()
            except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                pass
            except ssl.SSLError as exc:
                return f"client_hello_creation_failed:{type(exc).__name__}"
            client_hello = outgoing.read()
            if not client_hello:
                return "client_hello_not_generated"
            connection.sendall(client_hello)
            response = connection.recv(512)
            return _classify_tls_first_response(response)
    except socket.timeout:
        return "direct_tcp_443_probe_timeout"
    except Exception as exc:
        return f"direct_tls_probe_failed:{type(exc).__name__}"


def collect_network_diagnostics(*, tls_probe_host: str | None = None) -> dict[str, Any]:
    """Collect privacy-conscious Windows proxy and HTTPS-path diagnostics."""
    global _network_diagnostics_cache
    environment_names = (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    )
    with _network_diagnostics_lock:
        if _network_diagnostics_cache is None:
            try:
                detected_proxies = urllib.request.getproxies()
                proxy_map = {
                    str(name): _safe_proxy_endpoint(value)
                    for name, value in sorted(detected_proxies.items())
                    if value
                }
            except Exception as exc:
                proxy_map = {"diagnostic_error": type(exc).__name__}
            _network_diagnostics_cache = {
                "platform": sys.platform,
                "proxy_environment_keys_present": [
                    name for name in environment_names if os.environ.get(name)
                ],
                "python_effective_proxy_endpoints_redacted": proxy_map,
                "windows_internet_settings": _windows_internet_proxy_flags(),
                "winhttp_proxy_status": _winhttp_proxy_status(),
                "direct_tls_probe_host": None,
                "direct_tls_first_response": None,
            }
        if tls_probe_host and not _network_diagnostics_cache.get("direct_tls_first_response"):
            _network_diagnostics_cache["direct_tls_probe_host"] = tls_probe_host
            _network_diagnostics_cache["direct_tls_first_response"] = (
                _probe_direct_tls_first_response(tls_probe_host)
            )
        return json.loads(json.dumps(_network_diagnostics_cache, ensure_ascii=False))


def _curl_get_fallback(
    url: str, *, params: dict[str, Any] | None,
    timeout: float | tuple[float, float], headers: dict[str, str],
) -> requests.Response:
    """Use Windows' verified curl TLS stack after Python/OpenSSL reports WRONG_VERSION_NUMBER."""
    if not sys.platform.startswith("win"):
        raise RuntimeError("curl.exe TLS yedeği yalnızca Windows üzerinde etkinleştirilir.")
    if not url.lower().startswith("https://"):
        raise ValueError("TLS yedeği yalnızca HTTPS adreslerini kabul eder.")

    executable = shutil.which("curl.exe") or shutil.which("curl")
    if not executable:
        raise RuntimeError("Windows curl.exe bulunamadı; güvenli TLS yedeği kullanılamıyor.")

    prepared = requests.Request("GET", url, params=params, headers=headers).prepare()
    if isinstance(timeout, tuple):
        timeout_seconds = sum(float(value) for value in timeout if value is not None)
    else:
        timeout_seconds = float(timeout)
    timeout_seconds = max(1.0, min(timeout_seconds, 30.0))
    connect_seconds = min(5.0, timeout_seconds)

    # --disable prevents a local curl config from silently changing TLS behavior.
    # Certificate validation remains enabled; never add --insecure/-k here.
    command = [
        executable,
        "--disable",
        "--silent",
        "--show-error",
        "--fail",
        "--location",
        "--connect-timeout", str(connect_seconds),
        "--max-time", str(timeout_seconds),
        "--user-agent", str(headers.get("User-Agent") or USER_AGENT),
        prepared.url,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout_seconds + 2.0,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"curl.exe HTTPS yedeği çalıştırılamadı: {type(exc).__name__}: {exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
        if not detail:
            detail = f"curl.exe çıkış kodu {completed.returncode}"
        raise RuntimeError(f"curl.exe HTTPS yedeği başarısız: {detail[:500]}")

    response = requests.Response()
    response.status_code = 200  # curl --fail returns success only for HTTP success responses.
    response._content = completed.stdout
    response._content_consumed = True
    response.url = prepared.url
    response.encoding = "utf-8"
    response.reason = "OK"
    response.request = prepared
    response.headers["X-Transport-Fallback"] = "curl.exe"
    return response


def _requests_get(url: str, *, params: dict[str, Any] | None,
                  timeout: float | tuple[float, float],
                  headers: dict[str, str]) -> requests.Response:
    """Retry TLS wrong-version failures and diagnose the effective network path."""
    try:
        response = requests.get(url, params=params, timeout=timeout, headers=headers)
        response.raise_for_status()
        return response
    except requests.exceptions.SSLError as first_error:
        message = str(first_error).lower()
        if "wrong_version_number" not in message and "wrong version number" not in message:
            raise
        try:
            configured_proxies = urllib.request.getproxies()
        except Exception:
            configured_proxies = {}
        proxy_note = (
            "Python'ın algıladığı proxy ayarları dışında doğrudan bağlantı denenerek"
            if configured_proxies else "ortam/sistem proxy yolu dışında doğrudan bağlantı denenerek"
        )
        with requests.Session() as direct_session:
            direct_session.trust_env = False
            try:
                response = direct_session.get(url, params=params, timeout=timeout, headers=headers)
                response.raise_for_status()
                return response
            except Exception as direct_error:
                host = urlsplit(url).hostname or "unknown-host"
                diagnostics = collect_network_diagnostics(tls_probe_host=host)
                logging.getLogger(__name__).warning(
                    "TLS bağlantı tanılaması: %s",
                    json.dumps(diagnostics, ensure_ascii=False, sort_keys=True),
                )
                direct_reply = diagnostics.get("direct_tls_first_response") or "probe_not_available"
                if sys.platform.startswith("win"):
                    try:
                        response = _curl_get_fallback(
                            url, params=params, timeout=timeout, headers=headers
                        )
                    except Exception as curl_error:
                        raise RuntimeError(
                            "TLS WRONG_VERSION_NUMBER: {} için varsayılan Python HTTPS, "
                            "{} doğrudan Python HTTPS ve curl.exe yedeği başarısız. "
                            "Doğrudan TCP/443 ilk yanıt tanısı: {}. Windows otomatik proxy/PAC, "
                            "WinHTTP, VPN, güvenlik yazılımı veya ağ filtresi olasılığı araştırılmalı. "
                            "TLS sertifika doğrulaması hiçbir aşamada kapatılmadı. "
                            "Ayrıntılar: ilk hata: {}; doğrudan yeniden deneme: {}; curl.exe: {}."
                            .format(
                                host, proxy_note, direct_reply,
                                first_error, direct_error, str(curl_error)[:500]
                            )
                        ) from curl_error
                    logging.getLogger(__name__).warning(
                        "Python TLS bağlantısı başarısız oldu; %s için sertifika doğrulaması açık "
                        "Windows curl.exe yedeği kullanıldı.", host
                    )
                    return response
                raise RuntimeError(
                    "TLS WRONG_VERSION_NUMBER: {} için varsayılan Python HTTPS ve {} "
                    "yeniden deneme başarısız. Doğrudan TCP/443 ilk yanıt tanısı: {}. "
                    "Proxy/PAC, VPN, güvenlik yazılımı veya ağ filtresi olasılığı araştırılmalı; "
                    "SSL sertifika doğrulaması kapatılmadı. Hatalar: ilk={}; doğrudan={}."
                    .format(host, proxy_note, direct_reply, first_error, direct_error)
                ) from direct_error

def public_get(url: str, *, params: dict[str, Any] | None = None,
               timeout: float | tuple[float, float] = 12.0,
               headers: dict[str, str] | None = None) -> requests.Response:
    """Fetch public exchange data directly from the supplied official endpoint."""
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    return _requests_get(url, params=params, timeout=timeout, headers=request_headers)


def _json_get(url: str, timeout: float = 12.0,
              params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = public_get(url, params=params, timeout=timeout)
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Beklenmeyen JSON yapısı: {url}")
    return payload


def _binance_json_get(path: str, timeout: float = 8.0) -> dict[str, Any]:
    """Try every configured official REST base and log each endpoint result separately."""
    global _active_binance_rest_base
    with _binance_base_lock:
        active = _active_binance_rest_base
    bases = ([active] if active in BINANCE_REST_BASES else []) + [
        base for base in BINANCE_REST_BASES if base != active
    ]
    errors: list[str] = []
    logger = logging.getLogger(__name__)
    attempted: list[str] = []
    for base in bases:
        attempted.append(base)
        started = time.monotonic()
        try:
            payload = _json_get(f"{base}{path}", timeout=timeout)
            elapsed = time.monotonic() - started
            with _binance_base_lock:
                _active_binance_rest_base = base
            logger.info(
                "Binance REST uç noktası başarılı: base=%s path=%s süre=%.2fs",
                base, path, elapsed,
            )
            return payload
        except Exception as exc:
            elapsed = time.monotonic() - started
            detail = f"{type(exc).__name__}: {str(exc)}"
            errors.append(f"{base}: {detail}")
            # Log each host separately: the final state/error message may be shortened
            # for the UI, but this diagnostic line preserves the outcome per endpoint.
            logger.warning(
                "Binance REST uç noktası başarısız: base=%s path=%s süre=%.2fs hata=%s",
                base, path, elapsed, detail[:1200],
            )
    attempted_text = ", ".join(attempted)
    tail = " | ".join(errors[-3:])
    raise RuntimeError(
        f"Binance REST adreslerinin hiçbiri yanıt vermedi; "
        f"{len(attempted)} adres ayrı ayrı denendi: {attempted_text}. "
        f"Son uç nokta hataları: {tail}"
    )

def fetch_binance_usdt_spot() -> dict[str, dict[str, str]]:
    """{BASE: {symbol, base, quote}}; aktif durum ve Spot izni zorunludur."""
    payload = _binance_json_get("/api/v3/exchangeInfo")
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        raise ValueError("Binance exchangeInfo içinde symbols listesi bulunamadı.")
    result: dict[str, dict[str, str]] = {}
    for row in symbols:
        if not isinstance(row, dict):
            continue
        base = str(row.get("baseAsset", "")).upper().strip()
        quote = str(row.get("quoteAsset", "")).upper().strip()
        status = str(row.get("status", "")).upper()
        spot_allowed = row.get("isSpotTradingAllowed")
        permissions = row.get("permissions", [])
        permission_sets = row.get("permissionSets", [])
        spot_flag = spot_allowed is True or "SPOT" in (permissions if isinstance(permissions, list) else [])
        if isinstance(permission_sets, list):
            spot_flag = spot_flag or any("SPOT" in group for group in permission_sets if isinstance(group, list))
        if base and quote == "USDT" and status == "TRADING" and spot_flag:
            result[base] = {"symbol": str(row.get("symbol", "")).upper(),
                            "base": base, "quote": quote}
    return result


def _extract_btcturk_symbols(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", payload)
    if isinstance(data, dict):
        rows = data.get("symbols", data.get("pairs", []))
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    if not isinstance(rows, list):
        raise ValueError("BtcTurk exchangeinfo içinde sembol listesi bulunamadı.")
    return [row for row in rows if isinstance(row, dict)]


def _write_json_cache(path: Path, payload: dict[str, Any]) -> None:
    """Atomically persist small public-market metadata without corrupting a prior cache."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
    with _btcturk_cache_lock:
        try:
            temporary.write_text(encoded, encoding="utf-8")
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def load_cached_btcturk_usdt_spot() -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    """Load the last successful BtcTurk list, or the older verified common-universe cache."""
    cache_candidates = (
        (BTCTURK_UNIVERSE_CACHE_PATH, "BTCTURK_UNIVERSE_CACHE"),
        (ROOT / "data" / "common_universe.json", "LEGACY_COMMON_UNIVERSE_CACHE"),
    )
    errors: list[str] = []
    for cache_path, cache_kind in cache_candidates:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("kök JSON nesnesi bekleniyordu.")
            symbols: dict[str, dict[str, str]] = {}
            raw_symbols = payload.get("symbols")
            if isinstance(raw_symbols, dict):
                for raw_base, item in raw_symbols.items():
                    if not isinstance(item, dict):
                        continue
                    base = str(raw_base).upper().strip()
                    symbol = str(item.get("symbol", "")).upper().strip()
                    quote = str(item.get("quote", "")).upper().strip()
                    if base and quote == "USDT" and symbol == f"{base}USDT":
                        symbols[base] = {"symbol": symbol, "base": base, "quote": "USDT"}
            else:
                # Compatibility: older releases only persisted the intersection in common_universe.json.
                pairs = payload.get("pairs", [])
                if isinstance(pairs, list):
                    for item in pairs:
                        if not isinstance(item, dict):
                            continue
                        base = str(item.get("base_asset", "")).upper().strip()
                        quote = str(item.get("quote_asset", "")).upper().strip()
                        symbol = str(item.get("btcturk_symbol", "")).upper().strip()
                        if base and quote == "USDT" and symbol == f"{base}USDT":
                            symbols[base] = {"symbol": symbol, "base": base, "quote": "USDT"}
            generated_at = str(payload.get("generated_at_utc") or "")
            if not symbols or not generated_at:
                raise ValueError("parite veya zaman damgası bulunamadı.")
            try:
                dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                age_seconds = max(0, int((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()))
            except (TypeError, ValueError):
                age_seconds = None
            source = str(payload.get("source") or (
                "Legacy verified common-universe cache" if cache_kind == "LEGACY_COMMON_UNIVERSE_CACHE"
                else "BtcTurk public exchangeInfo cache"
            ))
            ticker_source = "/api/v2/ticker" in source
            legacy_common_source = "legacy common-universe" in source.casefold()
            if cache_kind == "LEGACY_COMMON_UNIVERSE_CACHE" or legacy_common_source:
                mode = "CACHED_COMMON_FALLBACK"
                warning = (
                    "Yalnızca son kaydedilmiş ortak Binance/BtcTurk listesi bulundu; "
                    "bu kayıt BtcTurk'ün tam parite evreni değildir."
                )
            elif ticker_source:
                mode = "CACHED_TICKER_FALLBACK"
                warning = (
                    "Son kayıt resmî BtcTurk ticker listesinden türemiştir; "
                    "exchangeInfo ile aktif işlem durumu doğrulanmış değildir."
                )
            else:
                mode = "CACHED"
                warning = None
            return symbols, {
                "mode": mode,
                "generated_at_utc": generated_at,
                "age_seconds": age_seconds,
                "count": len(symbols),
                "source": source,
                "cache_path": str(cache_path),
                "warning": warning,
            }
        except Exception as exc:
            errors.append(f"{cache_path.name}: {exc}")
    raise ValueError("Geçerli bir BtcTurk parite kaydı bulunamadı. " + " | ".join(errors))


def _extract_btcturk_ticker_universe(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Infer listed USDT pairs from the official BtcTurk ticker snapshot."""
    raw = payload.get("data")
    if isinstance(raw, dict):
        rows = [raw]
    elif isinstance(raw, list):
        rows = raw
    else:
        rows = []
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("pair", row.get("pairSymbol", row.get("name", "")))).upper().replace("_", "").strip()
        base = str(row.get("numeratorSymbol", row.get("numerator", row.get("baseAsset", "")))).upper().strip()
        quote = str(row.get("denominatorSymbol", row.get("denominator", row.get("quoteAsset", "")))).upper().strip()
        if not base and name.endswith("USDT"):
            base, quote = name[:-4], "USDT"
        if not (base and quote == "USDT" and name == f"{base}USDT"):
            continue
        try:
            last = float(row.get("last", row.get("lastPrice", 0)) or 0)
        except (TypeError, ValueError):
            last = 0.0
        if not (last > 0):
            continue
        result[base] = {"symbol": name, "base": base, "quote": "USDT"}
    return result


def fetch_btcturk_usdt_spot(*, allow_unverified_cache: bool = True) -> dict[str, dict[str, str]]:
    """Fetch USDT pairs; ticker fallback is explicitly marked as unverified."""
    endpoints = [
        (BTCTURK_EXCHANGE_INFO, None, "exchangeInfo"),
        ("https://api.btcturk.com/api/v2/ticker/currency", {"symbol": "usdt"}, "ticker/currency"),
        ("https://api.btcturk.com/api/v2/ticker", None, "ticker"),
    ]
    errors: list[str] = []
    for url, params, endpoint_kind in endpoints:
        # Retry the primary exchangeInfo once; try each documented ticker alternative once.
        attempts = 2 if endpoint_kind == "exchangeInfo" else 1
        for attempt in range(attempts):
            try:
                payload = _json_get(url, timeout=4.5, params=params)
                if payload.get("success") is False:
                    raise ValueError("BtcTurk endpoint success=false döndürdü.")
                if endpoint_kind == "exchangeInfo":
                    rows = _extract_btcturk_symbols(payload)
                    result: dict[str, dict[str, str]] = {}
                    for row in rows:
                        base = str(row.get("numerator", row.get("baseAsset", ""))).upper().strip()
                        quote = str(row.get("denominator", row.get("quoteAsset", ""))).upper().strip()
                        status = str(row.get("status", "")).upper()
                        name = str(row.get("name", row.get("symbol", ""))).upper().strip()
                        if base and quote == "USDT" and status == "TRADING" and name == f"{base}USDT":
                            result[base] = {"symbol": name, "base": base, "quote": "USDT"}
                else:
                    result = _extract_btcturk_ticker_universe(payload)
                if not result:
                    raise ValueError("Endpoint boş veya doğrulanabilir USDT Spot paritesi içermiyor.")
                generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                source = url + (f"?symbol={params['symbol']}" if params and "symbol" in params else "")
                # Never overwrite a saved exchangeInfo-verified universe with a ticker
                # fallback. Single-engine manual update also disables fallback persistence.
                should_persist = (
                    endpoint_kind == "exchangeInfo"
                    or (allow_unverified_cache and not BTCTURK_UNIVERSE_CACHE_PATH.exists())
                )
                if should_persist:
                    try:
                        _write_json_cache(BTCTURK_UNIVERSE_CACHE_PATH, {
                            "generated_at_utc": generated_at,
                            "source": source,
                            "count": len(result),
                            "active_status_verified": endpoint_kind == "exchangeInfo",
                            "symbols": result,
                        })
                    except Exception:
                        pass
                if endpoint_kind != "exchangeInfo":
                    result = {
                        base: {**item, "pair_status": "TICKER_SNAPSHOT_FALLBACK_NOT_EXCHANGEINFO_VERIFIED"}
                        for base, item in result.items()
                    }
                return result
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
                if attempt + 1 < attempts:
                    time.sleep(0.35)
    raise RuntimeError(
        "BtcTurk resmî parite-listesi ve ticker-listesi uç noktalarının tümü başarısız. "
        + " | ".join(errors[-4:])
    )


def fetch_btcturk_usdt_spot_with_cache() -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    """Prefer a fresh BtcTurk list; fall back to its last successful cache with explicit metadata."""
    try:
        symbols = fetch_btcturk_usdt_spot()
        ticker_fallback = any(
            isinstance(item, dict)
            and item.get("pair_status") == "TICKER_SNAPSHOT_FALLBACK_NOT_EXCHANGEINFO_VERIFIED"
            for item in symbols.values()
        )
        if ticker_fallback:
            source = "BtcTurk ticker yedeği — exchangeInfo aktiflik doğrulaması yok"
            generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        else:
            try:
                _cached_symbols, persisted = load_cached_btcturk_usdt_spot()
                source = str(persisted.get("source") or BTCTURK_EXCHANGE_INFO)
                generated_at = str(persisted.get("generated_at_utc") or datetime.now(timezone.utc).isoformat(timespec="seconds"))
            except Exception:
                source = BTCTURK_EXCHANGE_INFO
                generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return symbols, {
            "mode": "LIVE_TICKER_FALLBACK" if ticker_fallback else "LIVE",
            "generated_at_utc": generated_at,
            "age_seconds": 0,
            "count": len(symbols),
            "source": source,
            "warning": (
                "BtcTurk exchangeInfo alınamadı; resmî ticker-listesi yedeği kullanıldı. "
                "Bu listedeki paritelerin aktif işlem durumu exchangeInfo üzerinden doğrulanmadı."
                if ticker_fallback else None
            ),
            "live_fetch_error": None,
        }
    except Exception as live_error:
        try:
            symbols, metadata = load_cached_btcturk_usdt_spot()
        except Exception as cache_error:
            raise RuntimeError(
                f"BtcTurk güncel parite listesi alınamadı ve geçerli bir son kayıt yok. "
                f"Canlı hata: {live_error}; kayıtlı liste hatası: {cache_error}"
            ) from live_error
        metadata = dict(metadata)
        if metadata.get("mode") == "CACHED_COMMON_FALLBACK":
            fallback_warning = (
                "BtcTurk güncel parite evreni alınamadı; yalnız eski ortak Binance/BtcTurk kayıt kümesi "
                "kullanılıyor. Bu kayıt BtcTurk'ün tam evreni değildir."
            )
        elif metadata.get("mode") == "CACHED_TICKER_FALLBACK":
            fallback_warning = (
                "BtcTurk güncel liste alınamadı; son başarılı ticker-listesi kaydı kullanılıyor. "
                "Aktif işlem durumu exchangeInfo ile doğrulanmış değildir."
            )
        else:
            fallback_warning = "BtcTurk parite evreni güncel olarak alınamadı; son başarılı kayıt kullanılıyor."
        metadata.update({
            "warning": fallback_warning,
            "live_fetch_error": str(live_error)[:500],
        })
        return symbols, metadata


def parse_usdt_base_asset(symbol_input: str) -> str | None:
    """Normalize BASE, BASEUSDT or BASE/USDT to BASE; return None for non-USDT pairs."""
    value = str(symbol_input or "").strip().upper().replace(" ", "")
    if "/" in value:
        parts = value.split("/")
        if len(parts) != 2 or parts[1] != "USDT":
            return None
        base = parts[0]
    elif value.endswith("USDT"):
        base = value[:-4]
    else:
        base = value
    return base if base and base not in {"USDT"} else None


def fetch_common_usdt_symbols() -> dict[str, Any]:
    """Build a Binance/BtcTurk common Spot USDT set, using a timestamped BtcTurk cache only if needed."""
    settings = load_settings()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    binance = fetch_binance_usdt_spot()
    btcturk, btcturk_meta = fetch_btcturk_usdt_spot_with_cache()
    fan_skip = {str(x).upper() for x in settings.get("fan_token_bases_to_skip", [])}
    exclusions: dict[str, str] = {}
    common_bases = sorted(set(binance).intersection(btcturk))
    pairs = []
    for base in common_bases:
        if base in fan_skip:
            exclusions[base] = "YAPILANDIRILMIŞ FAN TOKEN DIŞLAMA LİSTESİ"
            continue
        b, t = binance[base], btcturk[base]
        if b["base"] != t["base"] or b["quote"] != t["quote"]:
            continue
        pairs.append({
            "base_asset": base, "quote_asset": "USDT",
            "binance_symbol": b["symbol"], "btcturk_symbol": t["symbol"],
            "identity_match": "EXACT_BASE_AND_QUOTE",
            "category_status": "MANUEL_FAN_TOKEN_LISTESINE_GÖRE_FİLTRELENDİ; DİĞER KATEGORİLER BAĞIMSIZ DOĞRULANMADI",
        })
    if not pairs:
        raise RuntimeError("İki borsada uygun ortak Spot USDT paritesi bulunamadı.")
    btcturk_mode = str(btcturk_meta.get("mode") or "LIVE")
    btcturk_cached = btcturk_mode in ("CACHED", "CACHED_TICKER_FALLBACK", "CACHED_COMMON_FALLBACK")
    btcturk_ticker_fallback = btcturk_mode in ("LIVE_TICKER_FALLBACK", "CACHED_TICKER_FALLBACK")
    warning = (
        str(btcturk_meta.get("warning") or
            f"BtcTurk parite evreni güncel olarak alınamadı; son başarılı kayıt kullanılıyor. Son kayıt: {btcturk_meta.get('generated_at_utc', 'bilinmiyor')} UTC.")
        if btcturk_cached or btcturk_ticker_fallback else
        "Ortak aktif USDT evreni fan token dışlaması dışında ek coin listesinden daraltılmaz. "
        "Token kategorileri API tarafından tam sunulmayabileceğinden fan token dışlama listesi ayarlardan yönetilir."
    )
    return {
        "generated_at_utc": now,
        "source": (
            "Binance Spot exchangeInfo + BtcTurk prior common-universe cache" if btcturk_mode == "CACHED_COMMON_FALLBACK" else
            "Binance Spot exchangeInfo + BtcTurk last successful ticker-list cache" if btcturk_mode == "CACHED_TICKER_FALLBACK" else
            "Binance Spot exchangeInfo + BtcTurk last successful exchangeInfo cache" if btcturk_cached else
            "Binance Spot exchangeInfo + BtcTurk ticker-list fallback" if btcturk_ticker_fallback else
            "Binance Spot exchangeInfo + BtcTurk Spot exchangeInfo"
        ),
        "universe_mode": (
            "CACHED_COMMON_FALLBACK" if btcturk_mode == "CACHED_COMMON_FALLBACK" else
            "CACHED_BTCTURK_TICKER_FALLBACK" if btcturk_mode == "CACHED_TICKER_FALLBACK" else
            "CACHED_BTCTURK_FALLBACK" if btcturk_cached else
            "BTCTURK_TICKER_FALLBACK" if btcturk_ticker_fallback else
            "COMMON_VERIFIED"
        ),
        "btcturk_universe_mode": btcturk_meta.get("mode"),
        "btcturk_universe_generated_at_utc": btcturk_meta.get("generated_at_utc"),
        "btcturk_universe_age_seconds": btcturk_meta.get("age_seconds"),
        "btcturk_universe_count": len(btcturk),
        "btcturk_universe_warning": btcturk_meta.get("warning"),
        "btcturk_universe_live_error": btcturk_meta.get("live_fetch_error"),
        "binance_active_usdt_count": len(binance),
        "btcturk_active_usdt_count": len(btcturk),
        "common_pair_count_before_local_exclusions": len(common_bases),
        "excluded_common_assets": exclusions,
        "common_pair_count": len(pairs), "pairs": pairs,
        "scan_symbol_count": len(pairs),
        "warning": warning,
    }


def find_common_pair(symbol_input: str, universe: dict[str, Any]) -> dict[str, str] | None:
    """BASE, BASEUSDT veya BASE/USDT girişini güncel ortak evrende ara."""
    text = str(symbol_input or "").strip().upper().replace(" ", "")
    if "/" in text:
        pieces = text.split("/")
        if len(pieces) != 2 or pieces[1] != "USDT":
            return None
        base = pieces[0]
    elif text.endswith("USDT"):
        base = text[:-4]
    else:
        base = text
    for pair in universe.get("pairs", []):
        if pair.get("base_asset") == base and pair.get("quote_asset") == "USDT":
            return pair
    return None


_SNAPSHOT_FINGERPRINT_FIELDS = (
    "common_pair_count", "base_asset", "quote_asset", "binance_symbol",
    "btcturk_symbol", "identity_match", "category_status", "universe_mode",
    "universe_source", "binance_universe_source_verified",
    "btcturk_list_active_status_verified", "btcturk_list_timestamp_utc",
    "strong_alerts_enabled", "strong_alarm_eligible",
)


def _snapshot_fingerprint(rows: list[dict[str, Any]]) -> str:
    """Hash the state that changes historical universe meaning."""
    normalized = [
        {field: str(row.get(field) or "").strip() for field in _SNAPSHOT_FINGERPRINT_FIELDS}
        for row in rows
    ]
    normalized.sort(key=lambda item: (item.get("binance_symbol", ""), item.get("base_asset", "")))
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _parse_snapshot_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _read_latest_snapshot_state_locked(path: Path) -> dict[str, Any] | None:
    """Recover the most recent CSV timestamp group when the small index is stale."""
    if not path.is_file() or path.stat().st_size == 0:
        return None
    latest_stamp: str | None = None
    latest_rows: list[dict[str, Any]] = []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "timestamp_utc" not in reader.fieldnames:
            return None
        for row in reader:
            stamp = str(row.get("timestamp_utc") or "").strip()
            if not stamp:
                continue
            if stamp != latest_stamp:
                latest_stamp = stamp
                latest_rows = []
            latest_rows.append(row)
    if not latest_rows or not latest_stamp:
        return None
    return {"last_snapshot_at_utc": latest_stamp, "last_fingerprint": _snapshot_fingerprint(latest_rows)}


def _write_snapshot_state(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _append_csv_rows_locked(
    path: Path,
    fields: list[str],
    rows: list[dict[str, Any]],
    *,
    snapshot_fingerprint: str | None = None,
    observed_at_utc: str | None = None,
    checkpoint_seconds: int = 86400,
) -> bool:
    """Append under a process lock, preserving legacy rows and skipping redundant snapshots."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    state_path = path.with_name(path.name + ".state.json")
    observed_time = _parse_snapshot_time(observed_at_utc)
    dedupe_enabled = snapshot_fingerprint is not None and observed_time is not None
    checkpoint_seconds = max(60, int(checkpoint_seconds))
    with lock_path.open("a+b") as lock_handle:
        lock_handle.seek(0, os.SEEK_END)
        if lock_handle.tell() == 0:
            lock_handle.write(b"\0")
            lock_handle.flush()
        lock_handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            if dedupe_enabled:
                previous_state: dict[str, Any] | None = None
                state_needs_refresh = False
                try:
                    current_stat = path.stat()
                    cached = None
                    if state_path.is_file():
                        with state_path.open("r", encoding="utf-8") as state_handle:
                            candidate = json.load(state_handle)
                        if (
                            isinstance(candidate, dict)
                            and candidate.get("archive_size_bytes") == current_stat.st_size
                            and candidate.get("archive_mtime_ns") == current_stat.st_mtime_ns
                        ):
                            cached = candidate
                    if cached is not None:
                        previous_state = {
                            "last_snapshot_at_utc": cached.get("last_snapshot_at_utc"),
                            "last_fingerprint": cached.get("last_fingerprint"),
                        }
                    else:
                        previous_state = _read_latest_snapshot_state_locked(path)
                        state_needs_refresh = previous_state is not None
                except (OSError, UnicodeError, json.JSONDecodeError, csv.Error):
                    previous_state = None
                previous_time = (
                    _parse_snapshot_time(previous_state.get("last_snapshot_at_utc"))
                    if isinstance(previous_state, dict) else None
                )
                previous_fingerprint = (
                    previous_state.get("last_fingerprint")
                    if isinstance(previous_state, dict) else None
                )
                if (
                    previous_fingerprint == snapshot_fingerprint
                    and previous_time is not None
                    and 0 <= (observed_time - previous_time).total_seconds() < checkpoint_seconds
                ):
                    if state_needs_refresh:
                        try:
                            stat = path.stat()
                            _write_snapshot_state(state_path, {
                                "last_snapshot_at_utc": previous_time.isoformat(timespec="milliseconds"),
                                "last_fingerprint": previous_fingerprint,
                                "archive_size_bytes": stat.st_size,
                                "archive_mtime_ns": stat.st_mtime_ns,
                            })
                        except OSError:
                            pass
                    return False

            output_fields = list(fields)
            old_rows: list[dict[str, Any]] = []
            old_fields: list[str] = []
            if path.exists() and path.stat().st_size:
                with path.open("r", newline="", encoding="utf-8-sig") as existing_handle:
                    reader = csv.DictReader(existing_handle)
                    old_fields = list(reader.fieldnames or [])
                    if not old_fields:
                        raise ValueError(f"CSV arşiv başlığı okunamadı: {path}")
                    old_rows = list(reader)
                output_fields = list(old_fields)
                output_fields.extend(field for field in fields if field not in output_fields)
                if output_fields != old_fields:
                    temporary = path.with_name(f".{path.name}.{os.getpid()}.schema.tmp")
                    try:
                        with temporary.open("w", newline="", encoding="utf-8") as handle:
                            handle.write("\ufeff")
                            writer = csv.DictWriter(
                                handle, fieldnames=output_fields, extrasaction="ignore"
                            )
                            writer.writeheader()
                            writer.writerows(old_rows)
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(temporary, path)
                    finally:
                        try:
                            temporary.unlink(missing_ok=True)
                        except OSError:
                            pass

            with path.open("a+", newline="", encoding="utf-8") as handle:
                handle.seek(0, os.SEEK_END)
                is_new = handle.tell() == 0
                if is_new:
                    handle.write("\ufeff")
                writer = csv.DictWriter(
                    handle, fieldnames=output_fields, extrasaction="ignore"
                )
                if is_new:
                    writer.writeheader()
                writer.writerows(rows)
                handle.flush()
                os.fsync(handle.fileno())

            if dedupe_enabled:
                try:
                    stat = path.stat()
                    _write_snapshot_state(state_path, {
                        "last_snapshot_at_utc": observed_time.isoformat(timespec="milliseconds"),
                        "last_fingerprint": snapshot_fingerprint,
                        "archive_size_bytes": stat.st_size,
                        "archive_mtime_ns": stat.st_mtime_ns,
                    })
                except OSError:
                    # The sidecar is a cache; next call can recover the latest snapshot from CSV.
                    pass
            return True
        finally:
            lock_handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def append_universe_snapshot(
    universe: dict[str, Any],
    trigger: str,
    *,
    observed_at_utc: str | None = None,
    checkpoint_seconds: int | None = None,
) -> bool:
    """Archive actual scan membership, source age and effective per-pair alarm permission."""
    pairs = universe.get("pairs", [])
    if not isinstance(pairs, list) or not pairs:
        return False

    mode = str(universe.get("universe_mode") or "COMMON_VERIFIED")
    trusted_modes = {"COMMON_VERIFIED", "SINGLE_ENGINE_LOCAL_LIST"}
    explicit_global = universe.get("strong_alerts_enabled")
    global_permission = (
        explicit_global if isinstance(explicit_global, bool)
        else mode == "COMMON_VERIFIED"
    )
    if mode not in trusted_modes:
        global_permission = False

    path = ROOT / "data" / "universe_history.csv"
    fields = [
        "timestamp_utc", "trigger", "common_pair_count", "base_asset", "quote_asset",
        "binance_symbol", "btcturk_symbol", "identity_match", "category_status",
        "universe_mode", "universe_source", "source_generated_at_utc",
        "binance_universe_source_verified", "btcturk_list_active_status_verified",
        "btcturk_list_timestamp_utc", "btcturk_list_age_seconds",
        "strong_alerts_enabled", "strong_alarm_eligible", "strong_alarm_block_reason",
    ]

    def bool_text(value: Any) -> str:
        return "true" if value is True else "false" if value is False else ""

    observed = str(observed_at_utc or universe.get("generated_at_utc") or "").strip()
    source_generated = str(universe.get("generated_at_utc") or "").strip()
    btcturk_timestamp = (
        universe.get("btcturk_universe_generated_at_utc")
        or universe.get("local_list_generated_at_utc")
    )
    btcturk_age = (
        universe.get("btcturk_universe_age_seconds")
        if universe.get("btcturk_universe_age_seconds") is not None
        else universe.get("local_list_age_seconds")
    )
    source = str(universe.get("source") or "").strip()
    rows = []
    for pair in pairs:
        pair_permission = pair.get("strong_alarm_eligible")
        if not global_permission:
            effective_permission: bool | None = False
        elif isinstance(pair_permission, bool):
            effective_permission = pair_permission
        else:
            effective_permission = None

        reasons: list[str] = []
        pair_reason = str(pair.get("strong_alarm_block_reason") or "").strip()
        if pair_reason:
            reasons.append(pair_reason)
        if not global_permission:
            global_reason = str(
                universe.get("warning") or universe.get("alert_filter_warning")
                or f"Güçlü alarm izni doğrulanmadı (evren modu: {mode})."
            ).strip()
            if global_reason:
                reasons.append(global_reason)
        elif effective_permission is None:
            reasons.append("Pariteye özel güçlü alarm uygunluğu kaynak kaydında bulunmuyor.")

        rows.append({
            "timestamp_utc": observed,
            "trigger": trigger,
            "common_pair_count": len(pairs),
            "base_asset": pair.get("base_asset"),
            "quote_asset": pair.get("quote_asset"),
            "binance_symbol": pair.get("binance_symbol"),
            "btcturk_symbol": pair.get("btcturk_symbol"),
            "identity_match": pair.get("identity_match"),
            "category_status": pair.get("category_status"),
            "universe_mode": mode,
            "universe_source": source,
            "source_generated_at_utc": source_generated,
            "binance_universe_source_verified": bool_text(
                universe.get("binance_universe_source_verified")
            ),
            "btcturk_list_active_status_verified": bool_text(
                universe.get("btcturk_list_active_status_verified")
            ),
            "btcturk_list_timestamp_utc": btcturk_timestamp,
            "btcturk_list_age_seconds": btcturk_age,
            "strong_alerts_enabled": bool_text(global_permission),
            "strong_alarm_eligible": bool_text(effective_permission),
            "strong_alarm_block_reason": "; ".join(dict.fromkeys(reasons)),
        })

    if checkpoint_seconds is None:
        checkpoint_seconds = load_settings().get("universe_snapshot_checkpoint_seconds", 86400)
    try:
        checkpoint_seconds = max(60, int(checkpoint_seconds))
    except (TypeError, ValueError, OverflowError):
        checkpoint_seconds = 86400
    return _append_csv_rows_locked(
        path, fields, rows, snapshot_fingerprint=_snapshot_fingerprint(rows),
        observed_at_utc=observed, checkpoint_seconds=checkpoint_seconds,
    )
