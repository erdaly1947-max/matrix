"""Sinyal dönemlerini ve ileri fiyat gözlemlerini kalıcı kaydeder.

Bu kayıtlar kârlılık kanıtı değildir. Sonraki analiz için sinyal anını,
izleme sırasındaki MFE/MAE'yi ve 30m/1h/4h/24h gözlemlerini saklar.
"""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing, contextmanager
import time
from typing import Any

from radar_core import ROOT

DB_PATH = ROOT / "data" / "sinyal_gecmisi.sqlite3"


class SignalTracker:
    def __init__(self, inactive_after_missing_cycles: int = 3, sample_seconds: int = 60):
        self.inactive_after_missing_cycles = max(1, int(inactive_after_missing_cycles))
        self.sample_seconds = max(10, int(sample_seconds))
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                started_utc TEXT NOT NULL,
                start_epoch REAL NOT NULL,
                start_price REAL,
                latest_price REAL,
                max_price REAL,
                min_price REAL,
                mfe_pct REAL,
                mae_pct REAL,
                return_30m_pct REAL,
                return_1h_pct REAL,
                return_4h_pct REAL,
                return_24h_pct REAL,
                phase TEXT,
                state TEXT,
                timeframe TEXT,
                reasons_json TEXT,
                metrics_json TEXT,
                last_seen_utc TEXT NOT NULL,
                last_seen_epoch REAL NOT NULL,
                last_sample_epoch REAL NOT NULL DEFAULT 0,
                missing_cycles INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                closed_utc TEXT,
                coverage_note TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_episodes_exchange_symbol ON episodes(exchange,symbol,active);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id INTEGER NOT NULL,
                event_epoch REAL NOT NULL,
                event_utc TEXT NOT NULL,
                event_type TEXT NOT NULL,
                phase TEXT,
                state TEXT,
                price REAL,
                reasons_json TEXT,
                metrics_json TEXT,
                FOREIGN KEY(episode_id) REFERENCES episodes(id)
            );
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id INTEGER NOT NULL,
                sample_epoch REAL NOT NULL,
                sample_utc TEXT NOT NULL,
                price REAL,
                phase TEXT,
                state TEXT,
                FOREIGN KEY(episode_id) REFERENCES episodes(id)
            );
            """)

    def _connect(self):
        conn = sqlite3.connect(DB_PATH, timeout=20)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        """Commit/rollback and always close SQLite connections on Windows and Unix."""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()
    @staticmethod
    def _utc(epoch: float) -> str:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    def record(self, exchange: str, candidates: list[dict[str, Any]],
               prices_by_base: dict[str, float], *, source_complete: bool) -> dict[str, int]:
        now = time.time()
        now_utc = self._utc(now)
        rows_by_symbol = {
            str(row.get("base_asset") or row.get("symbol", "").removesuffix("USDT")).upper(): row
            for row in candidates if isinstance(row, dict)
        }
        eligible = {symbol: row for symbol, row in rows_by_symbol.items()
                    if row.get("phase") in ("A", "B", "C")}
        new_count = transition_count = closed_count = sample_count = 0
        with self._connection() as conn:
            active_rows = conn.execute(
                "SELECT * FROM episodes WHERE exchange=? AND active=1", (exchange,)
            ).fetchall()
            active_by_symbol = {str(row["symbol"]): row for row in active_rows}

            for symbol, candidate in eligible.items():
                price = _positive_float(prices_by_base.get(symbol, candidate.get("latest_price")))
                phase = str(candidate.get("phase"))
                state = str(candidate.get("state") or "BELİRLENMEDİ")
                tf = str(candidate.get("phase_timeframe") or candidate.get("timeframe") or "")
                reasons = candidate.get("findings", [])
                raw_score = candidate.get("opportunity_score", candidate.get("score_0_100"))
                opportunity_score = (
                    float(raw_score)
                    if isinstance(raw_score, (int, float))
                    and not isinstance(raw_score, bool)
                    and math.isfinite(float(raw_score))
                    and 0.0 <= float(raw_score) <= 100.0
                    else None
                )
                raw_decision = candidate.get("final_decision") or candidate.get("decision_class")
                final_decision = (
                    raw_decision.strip()
                    if isinstance(raw_decision, str) and raw_decision.strip()
                    else None
                )
                metrics = {
                    "final_decision": final_decision,
                    "decision_class": final_decision,
                    "opportunity_score": opportunity_score,
                    "score_0_100": opportunity_score,
                    "score_components": candidate.get("score_components", {}),
                    "decision_reason": candidate.get("decision_reason"),
                    "strong_alarm_eligible": candidate.get("strong_alarm_eligible") is True,
                    "strong_alarm_block_reason": candidate.get("strong_alarm_block_reason"),
                    "data_freshness": candidate.get("data_freshness"),
                    "strong_opportunity_qualified": candidate.get("strong_opportunity_qualified"),
                    "strong_opportunity_gate_reasons": candidate.get("strong_opportunity_gate_reasons", []),
                    "risk_plan": candidate.get("risk_plan"),
                    "liquidity_assessment": candidate.get("liquidity_assessment"),
                    "btc_market_context": candidate.get("btc_market_context"),
                    "evidence_groups": candidate.get("evidence_groups", []),
                    "missing_checks": candidate.get("missing_checks", []),
                    "timeframes": candidate.get("timeframes", {}),
                    "relative_strength_vs_btc_pct_points": candidate.get("relative_strength_vs_btc_pct_points", {}),
                    "btc_return_correlation": candidate.get("btc_return_correlation", {}),
                    "group_category": candidate.get("group_category"),
                    "group_category_verified": candidate.get("group_category_verified"),
                    "group_category_source": candidate.get("group_category_source"),
                    "group_comparable_count": candidate.get("group_comparable_count"),
                    "group_leadership_score": candidate.get("group_leadership_score"),
                    "group_leadership_basis": candidate.get("group_leadership_basis"),
                    "group_leadership_summary": candidate.get("group_leadership_summary"),
                    "forward_return_observed_elapsed_seconds": {},
                }
                existing = active_by_symbol.get(symbol)
                candidate_evaluation = _build_technical_plan_evaluation(
                    candidate, now_epoch=now, now_utc=now_utc
                )
                if existing is None:
                    if candidate_evaluation is not None:
                        metrics["evaluation_plan"] = candidate_evaluation
                    cursor = conn.execute("""
                        INSERT INTO episodes(exchange,symbol,started_utc,start_epoch,start_price,latest_price,
                          max_price,min_price,mfe_pct,mae_pct,phase,state,timeframe,reasons_json,metrics_json,
                          last_seen_utc,last_seen_epoch,active,coverage_note)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (exchange, symbol, now_utc, now, price, price, price, price, 0.0, 0.0,
                          phase, state, tf, self._json(reasons), self._json(metrics), now_utc, now, 1,
                          "Fiyat gözlemleri yalnızca program çalışırken gelen örnekleri kapsar; boşluklar kesin MFE/MAE sağlamaz."))
                    episode_id = int(cursor.lastrowid)
                    conn.execute("""INSERT INTO events(episode_id,event_epoch,event_utc,event_type,phase,state,price,reasons_json,metrics_json)
                                    VALUES(?,?,?,?,?,?,?,?,?)""",
                                 (episode_id, now, now_utc, "SİNYAL BAŞLADI", phase, state, price,
                                  self._json(reasons), self._json(metrics)))
                    new_count += 1
                else:
                    episode_id = int(existing["id"])
                    old_phase, old_state = existing["phase"], existing["state"]
                    old_metrics: dict[str, Any] = {}
                    try:
                        parsed_metrics = json.loads(existing["metrics_json"] or "{}")
                        if isinstance(parsed_metrics, dict):
                            old_metrics = parsed_metrics
                    except (TypeError, ValueError):
                        pass
                    old_forward_elapsed = old_metrics.get("forward_return_observed_elapsed_seconds")
                    if isinstance(old_forward_elapsed, dict):
                        metrics["forward_return_observed_elapsed_seconds"] = dict(old_forward_elapsed)
                    old_evaluation = old_metrics.get("evaluation_plan")
                    if isinstance(old_evaluation, dict):
                        metrics["evaluation_plan"] = old_evaluation
                    elif candidate_evaluation is not None:
                        metrics["evaluation_plan"] = candidate_evaluation
                    old_final_decision = old_metrics.get("final_decision") or old_metrics.get("decision_class")
                    decision_changed = (
                        isinstance(old_final_decision, str)
                        and isinstance(final_decision, str)
                        and old_final_decision != final_decision
                    )
                    old_alarm_permission = old_metrics.get("strong_alarm_eligible")
                    current_alarm_permission = metrics["strong_alarm_eligible"]
                    alarm_permission_changed = (
                        isinstance(old_alarm_permission, bool)
                        and old_alarm_permission != current_alarm_permission
                    )
                    changed = (
                        existing["phase"] != phase
                        or existing["state"] != state
                        or decision_changed
                        or alarm_permission_changed
                    )
                    conn.execute("""UPDATE episodes SET latest_price=?, phase=?, state=?, timeframe=?,
                                  reasons_json=?, metrics_json=?, last_seen_utc=?, last_seen_epoch=?,
                                  missing_cycles=0 WHERE id=?""",
                                 (price, phase, state, tf, self._json(reasons), self._json(metrics),
                                  now_utc, now, episode_id))
                    if changed:
                        event_type = (
                            "NİHAİ KARAR DEĞİŞTİ" if decision_changed
                            else "GÜÇLÜ ALARM UYGUNLUĞU DEĞİŞTİ" if alarm_permission_changed
                            else "AŞAMA DEĞİŞTİ" if old_phase != phase
                            else "DURUM DEĞİŞTİ"
                        )
                        event_metrics = {
                            **metrics,
                            "previous_phase": old_phase,
                            "previous_state": old_state,
                            "previous_final_decision": old_final_decision,
                            "previous_strong_alarm_eligible": old_alarm_permission,
                            "previous_strong_alarm_block_reason": old_metrics.get("strong_alarm_block_reason"),
                        }
                        conn.execute("""INSERT INTO events(episode_id,event_epoch,event_utc,event_type,phase,state,price,reasons_json,metrics_json)
                                        VALUES(?,?,?,?,?,?,?,?,?)""",
                                     (episode_id, now, now_utc, event_type, phase, state, price,
                                      self._json(reasons), self._json(event_metrics)))
                        transition_count += 1

            # Sinyalin kaybolduğunu yalnızca kaynak/veri döngüsü yeterince sağlıklıysa değerlendir.
            if source_complete:
                for existing in active_rows:
                    symbol = str(existing["symbol"])
                    if symbol in eligible:
                        continue
                    current_row = rows_by_symbol.get(symbol)
                    # A stale row pauses the close timer. A missing row in a complete,
                    # healthy scan keeps the existing "not in current universe" behavior.
                    if (current_row is not None and "data_freshness" in current_row
                            and current_row.get("data_freshness") != "CANLI AKIŞ GÜNCEL"):
                        continue
                    miss = int(existing["missing_cycles"] or 0) + 1
                    episode_id = int(existing["id"])
                    if miss >= self.inactive_after_missing_cycles:
                        conn.execute("UPDATE episodes SET active=0,missing_cycles=?,closed_utc=? WHERE id=?",
                                     (miss, now_utc, episode_id))
                        conn.execute("""INSERT INTO events(episode_id,event_epoch,event_utc,event_type,phase,state,price,reasons_json,metrics_json)
                                        VALUES(?,?,?,?,?,?,?,?,?)""",
                                     (episode_id, now, now_utc, "SİNYAL AKTİFLİĞİNİ KAYBETTİ",
                                      existing["phase"], "AKTİF DEĞİL", prices_by_base.get(symbol),
                                      "[]", self._json({"neden": "Aday koşulları art arda tarama döngülerinde görülmedi"})))
                        closed_count += 1
                    else:
                        conn.execute("UPDATE episodes SET missing_cycles=? WHERE id=?", (miss, episode_id))

            # Takip ufku içinde aynı coin için gelen fiyatları ileri gözleme ve MFE/MAE'ye kaydet.
            tracked = conn.execute("SELECT * FROM episodes WHERE start_epoch >= ?", (now - 24 * 3600,)).fetchall()
            horizons = (("return_30m_pct", 30 * 60), ("return_1h_pct", 60 * 60),
                        ("return_4h_pct", 4 * 3600), ("return_24h_pct", 24 * 3600))
            for episode in tracked:
                symbol = str(episode["symbol"])
                price = _positive_float(prices_by_base.get(symbol))
                if price is None:
                    continue
                start_price = _positive_float(episode["start_price"])
                max_price = max(price, _positive_float(episode["max_price"]) or price)
                min_price = min(price, _positive_float(episode["min_price"]) or price)
                mfe = ((max_price / start_price) - 1) * 100 if start_price else None
                mae = ((min_price / start_price) - 1) * 100 if start_price else None
                updates: dict[str, Any] = {"latest_price": price, "max_price": max_price,
                                           "min_price": min_price, "mfe_pct": mfe, "mae_pct": mae}
                elapsed = now - float(episode["start_epoch"])
                observed_horizons: dict[str, float] = {}
                for column, horizon_seconds in horizons:
                    if episode[column] is None and elapsed >= horizon_seconds and start_price:
                        updates[column] = (price / start_price - 1.0) * 100.0
                        observed_horizons[column] = round(max(0.0, elapsed), 3)
                if observed_horizons:
                    try:
                        persisted_metrics = json.loads(episode["metrics_json"] or "{}")
                    except (TypeError, ValueError):
                        persisted_metrics = {}
                    if isinstance(persisted_metrics, dict):
                        old_elapsed = persisted_metrics.get("forward_return_observed_elapsed_seconds")
                        elapsed_map = dict(old_elapsed) if isinstance(old_elapsed, dict) else {}
                        elapsed_map.update(observed_horizons)
                        persisted_metrics["forward_return_observed_elapsed_seconds"] = elapsed_map
                        updates["metrics_json"] = self._json(persisted_metrics)
                assignments = ",".join(f"{key}=?" for key in updates)
                conn.execute(f"UPDATE episodes SET {assignments} WHERE id=?", (*updates.values(), int(episode["id"])))
                if now - float(episode["last_sample_epoch"] or 0) >= self.sample_seconds:
                    conn.execute("INSERT INTO samples(episode_id,sample_epoch,sample_utc,price,phase,state) VALUES(?,?,?,?,?,?)",
                                 (int(episode["id"]), now, now_utc, price, episode["phase"], episode["state"]))
                    conn.execute("UPDATE episodes SET last_sample_epoch=? WHERE id=?", (now, int(episode["id"])))
                    sample_count += 1


            # Track frozen entry/stop/target levels separately from episode MFE/MAE.
            plan_events = 0
            evaluation_rows = conn.execute(
                "SELECT * FROM episodes WHERE active=1 OR last_seen_epoch >= ?",
                (now - 24 * 3600,),
            ).fetchall()
            for episode in evaluation_rows:
                try:
                    episode_metrics = json.loads(episode["metrics_json"] or "{}")
                except (TypeError, ValueError):
                    episode_metrics = {}
                if not isinstance(episode_metrics, dict):
                    continue
                evaluation = episode_metrics.get("evaluation_plan")
                if not isinstance(evaluation, dict):
                    continue
                if str(evaluation.get("status") or "") in {
                    "HEDEF 1 GÖZLENDİ", "STOP SEVİYESİ GÖZLENDİ",
                    "GİRİŞ GÖZLENMEDİ (24 SAAT)",
                    "KURULUM GEÇERSİZLEŞTİ — GİRİŞ ÖNCESİ",
                    "24 SAATTE HEDEF/STOP GÖZLENMEDİ",
                }:
                    continue
                symbol = str(episode["symbol"])
                current_row = rows_by_symbol.get(symbol)
                if not isinstance(current_row, dict) or current_row.get("data_freshness") != "CANLI AKIŞ GÜNCEL":
                    continue
                price = _positive_float(prices_by_base.get(symbol))
                if price is None:
                    continue
                updated_evaluation, event_type = _advance_technical_plan_evaluation(
                    evaluation, price=price, now_epoch=now, current_candidate=current_row
                )
                episode_metrics["evaluation_plan"] = updated_evaluation
                conn.execute(
                    "UPDATE episodes SET metrics_json=? WHERE id=?",
                    (self._json(episode_metrics), int(episode["id"])),
                )
                if event_type:
                    conn.execute(
                        """INSERT INTO events(episode_id,event_epoch,event_utc,event_type,phase,state,
                               price,reasons_json,metrics_json)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (
                            int(episode["id"]), now, now_utc, event_type,
                            episode["phase"], episode["state"], price,
                            episode["reasons_json"] or "[]",
                            self._json({"evaluation_plan": updated_evaluation}),
                        ),
                    )
                    plan_events += 1

        return {"new_signals": new_count, "transitions": transition_count,
                "closed_signals": closed_count, "samples": sample_count,
                "technical_plan_events": plan_events}


def _positive_float(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (TypeError, ValueError):
        return None



def _build_technical_plan_evaluation(
    candidate: dict[str, Any], *, now_epoch: float, now_utc: str
) -> dict[str, Any] | None:
    """Freeze a valid B/C technical plan so later re-computations cannot rewrite its levels."""
    if candidate.get("data_freshness") != "CANLI AKIŞ GÜNCEL" or candidate.get("phase") not in ("B", "C"):
        return None
    decision = candidate.get("final_decision") or candidate.get("decision_class")
    if decision not in {"GÜÇLÜ FIRSAT", "ERKEN ADAY", "İZLEMEDE"}:
        return None
    plan = candidate.get("risk_plan")
    if not isinstance(plan, dict) or plan.get("technical_targets_available") is not True:
        return None
    def positive_value(key: str) -> float | None:
        raw_value = plan.get(key)
        return None if isinstance(raw_value, bool) else _positive_float(raw_value)
    low, high = positive_value("entry_zone_low"), positive_value("entry_zone_high")
    reference, stop = positive_value("entry_reference"), positive_value("stop_loss")
    if low is None or high is None or reference is None or stop is None or high < low or not low <= reference <= high or stop >= low:
        return None
    targets = plan.get("targets")
    if not isinstance(targets, list):
        return None
    valid_targets = []
    for row in targets:
        if not isinstance(row, dict):
            continue
        raw_price = row.get("price")
        target_price = None if isinstance(raw_price, bool) else _positive_float(raw_price)
        if target_price is not None and target_price > high:
            valid_targets.append((target_price, row))
    if not valid_targets:
        return None
    target_price, target_row = min(valid_targets, key=lambda item: item[0])
    raw_score = candidate.get("opportunity_score", candidate.get("score_0_100"))
    score = (
        float(raw_score) if isinstance(raw_score, (int, float))
        and not isinstance(raw_score, bool) and math.isfinite(float(raw_score))
        and 0.0 <= float(raw_score) <= 100.0 else None
    )
    raw_cost = plan.get("round_trip_cost_pct")
    costs_included = (
        plan.get("costs_included") is True and isinstance(raw_cost, (int, float))
        and not isinstance(raw_cost, bool) and math.isfinite(float(raw_cost))
        and float(raw_cost) >= 0.0
    )
    return {
        "status": "GİRİŞ BEKLENİYOR", "created_epoch": float(now_epoch), "created_utc": now_utc,
        "decision_at_creation": str(decision), "score_at_creation": score,
        "timeframe": str(plan.get("timeframe") or candidate.get("phase_timeframe") or ""),
        "entry_zone_low": low, "entry_zone_high": high, "entry_reference": reference,
        "stop_loss": stop, "target_1_price": target_price,
        "target_1_name": str(target_row.get("name") or "Teknik hedef 1"),
        "costs_included": costs_included,
        "round_trip_cost_pct": float(raw_cost) if costs_included else None,
        "entry_observed": False, "entry_observed_epoch": None, "entry_observed_utc": None,
        "entry_observed_price": None, "outcome_deadline_epoch": None, "last_observed_price": None,
        "price_change_vs_entry_reference_pct": None, "current_gross_return_pct": None,
        "current_estimated_net_return_pct": None,
        "outcome_observed_epoch": None, "outcome_observed_utc": None, "observed_price": None,
        "planned_exit_price": None, "gross_return_pct": None, "estimated_net_return_pct": None,
        "coverage_note": (
            "Örneklenen fiyatlar ve dondurulmuş teknik seviyeler kullanılır; gerçek emir/dolum, "
            "mum içi sıra veya gerçek kayma ölçümü değildir."
        ),
    }


def _update_current_price_metrics(evaluation: dict[str, Any], price: float, reference: float) -> None:
    """Keep a current price comparison even when fees are unknown or entry is not observed."""
    evaluation["last_observed_price"] = price
    evaluation["price_change_vs_entry_reference_pct"] = round(
        (price / reference - 1.0) * 100.0, 4
    )
    entry_price = (
        _positive_float(evaluation.get("entry_observed_price"))
        if evaluation.get("entry_observed") is True else None
    )
    if entry_price is None:
        evaluation["current_gross_return_pct"] = None
        evaluation["current_estimated_net_return_pct"] = None
        return
    gross = (price / entry_price - 1.0) * 100.0
    evaluation["current_gross_return_pct"] = round(gross, 4)
    raw_cost = evaluation.get("round_trip_cost_pct")
    has_cost = (
        evaluation.get("costs_included") is True and isinstance(raw_cost, (int, float))
        and not isinstance(raw_cost, bool) and math.isfinite(float(raw_cost))
        and float(raw_cost) >= 0.0
    )
    evaluation["current_estimated_net_return_pct"] = (
        round(gross - float(raw_cost), 4) if has_cost else None
    )


def _advance_technical_plan_evaluation(
    evaluation: dict[str, Any], *, price: float, now_epoch: float,
    current_candidate: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Advance a frozen plan only from a current price observation."""
    updated = dict(evaluation)
    terminal = {
        "HEDEF 1 GÖZLENDİ", "STOP SEVİYESİ GÖZLENDİ", "GİRİŞ GÖZLENMEDİ (24 SAAT)",
        "KURULUM GEÇERSİZLEŞTİ — GİRİŞ ÖNCESİ", "24 SAATTE HEDEF/STOP GÖZLENMEDİ",
    }
    if str(updated.get("status") or "") in terminal:
        return updated, None
    if not isinstance(price, (int, float)) or isinstance(price, bool) or not math.isfinite(float(price)) or price <= 0:
        return updated, None
    price = float(price)
    low, high = _positive_float(updated.get("entry_zone_low")), _positive_float(updated.get("entry_zone_high"))
    reference, stop, target = (
        _positive_float(updated.get("entry_reference")), _positive_float(updated.get("stop_loss")),
        _positive_float(updated.get("target_1_price")),
    )
    if any(value is None for value in (low, high, reference, stop, target)):
        updated["status"] = "GÖZLEM KAPSAMI YETERSİZ — PLAN VERİSİ BOZUK"
        updated["outcome_observed_epoch"] = float(now_epoch)
        updated["outcome_observed_utc"] = SignalTracker._utc(now_epoch)
        return updated, "PLAN VERİSİ BOZUK"
    _update_current_price_metrics(updated, price, float(reference))
    fresh = isinstance(current_candidate, dict) and current_candidate.get("data_freshness") == "CANLI AKIŞ GÜNCEL"
    if not updated.get("entry_observed"):
        if (
            fresh and current_candidate.get("final_decision") == "FIRSAT GEÇERSİZ"
            and str(current_candidate.get("phase_timeframe") or "") == str(updated.get("timeframe") or "")
        ):
            updated.update({
                "status": "KURULUM GEÇERSİZLEŞTİ — GİRİŞ ÖNCESİ",
                "outcome_observed_epoch": float(now_epoch), "outcome_observed_utc": SignalTracker._utc(now_epoch),
                "observed_price": price, "last_observed_price": price,
            })
            return updated, "PLAN KURULUMU GİRİŞ ÖNCESİ GEÇERSİZLEŞTİ"
        if now_epoch >= float(updated.get("created_epoch", now_epoch)) + 24 * 3600:
            updated.update({
                "status": "GİRİŞ GÖZLENMEDİ (24 SAAT)",
                "outcome_observed_epoch": float(now_epoch), "outcome_observed_utc": SignalTracker._utc(now_epoch),
                "observed_price": price, "last_observed_price": price,
            })
            return updated, "PLAN GİRİŞ SÜRESİ DOLDU"
        updated["last_observed_price"] = price
        if float(low) <= price <= float(high):
            updated.update({
                "status": "GİRİŞ GÖZLENDİ", "entry_observed": True,
                "entry_observed_epoch": float(now_epoch), "entry_observed_utc": SignalTracker._utc(now_epoch),
                "entry_observed_price": price, "outcome_deadline_epoch": float(now_epoch) + 24 * 3600,
            })
            _update_current_price_metrics(updated, price, float(reference))
            return updated, "PLAN GİRİŞ BÖLGESİ GÖZLENDİ"
        return updated, None
    deadline = updated.get("outcome_deadline_epoch")
    if isinstance(deadline, (int, float)) and now_epoch > float(deadline):
        updated.update({
            "status": "24 SAATTE HEDEF/STOP GÖZLENMEDİ",
            "outcome_observed_epoch": float(now_epoch), "outcome_observed_utc": SignalTracker._utc(now_epoch),
            "observed_price": price, "last_observed_price": price,
        })
        return updated, "PLAN 24 SAATLİK GÖZLEM PENCERESİ TAMAMLANDI"
    outcome, planned_exit, event_type = None, None, None
    if price <= float(stop):
        outcome, planned_exit, event_type = "STOP SEVİYESİ GÖZLENDİ", float(stop), "PLAN STOP SEVİYESİ GÖZLENDİ"
    elif price >= float(target):
        outcome, planned_exit, event_type = "HEDEF 1 GÖZLENDİ", float(target), "PLAN HEDEF 1 GÖZLENDİ"
    updated["last_observed_price"] = price
    if outcome is None:
        return updated, None
    gross = (planned_exit / float(reference) - 1.0) * 100.0
    raw_cost = updated.get("round_trip_cost_pct")
    has_cost = (
        updated.get("costs_included") is True and isinstance(raw_cost, (int, float))
        and not isinstance(raw_cost, bool) and math.isfinite(float(raw_cost)) and float(raw_cost) >= 0.0
    )
    updated.update({
        "status": outcome, "outcome_observed_epoch": float(now_epoch),
        "outcome_observed_utc": SignalTracker._utc(now_epoch), "observed_price": price,
        "planned_exit_price": planned_exit, "gross_return_pct": round(gross, 4),
        "estimated_net_return_pct": round(gross - float(raw_cost), 4) if has_cost else None,
    })
    return updated, event_type


def historical_summary() -> dict[str, Any]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        empty_forward_returns = {
            field: {
                "observations": 0, "mean_pct": None,
                "sampling_timing": {
                    "observations": 0, "mean_elapsed_seconds": None,
                    "max_elapsed_seconds": None, "mean_delay_seconds": None,
                    "max_delay_seconds": None,
                },
            }
            for field in ("return_30m_pct", "return_1h_pct", "return_4h_pct", "return_24h_pct")
        }
        return {
            "database": str(DB_PATH), "episode_count": 0,
            "forward_return_observations": empty_forward_returns,
            "technical_plan_tracking": {
                "plan_count": 0, "status_counts": {}, "target_1_observed_count": 0,
                "stop_observed_count": 0, "entry_not_observed_count": 0,
                "entry_invalidated_before_entry_count": 0, "no_target_or_stop_in_24h_count": 0,
                "estimated_net_return_observations": 0, "mean_estimated_net_return_pct": None,
                "current_price_reference_observations": 0, "mean_current_price_vs_entry_reference_pct": None,
                "current_gross_return_observations": 0, "mean_current_gross_return_pct": None,
                "current_estimated_net_return_observations": 0, "mean_current_estimated_net_return_pct": None,
                "note": "Henüz teknik plan gözlemi yok.",
            },
            "note": "Henüz sinyal kaydı yok.",
        }
    with closing(sqlite3.connect(DB_PATH, timeout=10)) as conn:
        conn.row_factory = sqlite3.Row
        count = conn.execute("SELECT COUNT(*) AS n FROM episodes").fetchone()["n"]
        active = conn.execute("SELECT COUNT(*) AS n FROM episodes WHERE active=1").fetchone()["n"]
        sample = conn.execute("SELECT COUNT(*) AS n FROM samples").fetchone()["n"]
        transitions = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE event_type IN "
            "('AŞAMA DEĞİŞTİ','DURUM DEĞİŞTİ','NİHAİ KARAR DEĞİŞTİ')"
        ).fetchone()["n"]
        decision_counts: dict[str, int] = {}
        episodes_with_strong_qualification = 0
        episodes_without_final_decision = 0
        technical_plan_status_counts: dict[str, int] = {}
        technical_plan_count = 0
        estimated_net_returns: list[float] = []
        forward_elapsed_observations: dict[str, list[float]] = {
            field: [] for field in ("return_30m_pct", "return_1h_pct", "return_4h_pct", "return_24h_pct")
        }
        price_reference_changes: list[float] = []
        current_gross_returns: list[float] = []
        current_estimated_net_returns: list[float] = []
        for record in conn.execute("SELECT metrics_json FROM episodes").fetchall():
            try:
                metrics_record = json.loads(record["metrics_json"] or "{}")
            except (TypeError, ValueError):
                metrics_record = {}
            if not isinstance(metrics_record, dict):
                metrics_record = {}
            decision = metrics_record.get("final_decision") or metrics_record.get("decision_class")
            if isinstance(decision, str) and decision.strip():
                decision = decision.strip()
                decision_counts[decision] = decision_counts.get(decision, 0) + 1
            else:
                episodes_without_final_decision += 1
            if metrics_record.get("strong_opportunity_qualified") is True:
                episodes_with_strong_qualification += 1
            elapsed_map = metrics_record.get("forward_return_observed_elapsed_seconds")
            if isinstance(elapsed_map, dict):
                for field, _horizon_seconds in (
                    ("return_30m_pct", 30 * 60), ("return_1h_pct", 60 * 60),
                    ("return_4h_pct", 4 * 3600), ("return_24h_pct", 24 * 3600),
                ):
                    elapsed_value = elapsed_map.get(field)
                    if (
                        isinstance(elapsed_value, (int, float))
                        and not isinstance(elapsed_value, bool)
                        and math.isfinite(float(elapsed_value)) and float(elapsed_value) >= 0.0
                    ):
                        forward_elapsed_observations[field].append(float(elapsed_value))
            evaluation = metrics_record.get("evaluation_plan")
            if isinstance(evaluation, dict):
                technical_plan_count += 1
                outcome_status = str(evaluation.get("status") or "DURUM BİLİNMİYOR")
                technical_plan_status_counts[outcome_status] = technical_plan_status_counts.get(outcome_status, 0) + 1
                net_return = evaluation.get("estimated_net_return_pct")
                if (
                    isinstance(net_return, (int, float)) and not isinstance(net_return, bool)
                    and math.isfinite(float(net_return))
                ):
                    estimated_net_returns.append(float(net_return))
                metric_sets = (
                    ("price_change_vs_entry_reference_pct", price_reference_changes),
                    ("current_gross_return_pct", current_gross_returns),
                    ("current_estimated_net_return_pct", current_estimated_net_returns),
                )
                for metric_name, metric_values in metric_sets:
                    metric_value = evaluation.get(metric_name)
                    if (
                        isinstance(metric_value, (int, float)) and not isinstance(metric_value, bool)
                        and math.isfinite(float(metric_value))
                    ):
                        metric_values.append(float(metric_value))

        outcomes = {}
        horizon_seconds_by_field = {
            "return_30m_pct": 30 * 60, "return_1h_pct": 60 * 60,
            "return_4h_pct": 4 * 3600, "return_24h_pct": 24 * 3600,
        }
        for field, horizon_seconds in horizon_seconds_by_field.items():
            row = conn.execute(f"SELECT COUNT({field}) AS n, AVG({field}) AS avg FROM episodes WHERE {field} IS NOT NULL").fetchone()
            elapsed_values = forward_elapsed_observations[field]
            mean_elapsed = (
                sum(elapsed_values) / len(elapsed_values) if elapsed_values else None
            )
            outcomes[field] = {
                "observations": row["n"], "mean_pct": row["avg"],
                "sampling_timing": {
                    "observations": len(elapsed_values),
                    "mean_elapsed_seconds": round(mean_elapsed, 3) if mean_elapsed is not None else None,
                    "max_elapsed_seconds": round(max(elapsed_values), 3) if elapsed_values else None,
                    "mean_delay_seconds": round(max(0.0, mean_elapsed - horizon_seconds), 3)
                    if mean_elapsed is not None else None,
                    "max_delay_seconds": round(max(0.0, max(elapsed_values) - horizon_seconds), 3)
                    if elapsed_values else None,
                },
            }
    return {
        "database": str(DB_PATH),
        "episode_count": count,
        "active_episodes": active,
        "sample_count": sample,
        "transition_count": transitions,
        "final_decision_counts": decision_counts,
        "strong_opportunity_episode_count": episodes_with_strong_qualification,
        "episodes_without_final_decision": episodes_without_final_decision,
        "forward_return_observations": outcomes,
        "technical_plan_tracking": {
            "plan_count": technical_plan_count,
            "status_counts": technical_plan_status_counts,
            "target_1_observed_count": technical_plan_status_counts.get("HEDEF 1 GÖZLENDİ", 0),
            "stop_observed_count": technical_plan_status_counts.get("STOP SEVİYESİ GÖZLENDİ", 0),
            "entry_not_observed_count": technical_plan_status_counts.get("GİRİŞ GÖZLENMEDİ (24 SAAT)", 0),
            "entry_invalidated_before_entry_count": technical_plan_status_counts.get("KURULUM GEÇERSİZLEŞTİ — GİRİŞ ÖNCESİ", 0),
            "no_target_or_stop_in_24h_count": technical_plan_status_counts.get("24 SAATTE HEDEF/STOP GÖZLENMEDİ", 0),
            "estimated_net_return_observations": len(estimated_net_returns),
            "mean_estimated_net_return_pct": (
                round(sum(estimated_net_returns) / len(estimated_net_returns), 4) if estimated_net_returns else None
            ),
            "current_price_reference_observations": len(price_reference_changes),
            "mean_current_price_vs_entry_reference_pct": (
                round(sum(price_reference_changes) / len(price_reference_changes), 4)
                if price_reference_changes else None
            ),
            "current_gross_return_observations": len(current_gross_returns),
            "mean_current_gross_return_pct": (
                round(sum(current_gross_returns) / len(current_gross_returns), 4)
                if current_gross_returns else None
            ),
            "current_estimated_net_return_observations": len(current_estimated_net_returns),
            "mean_current_estimated_net_return_pct": (
                round(sum(current_estimated_net_returns) / len(current_estimated_net_returns), 4)
                if current_estimated_net_returns else None
            ),
            "note": (
                "Sonuçlar sabitlenmiş teknik seviyeler ve örneklenen fiyatlardan çıkarılır. "
                "Gerçek emir, dolum, mum içi fiyat sırası veya gerçek kayma değildir."
            ),
        },
        "note": (
            "Karar sayıları dönem başına son kaydedilen sınıfı gösterir; nihai karar geçişleri olay kaydında korunur. "
            "İleri getiriler hedef süreden sonraki ilk uygun fiyat örneğidir; gerçek geçen süre ve gecikme "
            "sampling_timing alanlarında verilir. Bunlar kapanış mumundan hesaplanan tarihsel geri test veya "
            "gerçek emir sonucu değildir."
        ),
    }
