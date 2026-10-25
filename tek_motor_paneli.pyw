"""FIRSAT-KONTROL PANELİ — yerel Tkinter arayüzü, tek Binance analiz motoru.

Bu uygulama yalnızca halka açık piyasa verilerini kullanır. Hesap/bakiye/pozisyon
verilerine erişmez ve emir göndermez. A/B/C değerleri araştırma aşamalarıdır.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any
import wave
import struct
import zipfile

import tkinter as tk
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"
REPORT_DIR = ROOT / "reports"
RUN_DIR = ROOT / "run"
STATE_PATH = DATA_DIR / "binance_state.json"
SETTINGS_PATH = ROOT / "ayarlar.json"
ENGINE_PATH = ROOT / "binance_erken_firsat_radari.py"
STOP_FILE = RUN_DIR / "stop_radar.flag"
PANEL_LOG_PATH = LOG_DIR / "tek_motor_paneli.log"
ENGINE_LOG_PATH = LOG_DIR / "binance_radar.log"
APP_TITLE = "FIRSAT-KONTROL PANELİ"

for _directory in (DATA_DIR, LOG_DIR, REPORT_DIR, RUN_DIR):
    _directory.mkdir(parents=True, exist_ok=True)


def _make_logger() -> logging.Logger:
    logger = logging.getLogger("firsat_kontrol_paneli")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            PANEL_LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(handler)
    return logger


LOGGER = _make_logger()


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _parse_utc_epoch(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _format_price(value: Any) -> str:
    number = _safe_float(value)
    if number is None or number <= 0:
        return "—"
    return f"{number:.10g}"


def _format_age(seconds: Any) -> str:
    value = _safe_float(seconds)
    if value is None or value < 0:
        return "bilinmiyor"
    if value < 60:
        return f"{value:.0f} sn"
    if value < 3600:
        return f"{value / 60:.1f} dk"
    if value < 86400:
        return f"{value / 3600:.1f} sa"
    return f"{value / 86400:.1f} gün"


def _short(value: Any, limit: int = 500) -> str:
    if value is None:
        return "—"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    else:
        text = str(value)
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(128 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def _get_engine_interpreter() -> str:
    executable = Path(sys.executable)
    if executable.name.casefold() == "pythonw.exe":
        sibling = executable.with_name("python.exe")
        if sibling.is_file():
            return str(sibling)
    return str(executable)


def _tail_text(paths: list[Path], *, max_lines: int = 300, max_bytes: int = 128 * 1024) -> str:
    """Return a bounded combined log tail for diagnostics, keeping recent lines first."""
    lines: list[str] = []
    used = 0
    for path in paths:
        try:
            raw = path.read_bytes()
            raw = raw[-max_bytes:]
            text = raw.decode("utf-8", errors="replace")
            group = [f"===== {path.name} =====", *text.splitlines()[-max_lines:]]
        except OSError:
            continue
        for line in reversed(group):
            encoded_size = len(line.encode("utf-8", errors="replace")) + 1
            if len(lines) >= max_lines or used + encoded_size > max_bytes:
                break
            lines.append(line)
            used += encoded_size
        if len(lines) >= max_lines or used >= max_bytes:
            break
    return "\n".join(reversed(lines)) + ("\n" if lines else "")


def _format_btc_context_summary(state: dict[str, Any]) -> str:
    """Build a concise BTC context line from the engine's existing state."""
    context = state.get("btc_market_context")
    context = context if isinstance(context, dict) else {}
    gate = state.get("btc_strong_alert_gate")
    gate = gate if isinstance(gate, dict) else {}
    if state.get("btc_market_context_freshness") != "CANLI AKIŞ GÜNCEL" or context.get("data_completeness") != "TAM":
        warning = str(state.get("btc_market_context_warning") or "BTC canlı bağlamı eksik/eski.")
        return f"BTC RİSK ÖZETİ: VERİ ESKİ/EKSİK — güçlü fırsat kapısı kapalı. {warning}"
    timeframe_rows = context.get("timeframes")
    timeframe_rows = timeframe_rows if isinstance(timeframe_rows, dict) else {}
    def zone_text(zone: Any) -> str:
        if not isinstance(zone, dict):
            return "teyitli bölge yok"
        lower, upper, center = (_safe_float(zone.get(key)) for key in ("lower", "upper", "center"))
        if lower is not None and upper is not None:
            return f"{_format_price(lower)}–{_format_price(upper)}"
        return _format_price(center) if center is not None else "teyitli bölge yok"
    details = []
    for timeframe in ("1h", "4h"):
        row = timeframe_rows.get(timeframe)
        if not isinstance(row, dict) or row.get("available") is not True:
            details.append(f"{timeframe}: veri yetersiz")
            continue
        direction = "pozitif" if row.get("bullish") is True else "zayıf" if row.get("price_above_slow_ema") is False else "karışık"
        support = zone_text(row.get("latest_confirmed_support_zone"))
        resistance = zone_text(row.get("nearest_relevant_resistance_zone"))
        channel = str(row.get("channel_status") or "kanal teyidi yok")
        details.append(f"{timeframe} {direction}; destek {support}; direnç {resistance}; {channel}")
    volatility = _safe_float(context.get("relative_volatility_ratio"))
    vol_text = f"BTC 1h oynaklık {volatility:.2f}x" if volatility is not None else "BTC oynaklık ölçümü yok"
    gate_text = "güçlü fırsat kapısı açık" if gate.get("eligible") is True else "güçlü fırsat kapısı kapalı"
    warnings = context.get("risk_warnings")
    warning_text = "; ".join(str(item) for item in warnings[:2] if item) if isinstance(warnings, list) else ""
    summary = "BTC: " + " | ".join([*details, vol_text, gate_text])
    if warning_text:
        summary += " | Risk: " + warning_text
    return summary


def _format_btc_relative(row: dict[str, Any]) -> str:
    if row.get("btc_market_context_freshness") not in (None, "CANLI AKIŞ GÜNCEL"):
        return "veri eski"
    relative = row.get("relative_strength_vs_btc_pct_points")
    relative = relative if isinstance(relative, dict) else {}
    value = _safe_float(relative.get("1h"))
    return f"{value:+.2f} yp" if value is not None else "—"


def _format_btc_correlation(row: dict[str, Any]) -> str:
    if row.get("btc_market_context_freshness") not in (None, "CANLI AKIŞ GÜNCEL"):
        return "veri eski"
    correlation = row.get("btc_return_correlation")
    correlation = correlation if isinstance(correlation, dict) else {}
    hourly = correlation.get("1h")
    if not isinstance(hourly, dict):
        return "—"
    value = _safe_float(hourly.get("value"))
    observations, minimum = hourly.get("observations"), hourly.get("minimum_required")
    if value is None or not isinstance(observations, int) or not isinstance(minimum, int) or observations < minimum:
        return "yetersiz veri"
    return f"{value:+.2f}"


