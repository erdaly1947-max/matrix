"""Focused regression checks for the current Sürüm 00 motor/panel defects."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

import unittest

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import binance_erken_firsat_radari as engine

_loader = importlib.machinery.SourceFileLoader("panel_for_tests", str(ROOT / "tek_motor_paneli.pyw"))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
panel = importlib.util.module_from_spec(_spec)
_loader.exec_module(panel)



class RuntimeStatusSeparationTests(unittest.TestCase):
    def test_websocket_snapshot_accepts_recent_shards(self):
        assert engine._websocket_streams_have_fresh_data(
            {0: "BAĞLI", 1: "BAĞLI"}, {0: 100.0, 1: 99.7},
            now=100.2, stale_limit=10.0,
        )


    def test_websocket_snapshot_clock_is_taken_after_message_snapshot(self):
        messages = {}

        class MessageArrivalLock:
            def __enter__(self):
                # Simulate a WebSocket callback arriving just before the snapshot acquires
                # its lock. With the old ordering, the clock could precede this timestamp.
                messages[0] = 100.05
                return self

            def __exit__(self, *_args):
                return False

        statuses, snapshot_messages, connected_at, apps, now = (
            engine._snapshot_websocket_runtime_state(
                MessageArrivalLock(), {0: "BAĞLI"}, messages, {}, {}, wall_clock=lambda: 100.06,
            )
        )
        assert statuses == {0: "BAĞLI"}
        assert snapshot_messages == {0: 100.05}
        assert connected_at == {}
        assert apps == {}
        assert now - snapshot_messages[0] >= 0


    def test_websocket_health_rejects_a_negative_age(self):
        # The engine snapshot code must prevent creating this condition in the first place;
        # the validator itself must continue rejecting it rather than weakening the gate.
        assert not engine._websocket_streams_have_fresh_data(
            {0: "BAĞLI"}, {0: 100.1}, now=100.0, stale_limit=10.0,
        )


    def test_unresolved_history_gap_does_not_change_live_stream_status(self):
        assert engine._live_stream_status_label(
            ws_healthy=True, settings_changed_since_load=False,
        ) == "CANLI AKIŞ GÜNCEL"
        assert engine._history_status_label(
            history_ready=False, bootstrap_in_progress=False,
        ) == "GEÇMİŞ MUM HAZIRLIĞI EKSİK"


    def test_settings_change_still_blocks_live_status(self):
        assert engine._live_stream_status_label(
            ws_healthy=True, settings_changed_since_load=True,
        ) == "AYARLAR DEĞİŞTİ — MOTORU YENİDEN BAŞLATIN"


    def test_panel_ui_only_settings_changes_do_not_require_engine_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ayarlar.json"
            initial = {
                "scan_refresh_seconds": 15,
                "websocket_stale_seconds_binance": 45,
                "panel_ui": {"alarm_sound_enabled": True, "alarm_volume": 55},
            }
            path.write_text(json.dumps(initial), encoding="utf-8")
            _loaded_settings, loaded = engine.load_settings_snapshot(path)

            changed = {
                **initial,
                "panel_ui": {"alarm_sound_enabled": False, "alarm_volume": 80, "panel_brightness": 75},
            }
            path.write_text(json.dumps(changed), encoding="utf-8")
            _current_settings, current = engine.load_settings_snapshot(path)

            assert loaded["settings_sha256"] != current["settings_sha256"]
            assert loaded["settings_runtime_sha256"] == current["settings_runtime_sha256"]
            assert not engine._settings_snapshot_changed(loaded, current)

    def test_engine_setting_changes_still_require_engine_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ayarlar.json"
            initial = {
                "scan_refresh_seconds": 15,
                "panel_ui": {"alarm_volume": 55},
            }
            path.write_text(json.dumps(initial), encoding="utf-8")
            _loaded_settings, loaded = engine.load_settings_snapshot(path)

            changed = {
                **initial,
                "scan_refresh_seconds": 30,
                "panel_ui": {"alarm_volume": 80},
            }
            path.write_text(json.dumps(changed), encoding="utf-8")
            _current_settings, current = engine.load_settings_snapshot(path)

            assert loaded["settings_runtime_sha256"] != current["settings_runtime_sha256"]
            assert engine._settings_snapshot_changed(loaded, current)

    def test_invalid_settings_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ayarlar.json"
            path.write_text('{"scan_refresh_seconds": 15}', encoding="utf-8")
            _loaded_settings, loaded = engine.load_settings_snapshot(path)
            path.write_text('{"scan_refresh_seconds": ', encoding="utf-8")
            _current_settings, current = engine.load_settings_snapshot(path)
            assert engine._settings_snapshot_changed(loaded, current)

    def test_strong_alert_can_run_when_global_history_status_is_warning(self):
        played = []
        fake = SimpleNamespace(
            engine=SimpleNamespace(poll=lambda: None),
            _previous_strong_keys=set(),
            _alarm_primed=True,
            alarm_enabled=True,
            alarm_volume=50,
            _candidate_key=lambda row: f"{row['symbol']}|{row['phase_timeframe']}",
            _play_alert=lambda: played.append(True),
        )
        state = {
            "status": "BAĞLANTI/VERİ UYARISI",
            "live_stream_status": "CANLI AKIŞ GÜNCEL",
            "candidates": [{
                "symbol": "TESTUSDT", "phase_timeframe": "15m", "phase": "C",
                "strong_alarm_eligible": True,
                "strong_opportunity_qualified": True,
                "data_freshness": "CANLI AKIŞ GÜNCEL",
            }],
        }
        panel.ControlPanel._check_strong_alerts(fake, state)
        assert played == [True]


    def test_strong_alert_still_requires_candidate_level_freshness(self):
        played = []
        fake = SimpleNamespace(
            engine=SimpleNamespace(poll=lambda: None),
            _previous_strong_keys=set(),
            _alarm_primed=True,
            alarm_enabled=True,
            alarm_volume=50,
            _candidate_key=lambda row: f"{row['symbol']}|{row['phase_timeframe']}",
            _play_alert=lambda: played.append(True),
        )
        state = {
            "status": "BAĞLANTI/VERİ UYARISI",
            "live_stream_status": "CANLI AKIŞ GÜNCEL",
            "candidates": [{
                "symbol": "TESTUSDT", "phase_timeframe": "15m", "phase": "C",
                "strong_alarm_eligible": True,
                "strong_opportunity_qualified": True,
                "data_freshness": "CANLI VERİ ESKİ/EKSİK",
            }],
        }
        panel.ControlPanel._check_strong_alerts(fake, state)
        assert played == []


    def test_level_watch_uses_live_stream_state_not_global_history_warning(self):
        logged = []
        key = "TESTUSDT|15m"
        candidate = {
            "symbol": "TESTUSDT", "phase_timeframe": "15m",
            "data_freshness": "CANLI AKIŞ GÜNCEL", "latest_price": 1.05,
            "risk_plan": {
                "status": "GEÇERLİ KOŞULLU PLAN",
                "entry_zone_low": 1.0, "entry_zone_high": 1.1,
                "breakout_level": 1.2, "stop_loss": 0.8,
                "targets": [],
            },
        }
        fake = SimpleNamespace(
            _level_watch_key=key, current_candidates={key: candidate},
            _level_previous_price=0.95, _level_crossed=set(),
            alarm_enabled=False, _log_line=logged.append,
            _play_alert=lambda: None,
        )
        panel.ControlPanel._check_level_watch(fake, {
            "status": "BAĞLANTI/VERİ UYARISI",
            "live_stream_status": "CANLI AKIŞ GÜNCEL",
        })
        assert any("Giriş bölgesine giriş" in line for line in logged)
        assert fake._level_previous_price == 1.05


    def test_legacy_state_without_separate_live_status_remains_conservative(self):
        played = []
        fake = SimpleNamespace(
            engine=SimpleNamespace(poll=lambda: None),
            _previous_strong_keys=set(), _alarm_primed=True,
            alarm_enabled=True, alarm_volume=50,
            _candidate_key=lambda row: f"{row['symbol']}|{row['phase_timeframe']}",
            _play_alert=lambda: played.append(True),
        )
        state = {
            "status": "BAĞLANTI/VERİ UYARISI",
            "candidates": [{
                "symbol": "TESTUSDT", "phase_timeframe": "15m", "phase": "C",
                "strong_alarm_eligible": True,
                "strong_opportunity_qualified": True,
                "data_freshness": "CANLI AKIŞ GÜNCEL",
            }],
        }
        panel.ControlPanel._check_strong_alerts(fake, state)
        assert played == []


    def test_known_unfilled_history_gaps_are_not_retried_every_five_minutes(self):
        errors = [
            "CVCUSDT 1M: Binance'ten tamamlanamayan mum aralığı var (1 boşluk).",
            "USDCUSDT 1M: Binance'ten tamamlanamayan mum aralığı var (1 boşluk).",
        ]
        assert engine._history_retry_delay_seconds(errors, scheduled_delay=300) == 86400


    def test_transient_history_errors_keep_the_normal_retry_delay(self):
        errors = [
            "CVCUSDT 1M: Binance'ten tamamlanamayan mum aralığı var (1 boşluk).",
            "ReadTimeout: Binance data request timed out",
        ]
        assert engine._history_retry_delay_seconds(errors, scheduled_delay=300) == 300