def _format_candidate_decision_summary(candidate: dict[str, Any]) -> str:
    """Prioritize decision, BTC relationship, technical levels, and blockers."""
    decision = candidate.get("final_decision") or candidate.get("decision_class") or "—"
    phase = candidate.get("phase") or candidate.get("last_known_phase") or "—"
    reason = str(candidate.get("decision_reason") or "Karar gerekçesi henüz yok.")
    relative = candidate.get("relative_strength_vs_btc_pct_points")
    relative = relative if isinstance(relative, dict) else {}
    rel_text = ", ".join(
        f"{tf}: {_safe_float(relative.get(tf)):+.2f} yp"
        for tf in ("15m", "1h", "4h") if _safe_float(relative.get(tf)) is not None
    ) or "göreceli güç hesaplanamadı"
    correlations = candidate.get("btc_return_correlation")
    correlations = correlations if isinstance(correlations, dict) else {}
    corr_text = []
    for tf in ("1h", "4h"):
        item = correlations.get(tf)
        if not isinstance(item, dict):
            continue
        value = _safe_float(item.get("value"))
        count, minimum = item.get("observations"), item.get("minimum_required")
        if value is not None and isinstance(count, int) and isinstance(minimum, int) and count >= minimum:
            corr_text.append(f"{tf}: {value:+.2f}")
    corr_text_value = ", ".join(corr_text) or "yeterli eşzamanlı mum yok"
    assessment = candidate.get("btc_correlation_assessment")
    assessment = assessment if isinstance(assessment, dict) else {}
    assessment_text = str(assessment.get("summary") or "Korelasyon risk yorumu yok.")
    timeframe = str(candidate.get("phase_timeframe") or candidate.get("timeframe") or "")
    timeframes = candidate.get("timeframes")
    timeframes = timeframes if isinstance(timeframes, dict) else {}
    selected = timeframes.get(timeframe)
    metrics = selected.get("metrics") if isinstance(selected, dict) else {}
    metrics = metrics if isinstance(metrics, dict) else {}
    channel = metrics.get("confirmed_channel")
    channel_text = f"{channel.get('direction', 'kanal')} / {channel.get('status', 'teyitli')}" if isinstance(channel, dict) and channel.get("available") is True else "teyitli kanal yok"
    plan = candidate.get("risk_plan")
    plan = plan if isinstance(plan, dict) else {}
    low, high = _safe_float(plan.get("entry_zone_low")), _safe_float(plan.get("entry_zone_high"))
    stop = _safe_float(plan.get("stop_loss"))
    targets = plan.get("targets")
    target = _safe_float(targets[0].get("price")) if isinstance(targets, list) and targets and isinstance(targets[0], dict) else None
    entry_text = f"{_format_price(low)}–{_format_price(high)} USDT" if low is not None and high is not None else "mevcut değil"
    stop_text = f"{_format_price(stop)} USDT" if stop is not None else "mevcut değil"
    target_text = f"{_format_price(target)} USDT" if target is not None else "teknik hedef yok"
    components = candidate.get("score_components")
    components = components if isinstance(components, dict) else {}
    try:
        adjustment = int(components.get("btc_correlation_risk_adjustment", 0))
    except (TypeError, ValueError, OverflowError):
        adjustment = 0
    missing = candidate.get("missing_checks")
    missing = [str(item) for item in missing if item] if isinstance(missing, list) else []
    blockers = "; ".join(missing[:2]) if missing else "kayıtlı eksik kontrol yok"
    return "\n".join([
        f"{decision} | Aşama {phase} | Puan {candidate.get('opportunity_score', '—')}",
        f"Gerekçe: {reason}",
        f"BTC'ye göre getiri farkı: {rel_text}",
        f"BTC korelasyonu: {corr_text_value}. {assessment_text}",
        f"Fiyat yapısı: {channel_text}",
        f"Koşullu giriş: {entry_text} | Zarar durdurma: {stop_text} | İlk teknik hedef: {target_text}",
        f"Eksik teyit/engel: {blockers}",
        f"Korelasyon puan etkisi: {adjustment:+d}; riskli BTC bağlamında yüksek pozitif korelasyona ceza uygulanır.",
    ])


class ControlPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        screen_width = max(800, self.winfo_screenwidth())
        screen_height = max(600, self.winfo_screenheight())
        window_width = min(int(screen_width * 0.76), int(screen_width * 0.80))
        window_height = min(int(screen_height * 0.88), int(screen_height * 0.93))
        window_width = max(min(1100, int(screen_width * 0.80)), window_width)
        window_height = max(min(650, int(screen_height * 0.93)), window_height)
        self.geometry(
            f"{window_width}x{window_height}+"
            f"{max(0, (screen_width - window_width) // 2)}+"
            f"{max(0, (screen_height - window_height) // 2)}"
        )
        self.minsize(min(1100, window_width), min(650, window_height))
        icon_path = ROOT / "firsat_kontrol.ico"
        if icon_path.is_file():
            try:
                self.iconbitmap(str(icon_path))
            except tk.TclError:
                pass

        self.settings = _read_json(SETTINGS_PATH, {})
        if not isinstance(self.settings, dict):
            self.settings = {}
        panel = self.settings.get("panel_ui")
        if not isinstance(panel, dict):
            panel = {}
            self.settings["panel_ui"] = panel
        self.panel_settings = panel
        self.alarm_enabled = panel.get("alarm_sound_enabled", True) is True
        volume = _safe_float(panel.get("alarm_volume", 55))
        self.alarm_volume = int(max(0, min(100, volume if volume is not None else 55)))
        brightness = _safe_float(panel.get("panel_brightness", 85))
        self.panel_brightness = int(max(60, min(100, brightness if brightness is not None else 85)))

        self.engine: subprocess.Popen[str] | None = None
        self.engine_started_epoch: float | None = None
        self.stop_requested_epoch: float | None = None
        self.close_after_stop = False
        self.output_queue: queue.Queue[str] = queue.Queue()
        self.current_state: dict[str, Any] = {}
        self.current_state_epoch: float | None = None
        self.current_candidates: dict[str, dict[str, Any]] = {}
        self.current_candidate_key: str | None = None
        self._last_rendered_stamp: str | None = None
        self._previous_strong_keys: set[str] = set()
        self._alarm_primed = False
        self._level_watch_key: str | None = None
        self._level_previous_price: float | None = None
        self._level_crossed: set[str] = set()
        self._log_read_thread: threading.Thread | None = None
        self._last_error_state_stamp: str | None = None

        self.status_var = tk.StringVar(value="Motor durduruldu")
        self.universe_var = tk.StringVar(value="Tarama evreni: —")
        self.ws_var = tk.StringVar(value="WebSocket: —")
        self.alert_var = tk.StringVar(value="Güçlü alarm: açık" if self.alarm_enabled else "Güçlü alarm: kapalı")
        self.level_var = tk.StringVar(value="Seviye takibi: kapalı")
        self.volume_var = tk.IntVar(value=self.alarm_volume)
        self.brightness_var = tk.IntVar(value=self.panel_brightness)
        self.btc_context_var = tk.StringVar(value="BTC piyasa bağlamı: canlı veri bekleniyor")
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(250, self._poll)
        LOGGER.info("Panel açıldı. Başlangıç kodu: %s", ENGINE_PATH.name)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Header.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("BTC.TLabel", font=("Segoe UI", 9, "bold"))
        style.configure("Treeview", rowheight=25, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

        header = ttk.Frame(self, padding=(12, 10, 12, 6))
        header.pack(fill="x")
        ttk.Label(header, text=APP_TITLE, style="Header.TLabel").pack(side="left")
        ttk.Label(header, text="Tek analiz motoru: Binance Spot · Emir göndermez", padding=(16, 5)).pack(side="left")
        ttk.Label(header, textvariable=self.status_var, style="Status.TLabel", anchor="e").pack(side="right")

        status_row = ttk.Frame(self, padding=(12, 0, 12, 8))
        status_row.pack(fill="x")
        ttk.Label(status_row, textvariable=self.universe_var).pack(side="left")
        ttk.Label(status_row, textvariable=self.ws_var, padding=(20, 0, 0, 0)).pack(side="left")
        ttk.Label(status_row, textvariable=self.alert_var, padding=(20, 0, 0, 0)).pack(side="left")
        ttk.Label(status_row, textvariable=self.level_var, padding=(20, 0, 0, 0)).pack(side="left")

        btc_row = ttk.Frame(self, padding=(12, 0, 12, 6))
        btc_row.pack(fill="x")
        ttk.Label(btc_row, text="BTC bağlamı:", style="BTC.TLabel").pack(side="left", anchor="n")
        ttk.Label(
            btc_row, textvariable=self.btc_context_var, justify="left",
            wraplength=max(500, window_width - 180), anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        controls = ttk.Frame(self, padding=(12, 0, 12, 8))
        controls.pack(fill="x")
        self.start_button = ttk.Button(controls, text="Başlat", command=self.start_engine)
        self.start_button.pack(side="left", padx=(0, 6))
        self.stop_button = ttk.Button(controls, text="Durdur", command=self.stop_engine, state="disabled")
        self.stop_button.pack(side="left", padx=6)
        self.update_list_button = ttk.Button(controls, text="Parite listesini güncelle", command=self.update_universe)
        self.update_list_button.pack(side="left", padx=6)
        ttk.Button(controls, text="Rapor Oluştur", command=self.create_report).pack(side="left", padx=6)
        ttk.Button(controls, text="Rapor + Devir ZIP", command=self.create_handoff_zip).pack(side="left", padx=6)
        ttk.Button(controls, text="Kayıtları Aç", command=self.open_logs).pack(side="left", padx=6)
        ttk.Button(controls, text="Seviye Takibini Aç/Kapat", command=self.toggle_level_watch).pack(side="left", padx=6)

        sound = ttk.Frame(controls)
        sound.pack(side="right")
        self.alarm_button = ttk.Button(sound, text="Alarm Açık" if self.alarm_enabled else "Alarm Kapalı", command=self.toggle_alarm)
        self.alarm_button.pack(side="left", padx=6)
        ttk.Label(sound, text="Ses").pack(side="left")
        self.volume_scale = ttk.Scale(sound, from_=0, to=100, orient="horizontal", length=110,
                                      variable=self.volume_var, command=self._volume_moved)
        self.volume_scale.pack(side="left", padx=(5, 0))
        self.volume_scale.bind("<ButtonRelease-1>", self._save_volume)
        self.volume_scale.bind("<KeyRelease>", self._save_volume)
        self.volume_label = ttk.Label(sound, text=f"{self.alarm_volume}%", width=4)
        self.volume_label.pack(side="left", padx=(4, 0))
        ttk.Button(sound, text="Sesi dene", command=self._test_sound).pack(side="left", padx=6)
        ttk.Label(sound, text="Aydınlık").pack(side="left", padx=(6, 0))
        self.brightness_scale = ttk.Scale(
            sound, from_=60, to=100, orient="horizontal", length=78,
            variable=self.brightness_var, command=self._brightness_moved,
        )
        self.brightness_scale.pack(side="left", padx=(4, 0))
        self.brightness_scale.bind("<ButtonRelease-1>", self._save_brightness)
        self.brightness_scale.bind("<KeyRelease>", self._save_brightness)
        self.brightness_label = ttk.Label(sound, text=f"{self.panel_brightness}%", width=4)
        self.brightness_label.pack(side="left", padx=(4, 0))

        pane = ttk.Panedwindow(self, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        left = ttk.Frame(pane, padding=(0, 0, 5, 0))
        right = ttk.Frame(pane, padding=(5, 0, 0, 0))
        pane.add(left, weight=4)
        pane.add(right, weight=3)
        ttk.Label(left, text="Aday akışı", style="Status.TLabel").pack(anchor="w", pady=(0, 5))

        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill="both", expand=True)
        columns = ("star", "symbol", "route", "phase", "price", "btc_relative", "btc_correlation", "timeframe", "freshness", "decision")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        headers = {
            "star": "★", "symbol": "Coin / Parite", "route": "Keşif yolu", "phase": "A/B/C",
            "price": "Binance fiyatı", "btc_relative": "BTC göreli 1h", "btc_correlation": "BTC corr 1h",
            "timeframe": "Zaman dilimi", "freshness": "Veri", "decision": "Karar sınıfı",
        }
        widths = {"star": 35, "symbol": 115, "route": 115, "phase": 55, "price": 105,
                  "btc_relative": 95, "btc_correlation": 90, "timeframe": 85, "freshness": 110, "decision": 150}
        for col in columns:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=widths[col], minwidth=35,
                             anchor="center" if col in ("star", "phase", "timeframe") else "w",
                             stretch=col in ("symbol", "route", "decision"))
        yscroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        xscroll.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.tree.tag_configure("strong", background="#e5f3e8")
        self.tree.tag_configure("stale", foreground="#777777")
        self.tree.tag_configure("phase_a", foreground="#9a5b00")
        self.tree.tag_configure("phase_b", foreground="#8b6b00")
        self.tree.tag_configure("phase_c", foreground="#176b37")

        ttk.Label(right, text="Seçilen coin ve kanıtlar", style="Status.TLabel").pack(anchor="w", pady=(0, 5))
        self.details = tk.Text(right, wrap="word", font=("Consolas", 9), state="disabled", height=22)
        detail_scroll = ttk.Scrollbar(right, orient="vertical", command=self.details.yview)
        self.details.configure(yscrollcommand=detail_scroll.set)
        self.details.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")

        lower = ttk.LabelFrame(self, text="Tanılama / son kayıtlar", padding=6)
        lower.pack(fill="x", padx=12, pady=(0, 10))
        self.log_view = tk.Text(lower, height=6, wrap="none", font=("Consolas", 8), state="disabled")
        self.log_view.pack(fill="x", expand=True)
        ttk.Label(self, text="A/B/C araştırma aşamalarıdır; fiyat senaryoları garanti değildir. Otomatik alım-satım yoktur.",
                  padding=(12, 0, 12, 8)).pack(anchor="w")
        self._apply_brightness()

    def _apply_brightness(self) -> None:
        """Adjust only the light grayscale UI brightness; no dark theme is used."""
        value = max(60, min(100, int(self.panel_brightness)))
        gray = round(220 + (value - 60) * 35 / 40)
        background = f"#{gray:02x}{gray:02x}{gray:02x}"
        foreground = "#444444"
        style = ttk.Style(self)
        self.configure(background=background)
        for widget_style in ("TFrame", "TLabel", "TLabelframe", "TLabelframe.Label", "TButton"):
            style.configure(widget_style, background=background, foreground=foreground)
        style.configure("Treeview", background="#ffffff", fieldbackground=background, foreground=foreground)
        style.configure("Treeview.Heading", background=background, foreground=foreground)
        for widget in (getattr(self, "details", None), getattr(self, "log_view", None)):
            if widget is not None:
                widget.configure(background=background, foreground=foreground, insertbackground=foreground)
        self.brightness_label.configure(text=f"{value}%")

    def _append_details(self, text: str) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _selected_candidate(self) -> dict[str, Any] | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.current_candidates.get(selection[0])

    def _selection_changed(self, _event: Any = None) -> None:
        candidate = self._selected_candidate()
        if not candidate:
            self.current_candidate_key = None
            self._append_details("Bir aday seçin.\n\nNot: A/B/C araştırma aşamalarıdır; emir veya kârlılık garantisi değildir.")
            return
        key = self._candidate_key(candidate)
        if self._level_watch_key and self._level_watch_key != key:
            self._level_watch_key = None
            self._level_previous_price = None
            self._level_crossed.clear()
            self.level_var.set("Seviye takibi: kapalı (aday seçimi değişti)")
        self.current_candidate_key = key
        plan = candidate.get("risk_plan") if isinstance(candidate.get("risk_plan"), dict) else {}
        lines = [
            f"Parite: {candidate.get('symbol') or candidate.get('base_asset') or '—'}",
            f"Aşama: {candidate.get('phase') or candidate.get('last_known_phase') or '—'}  |  Durum: {candidate.get('state') or '—'}",
            f"Zaman dilimi: {candidate.get('phase_timeframe') or candidate.get('timeframe') or '—'}",
            f"Güncel fiyat: {_format_price(candidate.get('latest_price', candidate.get('price')))} USDT",
            f"Veri güncelliği: {candidate.get('data_freshness') or '—'}",
            "", "--- HIZLI KARAR ÖZETİ ---", _format_candidate_decision_summary(candidate),
            "", "--- MEVCUT KARAR ALANLARI ---",
            f"Karar: {candidate.get('final_decision') or candidate.get('decision_class') or '—'}",
            f"Fırsat puanı: {candidate.get('opportunity_score', candidate.get('score_0_100', '—'))}",
            f"Güçlü fırsat uygunluğu: {candidate.get('strong_opportunity_qualified', '—')}",
            f"Güçlü alarm uygunluğu: {candidate.get('strong_alarm_eligible', '—')}",
            f"Alarm engeli: {candidate.get('strong_alarm_block_reason') or '—'}",
            "", "--- Bulgular ---", _short(candidate.get("findings", []), 6000),
            "", "--- Kanıt grupları ---", _short(candidate.get("evidence_groups", []), 3000),
            "", "--- Eksik kontroller ---", _short(candidate.get("missing_checks", []), 3000),
            "", "--- Koşullu risk planı ---", _short(plan, 7000),
            "", "--- Zaman dilimi metrikleri ---",
            _short({tf: row.get("metrics", {}) for tf, row in (candidate.get("timeframes", {}) or {}).items()
                    if isinstance(row, dict)}, 11000),
            "", "Planlar koşulludur. Komisyon ve kayma hesaplanmaz; güçlü fırsat kapısında brüt teknik risk/getiri kullanılır. Spread ayrı likidite filtresindedir. Emir gönderilmez.",
        ]
        self._append_details("\n".join(map(str, lines)))

    @staticmethod
    def _candidate_key(candidate: dict[str, Any]) -> str:
        symbol = str(candidate.get("symbol") or candidate.get("base_asset") or "").upper()
        timeframe = str(candidate.get("phase_timeframe") or candidate.get("timeframe") or "")
        return f"{symbol}|{timeframe}"

    def start_engine(self) -> None:
        if self.engine and self.engine.poll() is None:
            return
        if not ENGINE_PATH.is_file():
            messagebox.showerror("Motor dosyası bulunamadı", f"Başlatılacak kaynak dosyası yok:\n{ENGINE_PATH}")
            return
        STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            STOP_FILE.unlink(missing_ok=True)
        except OSError as exc:
            messagebox.showerror("Başlatılamadı", f"Durdurma işareti kaldırılamadı: {exc}")
            return
        self.engine_started_epoch = time.time()
        self.stop_requested_epoch = None
        self._last_rendered_stamp = None
        self._previous_strong_keys.clear()
        self._alarm_primed = False
        interpreter = _get_engine_interpreter()
        command = [interpreter, str(ENGINE_PATH), "--stop-file", str(STOP_FILE), "--single-engine"]
        try:
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            self.engine = subprocess.Popen(
                command, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                env=env, creationflags=creationflags,
            )
        except (OSError, ValueError) as exc:
            self.engine = None
            LOGGER.exception("Motor başlatılamadı")
            messagebox.showerror("Motor başlatılamadı", f"{type(exc).__name__}: {exc}")
            return
        self._log_line(f"Motor başlatıldı (PID {self.engine.pid}); komut: {Path(interpreter).name} binance_erken_firsat_radari.py --single-engine")
        self.status_var.set("BAŞLATILIYOR — ilk güncel motor durumu bekleniyor")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._log_read_thread = threading.Thread(target=self._read_engine_output, args=(self.engine,),
                                                 daemon=True, name="engine-output-reader")
        self._log_read_thread.start()

    def _read_engine_output(self, process: subprocess.Popen[str]) -> None:
        try:
            if process.stdout is not None:
                for raw_line in process.stdout:
                    self.output_queue.put(raw_line.rstrip("\r\n"))
        except (OSError, ValueError) as exc:
            self.output_queue.put(f"[stdout okuyucu uyarısı] {type(exc).__name__}: {exc}")

    def stop_engine(self) -> None:
        if not self.engine or self.engine.poll() is not None:
            self.status_var.set("Motor durduruldu")
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            return
        try:
            STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
            STOP_FILE.write_text("stop requested\n", encoding="utf-8")
            self.stop_requested_epoch = time.time()
            self.status_var.set("DURDURMA İSTEĞİ GÖNDERİLDİ")
            self._log_line("Motor için kontrollü durdurma istendi.")
            self.stop_button.configure(state="disabled")
        except OSError as exc:
            messagebox.showerror("Durdurma isteği başarısız", str(exc))

    def update_universe(self) -> None:
        if not self.update_list_button.instate(["!disabled"]):
            return
        active = bool(self.engine and self.engine.poll() is None)
        if active and not messagebox.askyesno(
            "Motor çalışıyor",
            "Parite listesi yenilense bile çalışan motor belleğindeki evreni hemen değiştirmeyebilir.\n"
            "İşlem sonunda motoru yeniden başlatmanız gerekir. Listeyi şimdi yenileyeyim mi?",
        ):
            return
        self.update_list_button.configure(state="disabled")
        self.status_var.set("BtcTurk USDT Spot parite listesi güncelleniyor…")
        self._log_line("Kamuya açık BtcTurk parite listesi güncellemesi başlatıldı.")

        def worker() -> None:
            try:
                from ortak_piyasa import BTCTURK_UNIVERSE_CACHE_PATH, fetch_btcturk_usdt_spot
                symbols = fetch_btcturk_usdt_spot()
                if not isinstance(symbols, dict) or not symbols:
                    raise RuntimeError("BtcTurk doğrulanabilir USDT listesi boş döndü.")
                unverified = any(
                    isinstance(item, dict) and item.get("pair_status") == "TICKER_SNAPSHOT_FALLBACK_NOT_EXCHANGEINFO_VERIFIED"
                    for item in symbols.values()
                )
                cached = _read_json(BTCTURK_UNIVERSE_CACHE_PATH, {})
                verified_cached = isinstance(cached, dict) and cached.get("active_status_verified") is True
                result = {
                    "ok": True, "count": len(symbols), "unverified": unverified,
                    "verified_cached": verified_cached, "path": str(BTCTURK_UNIVERSE_CACHE_PATH),
                    "message": "Ticker yedeği kullanıldı; aktif işlem durumu doğrulanmadı." if unverified else "BtcTurk exchangeInfo ile liste doğrulandı.",
                }
            except Exception as exc:
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            self.output_queue.put("__UNIVERSE_RESULT__" + json.dumps(result, ensure_ascii=False))
        threading.Thread(target=worker, daemon=True, name="universe-refresh").start()

    def _poll(self) -> None:
        self._drain_output_queue()
        if self.engine:
            return_code = self.engine.poll()
            if return_code is not None:
                self._log_line(f"Motor süreci sona erdi. Çıkış kodu: {return_code}")
                self.engine = None
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                if not self.close_after_stop:
                    self.status_var.set("Motor durduruldu" if return_code == 0 else f"Motor kapandı (çıkış kodu {return_code})")
                if self.close_after_stop:
                    self.destroy()
                    return
            elif self.stop_requested_epoch and time.time() - self.stop_requested_epoch > 30:
                self._log_line("Motor 30 saniye içinde kapanmadı; kontrollü kapatma başarısız olduğu için işlem sonlandırılıyor.")
                try:
                    self.engine.terminate()
                except OSError:
                    pass
                self.stop_requested_epoch = None

        state = _read_json(STATE_PATH, None)
        if isinstance(state, dict):
            stamp = str(state.get("generated_at_utc") or "")
            stamp_epoch = _parse_utc_epoch(stamp)
            launched = self.engine_started_epoch
            is_new_session_state = launched is None or (stamp_epoch is not None and stamp_epoch >= launched - 2.0)
            if is_new_session_state and stamp and stamp != self._last_rendered_stamp and (
                self.current_state_epoch is None or stamp_epoch is None or stamp_epoch >= self.current_state_epoch
            ):
                self.current_state = state
                self.current_state_epoch = stamp_epoch
                self._last_rendered_stamp = stamp
                self._render_state(state)
                self._check_strong_alerts(state)
                self._check_level_watch(state)
        self.after(1000, self._poll)

    def _drain_output_queue(self) -> None:
        rendered: list[str] = []
        while True:
            try:
                line = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if line.startswith("__UNIVERSE_RESULT__"):
                try:
                    result = json.loads(line[len("__UNIVERSE_RESULT__"):])
                except json.JSONDecodeError:
                    result = {"ok": False, "error": "Liste güncelleme sonucu okunamadı."}
                self.update_list_button.configure(state="normal")
                if result.get("ok"):
                    message = (
                        f"Parite listesi güncellendi: {result['count']} kayıt.\n"
                        f"Kayıt yolu: {result['path']}\n{result.get('message', '')}"
                    )
                    self.status_var.set(f"Parite listesi hazır: {result['count']} kayıt")
                    self._log_line(message.replace("\n", " | "))
                    if result.get("unverified") and not result.get("verified_cached"):
                        message += "\n\nUyarı: aktif işlem durumu doğrulanmayan ticker yedeği kaydedilmiş olabilir; güçlü alarmlar bu kayıttan dolayı kapalı kalmalıdır."
                    messagebox.showinfo("Parite listesi", message)
                else:
                    self._log_line("Parite listesi yenilenemedi: " + str(result.get("error")))
                    messagebox.showerror("Parite listesi yenilenemedi", str(result.get("error")))
                continue
            if line.strip():
                LOGGER.info("ENGINE | %s", line)
                rendered.append(line)
        if rendered:
            self.log_view.configure(state="normal")
            for line in rendered[-80:]:
                self.log_view.insert("end", line + "\n")
            # Bound visible text so the panel does not grow without limit.
            line_count = int(self.log_view.index("end-1c").split(".")[0])
            if line_count > 220:
                self.log_view.delete("1.0", f"{line_count - 180}.0")
            self.log_view.see("end")
            self.log_view.configure(state="disabled")

    def _log_line(self, line: str) -> None:
        LOGGER.info(line)
        self.log_view.configure(state="normal")
        self.log_view.insert("end", line + "\n")
        line_count = int(self.log_view.index("end-1c").split(".")[0])
        if line_count > 220:
            self.log_view.delete("1.0", f"{line_count - 180}.0")
        self.log_view.see("end")
        self.log_view.configure(state="disabled")

    def _render_state(self, state: dict[str, Any]) -> None:
        status = str(state.get("status") or "Durum bilinmiyor")
        if self.engine is None and self.engine_started_epoch is None:
            status = f"MOTOR KAPALI — son kayıt: {status}"
        elif self.engine is None and self.engine_started_epoch is not None:
            status = status if status in ("BAŞLATMA HATASI", "TARAMA EVRENİ BEKLENİYOR") else "Motor durduruldu"
        self.status_var.set(status)
        count = state.get("scan_symbol_count", state.get("common_pair_count", "—"))
        mode = state.get("universe_mode") or "—"
        warning = str(state.get("universe_warning") or state.get("alert_filter_warning") or "").strip()
        self.universe_var.set(f"Tarama evreni: {count} | mod: {mode}" + (f" | {warning[:95]}" if warning else ""))
        connected = state.get("websocket_connected_shards", "—")
        total = state.get("websocket_total_shards", "—")
        ws_age = state.get("websocket_last_message_age_seconds")
        self.ws_var.set(f"WebSocket: {connected}/{total} parça | son veri: {_format_age(ws_age)}")
        self.alert_var.set("Güçlü alarm: açık" if self.alarm_enabled else "Güçlü alarm: kapalı")
        self.btc_context_var.set(_format_btc_context_summary(state))

        rows = state.get("candidates")
        if not isinstance(rows, list):
            rows = []
        normalized: dict[str, dict[str, Any]] = {}
        sortable = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or row.get("base_asset") or "").strip().upper()
            if not symbol:
                continue
            tf = str(row.get("phase_timeframe") or row.get("timeframe") or "")
            key = f"{symbol}|{tf}"
            normalized[key] = row
            sortable.append((row, key))
        # Strong, live C/B candidates first; no row is silently dropped by a UI cap.
        sortable.sort(key=lambda pair: (
            pair[0].get("data_freshness") == "CANLI AKIŞ GÜNCEL",
            pair[0].get("strong_alarm_eligible") is True,
            {"C": 3, "B": 2, "A": 1}.get(pair[0].get("phase") or pair[0].get("last_known_phase"), 0),
            _safe_float(pair[0].get("opportunity_score", pair[0].get("score_0_100"))) or -1,
        ), reverse=True)
        old_selection = self.tree.selection()
        selected = old_selection[0] if old_selection else self.current_candidate_key
        self.tree.delete(*self.tree.get_children())
        self.current_candidates = normalized
        for row, key in sortable:
            phase = row.get("phase") or row.get("last_known_phase") or "—"
            symbol = row.get("symbol") or row.get("base_asset") or "—"
            route = row.get("discovery_route") or row.get("discovery_path") or row.get("discovery_method") or "—"
            freshness = row.get("data_freshness") or "—"
            decision = row.get("final_decision") or row.get("decision_class") or row.get("state") or "—"
            strong = row.get("strong_opportunity_qualified") is True and row.get("strong_alarm_eligible") is True
            tags = ("strong",) if strong else (("stale",) if freshness != "CANLI AKIŞ GÜNCEL" else (f"phase_{str(phase).lower()}",) if phase in ("A", "B", "C") else ())
            self.tree.insert("", "end", iid=key, values=(
                "★" if strong else "", symbol, route, phase,
                _format_price(row.get("latest_price", row.get("price"))),
                _format_btc_relative(row), _format_btc_correlation(row),
                row.get("phase_timeframe") or row.get("timeframe") or "—",
                freshness, decision,
            ), tags=tags)
        if selected and selected in normalized:
            self.tree.selection_set(selected)
            self.tree.focus(selected)
            self.current_candidate_key = selected
            self._selection_changed()
        elif sortable:
            first_key = sortable[0][1]
            self.tree.selection_set(first_key)
            self.tree.focus(first_key)
            self.current_candidate_key = first_key
            self._selection_changed()
        else:
            self.current_candidate_key = None
            self._append_details(
                "Henüz aday kaydı yok.\n\n" +
                f"Motor durumu: {status}\n" +
                f"Başlangıç mum hazırlığı: {state.get('bootstrap_progress_pct', '—')}%\n\n" +
                "Tarama evreni doğrulanamıyorsa Parite listesini güncelle düğmesini kullanın."
            )
        if state.get("status") in ("BAŞLATMA HATASI", "TARAMA EVRENİ BEKLENİYOR"):
            if self._last_error_state_stamp != str(state.get("generated_at_utc")):
                self._last_error_state_stamp = str(state.get("generated_at_utc"))
                LOGGER.warning("Motor durumu: %s | %s", state.get("status"), state.get("error") or state.get("warning"))

    def _check_strong_alerts(self, state: dict[str, Any]) -> None:
        # A prior session's saved state may be displayed on panel launch, but must
        # never create a fresh alarm when the live engine is not running.
        if not self.engine or self.engine.poll() is not None:
            self._previous_strong_keys.clear()
            self._alarm_primed = False
            return
        if state.get("status") != "CANLI AKIŞ GÜNCEL":
            # Do not sound while the overall engine/history/WebSocket state is stale.
            self._previous_strong_keys.clear()
            self._alarm_primed = False
            return
        candidates = state.get("candidates")
        if not isinstance(candidates, list):
            return
        live: set[str] = set()
        for row in candidates:
            if not isinstance(row, dict):
                continue
            phase = row.get("phase")
            if (phase not in ("B", "C") or row.get("strong_alarm_eligible") is not True
                    or row.get("strong_opportunity_qualified") is not True
                    or row.get("data_freshness") != "CANLI AKIŞ GÜNCEL"):
                continue
            key = self._candidate_key(row)
            live.add(key)
            if self._alarm_primed and key not in self._previous_strong_keys and self.alarm_enabled and self.alarm_volume > 0:
                self._play_alert()
                LOGGER.info("Yeni güçlü fırsat alarmı: %s (%s)", key, phase)
        self._previous_strong_keys = live
        self._alarm_primed = True

    def toggle_alarm(self) -> None:
        self.alarm_enabled = not self.alarm_enabled
        self.panel_settings["alarm_sound_enabled"] = self.alarm_enabled
        self.alarm_button.configure(text="Alarm Açık" if self.alarm_enabled else "Alarm Kapalı")
        self.alert_var.set("Güçlü alarm: açık" if self.alarm_enabled else "Güçlü alarm: kapalı")
        self._save_panel_settings()
        self._log_line("Güçlü alarm sesi " + ("açıldı." if self.alarm_enabled else "kapatıldı."))

    def _volume_moved(self, _value: str | None = None) -> None:
        try:
            self.alarm_volume = max(0, min(100, int(float(self.volume_var.get()))))
        except (ValueError, tk.TclError):
            self.alarm_volume = 55
        self.volume_label.configure(text=f"{self.alarm_volume}%")

    def _save_volume(self, _event: Any = None) -> None:
        self._volume_moved()
        self.panel_settings["alarm_volume"] = self.alarm_volume
        self._save_panel_settings()

    def _brightness_moved(self, _value: str | None = None) -> None:
        try:
            self.panel_brightness = max(60, min(100, int(float(self.brightness_var.get()))))
        except (ValueError, tk.TclError):
            self.panel_brightness = 85
        self._apply_brightness()

    def _save_brightness(self, _event: Any = None) -> None:
        self._brightness_moved()
        self.panel_settings["panel_brightness"] = self.panel_brightness
        self._save_panel_settings()

    def _save_panel_settings(self) -> None:
        # Update only panel_ui fields; preserve every engine/risk setting.
        try:
            current = _read_json(SETTINGS_PATH, {})
            if not isinstance(current, dict):
                current = {}
            ui = current.get("panel_ui")
            if not isinstance(ui, dict):
                ui = {}
            ui.update({
                "alarm_sound_enabled": bool(self.alarm_enabled),
                "alarm_volume": int(self.alarm_volume),
                "panel_brightness": int(self.panel_brightness),
            })
            current["panel_ui"] = ui
            _write_json_atomic(SETTINGS_PATH, current)
            self.settings = current
            self.panel_settings = ui
        except Exception as exc:
            LOGGER.exception("Panel ses ayarları kaydedilemedi: %s", exc)

    def _write_alarm_wave(self) -> Path:
        """Create a volume-scaled PCM tone; Windows playback supports actual amplitude scaling."""
        path = RUN_DIR / "panel_alert.wav"
        sample_rate = 22050
        amplitude = int(26000 * (self.alarm_volume / 100.0))
        segments = [(880.0, 0.12), (0.0, 0.05), (1175.0, 0.20)]
        data = bytearray()
        for frequency, duration in segments:
            count = int(sample_rate * duration)
            for i in range(count):
                envelope = min(1.0, i / max(1, sample_rate * 0.01), (count - i) / max(1, sample_rate * 0.015))
                sample = 0 if frequency == 0 else int(amplitude * max(0.0, envelope) * math.sin(2.0 * math.pi * frequency * i / sample_rate))
                data.extend(struct.pack("<h", max(-32767, min(32767, sample))))
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(bytes(data))
        return path

    def _play_alert(self) -> None:
        if not self.alarm_enabled or self.alarm_volume <= 0:
            return
        if os.name == "nt":
            try:
                import winsound
                path = self._write_alarm_wave()
                winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                return
            except (OSError, RuntimeError, wave.Error):
                pass
        try:
            self.bell()
        except tk.TclError:
            pass

    def _test_sound(self) -> None:
        if self.alarm_volume <= 0:
            messagebox.showinfo("Ses testi", "Ses seviyesi %0; test sesi kapalı.")
            return
        enabled_before = self.alarm_enabled
        self.alarm_enabled = True
        self._play_alert()
        self.alarm_enabled = enabled_before

    def toggle_level_watch(self) -> None:
        if self._level_watch_key:
            self._level_watch_key = None
            self._level_previous_price = None
            self._level_crossed.clear()
            self.level_var.set("Seviye takibi: kapalı")
            self._log_line("Seviye takibi kapatıldı.")
            return
        if not self.engine or self.engine.poll() is not None:
            messagebox.showwarning("Seviye takibi açılamadı", "Seviye takibi için motorun çalışıyor ve canlı veri üretiyor olması gerekir.")
            return
        candidate = self._selected_candidate()
        if not candidate:
            messagebox.showinfo("Seviye takibi", "Önce aday tablosundan bir coin seçin.")
            return
        plan = candidate.get("risk_plan")
        if not isinstance(plan, dict) or plan.get("status") in (None, "VERİ ESKİ — PLAN YOK", "UYGUN DEĞİL", "HESAPLANAMADI"):
            messagebox.showwarning("Seviye takibi açılamadı", str((plan or {}).get("reason") if isinstance(plan, dict) else "Geçerli koşullu risk planı yok."))
            return
        if candidate.get("data_freshness") != "CANLI AKIŞ GÜNCEL":
            messagebox.showwarning("Seviye takibi açılamadı", "Coinin güncel canlı veri durumu doğrulanmadı.")
            return
        price = _safe_float(candidate.get("latest_price"))
        if price is None or price <= 0:
            messagebox.showwarning("Seviye takibi açılamadı", "Güncel fiyat bulunamadı.")
            return
        self._level_watch_key = self._candidate_key(candidate)
        self._level_previous_price = price
        self._level_crossed.clear()
        self.level_var.set(f"Seviye takibi: {self._level_watch_key}")
        self._log_line(f"Seviye takibi açıldı: {self._level_watch_key}; mevcut fiyat başlangıç seviyesi kabul edildi.")

    def _check_level_watch(self, state: dict[str, Any]) -> None:
        key = self._level_watch_key
        if not key:
            return
        candidate = self.current_candidates.get(key)
        if not candidate or candidate.get("data_freshness") != "CANLI AKIŞ GÜNCEL" or state.get("status") != "CANLI AKIŞ GÜNCEL":
            # On stale data, wait and re-baseline when live data resumes; never infer crossings during a gap.
            self._level_previous_price = None
            return
        plan = candidate.get("risk_plan")
        price = _safe_float(candidate.get("latest_price"))
        if not isinstance(plan, dict) or price is None or price <= 0:
            self._level_previous_price = None
            return
        if self._level_previous_price is None:
            self._level_previous_price = price
            return
        previous = self._level_previous_price
        events: list[str] = []
        low, high = _safe_float(plan.get("entry_zone_low")), _safe_float(plan.get("entry_zone_high"))
        breakout = _safe_float(plan.get("breakout_level"))
        stop = _safe_float(plan.get("stop_loss"))
        if low is not None and high is not None and min(previous, price) <= high and max(previous, price) >= low:
            if (previous < low and price >= low) or (previous > high and price <= high) or low <= price <= high and not low <= previous <= high:
                events.append("Giriş bölgesine giriş")
        if breakout is not None and previous <= breakout < price:
            events.append("Yukarı yönlü kırılım seviyesi geçildi")
        if stop is not None and previous >= stop > price:
            events.append("Zarar durdurma seviyesi aşağı geçildi")
        targets = plan.get("targets")
        if isinstance(targets, list):
            for index, target in enumerate(targets, start=1):
                if not isinstance(target, dict):
                    continue
                target_price = _safe_float(target.get("price"))
                label = str(target.get("name") or f"Teknik hedef {index}")
                event_key = f"target:{target_price}"
                if target_price is not None:
                    if price < target_price <= previous:
                        self._level_crossed.discard(event_key)
                    if previous <= target_price < price and event_key not in self._level_crossed:
                        events.append(f"{label} geçildi")
                        self._level_crossed.add(event_key)
        if events:
            for event in events:
                self._log_line(f"SEVİYE ALARMI | {key} | {event} | fiyat={_format_price(price)}")
            if self.alarm_enabled:
                self._play_alert()
        self._level_previous_price = price

    def _diagnostic_payload(self) -> dict[str, Any]:
        config = _read_json(SETTINGS_PATH, {})
        if not isinstance(config, dict):
            config = {}
        fan = config.get("fan_token_bases_to_skip", [])
        stable = config.get("stablecoin_bases_no_strong_alarm", [])
        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "application": APP_TITLE,
            "python_version": sys.version.split()[0],
            "engine_source_exists": ENGINE_PATH.is_file(),
            "state_file_exists": STATE_PATH.is_file(),
            "settings": {
                "path": str(SETTINGS_PATH),
                "exists": SETTINGS_PATH.is_file(),
                "size_bytes": SETTINGS_PATH.stat().st_size if SETTINGS_PATH.is_file() else None,
                "sha256": _sha256_file(SETTINGS_PATH),
                "fan_token_exclusion_count": len(fan) if isinstance(fan, list) else None,
                "stablecoin_exclusion_count": len(stable) if isinstance(stable, list) else None,
            },
            "engine_status": self.current_state.get("status"),
            "state_generated_at_utc": self.current_state.get("generated_at_utc"),
            "universe_mode": self.current_state.get("universe_mode"),
            "scan_symbol_count": self.current_state.get("scan_symbol_count"),
            "websocket_connected_shards": self.current_state.get("websocket_connected_shards"),
            "websocket_total_shards": self.current_state.get("websocket_total_shards"),
            "candidate_count": len(self.current_candidates),
            "note": "Tanı özeti ayarların tam içeriğini içermez. Komisyon ve kayma hesaplanmaz; teknik risk/getiri oranı brüt olarak değerlendirilir.",
        }

    def _make_report(self) -> tuple[Path, Path, Path, str]:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"firsat_kontrol_raporu_{stamp}"
        payload = {
            "report_generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "state": self.current_state,
            "diagnostics": self._diagnostic_payload(),
        }
        json_path = REPORT_DIR / f"{base}.json"
        md_path = REPORT_DIR / f"{base}.md"
        diagnostic_path = REPORT_DIR / f"{base}_tani.json"
        _write_json_atomic(json_path, payload)
        _write_json_atomic(diagnostic_path, payload["diagnostics"])
        candidates = self.current_state.get("candidates") if isinstance(self.current_state.get("candidates"), list) else []
        table_rows = []
        for row in candidates:
            if not isinstance(row, dict):
                continue
            symbol = row.get("symbol") or row.get("base_asset") or "—"
            phase = row.get("phase") or row.get("last_known_phase") or "—"
            score = row.get("opportunity_score", row.get("score_0_100", "—"))
            table_rows.append((str(symbol), str(phase), _format_price(row.get("latest_price")), str(row.get("phase_timeframe") or "—"), str(row.get("final_decision") or row.get("state") or "—"), str(score)))
        markdown = [
            f"# {APP_TITLE} — Durum Raporu", "",
            f"- Rapor zamanı (UTC): {payload['report_generated_at_utc']}",
            f"- Motor durumu: {self.current_state.get('status', 'bilinmiyor')}",
            f"- Tarama evreni: {self.current_state.get('scan_symbol_count', '—')}",
            f"- WebSocket bağlantıları: {self.current_state.get('websocket_connected_shards', '—')}/{self.current_state.get('websocket_total_shards', '—')}",
            f"- Aday sayısı: {len(table_rows)}", "",
            "## BTC piyasa bağlamı", "",
            _format_btc_context_summary(self.current_state), "",
            "## Aday özeti", "",
            "| Coin | Aşama | Fiyat (USDT) | Zaman dilimi | Karar | Puan |",
            "|---|---:|---:|---|---|---:|",
        ]
        for symbol, phase, price, tf, decision, score in table_rows[:100]:
            markdown.append(f"| {symbol} | {phase} | {price} | {tf} | {decision.replace('|', '/')} | {score} |")
        if len(table_rows) > 100:
            markdown.append(f"\nİlk 100 satır gösterildi; JSON dosyasında {len(table_rows)} adayın tamamı bulunur.")
        markdown.extend([
            "", "## Güvenlik ve yorum", "",
            "A/B/C araştırma aşamalarıdır; alım emri veya kârlılık garantisi değildir. Program emir göndermez.",
            "Fiyat/stop/hedef planları koşullu teknik senaryolardır. Komisyon ve kayma hesaplanmaz; spread ayrı likidite filtresinde değerlendirilir. Gerçek emir/dolum ve BtcTurk uygulanabilirliği bu programda doğrulanmaz.",
            "", "## Tanı bilgisi", "", "Ayrıntılar JSON raporundaki diagnostics alanında saklanır. Tam ayarlar.json içeriği rapora kopyalanmaz.", "",
        ])
        md_path.write_text("\n".join(markdown), encoding="utf-8")
        LOGGER.info("Rapor oluşturuldu: %s", json_path.name)
        return json_path, md_path, diagnostic_path, "\n".join(markdown)

    def create_report(self) -> None:
        try:
            json_path, md_path, _diagnostic, markdown = self._make_report()
            self.clipboard_clear()
            self.clipboard_append(markdown)
            self.update_idletasks()
            self._open_select(json_path)
            messagebox.showinfo("Rapor hazır", f"Rapor dosyaları oluşturuldu:\n{json_path}\n{md_path}\n\nMarkdown metni panoya kopyalandı.")
        except Exception as exc:
            LOGGER.exception("Rapor oluşturulamadı")
            messagebox.showerror("Rapor oluşturulamadı", f"{type(exc).__name__}: {exc}")

    def create_handoff_zip(self) -> None:
        try:
            json_path, md_path, diagnostic_path, markdown = self._make_report()
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_path = REPORT_DIR / f"firsat_kontrol_devir_{stamp}.zip"
            log_tail = _tail_text([PANEL_LOG_PATH, ENGINE_LOG_PATH], max_lines=300, max_bytes=128 * 1024)
            manifest: dict[str, Any] = {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "files": [],
                "limits": {"log_tail_max_lines": 300, "log_tail_max_bytes": 128 * 1024},
            }
            temporary = zip_path.with_name(f".{zip_path.name}.{os.getpid()}.{time.time_ns()}.tmp")
            files = [json_path, md_path, diagnostic_path]
            if log_tail:
                files.append(None)
            try:
                with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                    for path in files:
                        if path is None:
                            raw = log_tail.encode("utf-8", errors="replace")
                            name = "diagnostics/log_tail.txt"
                        else:
                            raw = path.read_bytes()
                            name = f"reports/{path.name}"
                        archive.writestr(name, raw)
                        manifest["files"].append({"name": name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
                    state_summary = json.dumps(
                        self._diagnostic_payload(), ensure_ascii=False, indent=2
                    ).encode("utf-8")
                    archive.writestr("diagnostics/state_summary.json", state_summary)
                    manifest["files"].append({
                        "name": "diagnostics/state_summary.json",
                        "size_bytes": len(state_summary),
                        "sha256": hashlib.sha256(state_summary).hexdigest(),
                    })
                    archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"))
                with zipfile.ZipFile(temporary, "r") as check:
                    bad = check.testzip()
                    if bad:
                        raise ValueError(f"ZIP bütünlük denetimi başarısız: {bad}")
                    for entry in manifest["files"]:
                        raw = check.read(entry["name"])
                        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                            raise ValueError(f"ZIP SHA-256 doğrulaması başarısız: {entry['name']}")
                os.replace(temporary, zip_path)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            self.clipboard_clear()
            self.clipboard_append("\n".join([
                f"Fırsat-Kontrol Paneli devir paketi: {zip_path.name}",
                f"Motor durumu: {self.current_state.get('status', 'bilinmiyor')}",
                f"Aday sayısı: {len(self.current_candidates)}",
                "Ayrıntılı rapor, tanı özeti ve sınırlı günlük eki ZIP içinde.",
            ]))
            self.update_idletasks()
            self._open_select(zip_path)
            self._log_line(f"Rapor + Devir ZIP oluşturuldu: {zip_path.name}")
            messagebox.showinfo("Devir paketi hazır", f"ZIP oluşturuldu ve bütünlük denetimi geçti:\n{zip_path}\n\nPanoya kısa devir özeti kopyalandı.")
        except Exception as exc:
            LOGGER.exception("Devir ZIP oluşturulamadı")
            messagebox.showerror("Devir ZIP oluşturulamadı", f"{type(exc).__name__}: {exc}")

    def _open_select(self, path: Path) -> None:
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer.exe", "/select,", str(path)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, str(path.parent)])
        except OSError as exc:
            LOGGER.warning("Dosya Gezgini açılamadı: %s", exc)

    def open_logs(self) -> None:
        try:
            if os.name == "nt":
                os.startfile(str(LOG_DIR))  # type: ignore[attr-defined]
            else:
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, str(LOG_DIR)])
        except OSError as exc:
            messagebox.showerror("Klasör açılamadı", str(exc))

    def _on_close(self) -> None:
        if self.engine and self.engine.poll() is None:
            if not messagebox.askyesno("Paneli kapat", "Motor çalışıyor. Kontrollü durdurma isteği gönderip panel kapatılsın mı?"):
                return
            self.close_after_stop = True
            self.stop_engine()
            self.status_var.set("Motor kapanması bekleniyor…")
            return
        self.destroy()


def main() -> int:
    try:
        app = ControlPanel()
        app.mainloop()
        return 0
    except Exception:
        LOGGER.exception("Arayüz başlatılamadı")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
