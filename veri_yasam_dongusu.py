"""Güvenli yerel veri bakımı: eski aday CSV'lerini doğrulanmış aylık ZIP'e taşıma.

Bu modül piyasa verisi, sinyal veritabanı veya mum arşivini değiştirmez.
Kaynak aday CSV'leri ancak arşivin üyeleri ve SHA-256 manifesti doğrulandıktan
sonra silinir. Başarısızlıklar uyarı olarak döndürülür; canlı taramayı durdurmaz.
"""
from __future__ import annotations

import calendar
import csv
import hashlib
import io
import json
import os
import re
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_CANDIDATE_RE = re.compile(r"^binance_candidates_history_(\d{8})_v(\d+)\.csv$")
_TEMP_RE = re.compile(r"^\..+\.(\d+)\.(\d+)\.tmp$")
_MANIFEST_NAME = "manifest.json"
_ARCHIVE_DIRNAME = "candidate_archives"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse_candidate_name(path: Path) -> tuple[date, int] | None:
    match = _CANDIDATE_RE.fullmatch(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date(), int(match.group(2))
    except (TypeError, ValueError):
        return None


def _csv_row_count(data: bytes) -> int:
    # Count data rows rather than physical lines so quoted multiline cells are safe.
    text = data.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        next(reader, None)  # header
        return sum(1 for _ in reader)
    except csv.Error as exc:
        raise ValueError(f"CSV yapısı okunamadı: {exc}") from exc


def _pid_is_running(pid: int) -> bool:
    """Be conservative: uncertain process status means do not delete the temp file."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
    except OSError as exc:
        if getattr(exc, "winerror", None) in (87, 1168):
            return False
        # Windows and sandboxed environments can report uncertain access errors.
        return True


def _clean_stale_temp_files(
    directories: list[Path], *, stale_hours: float, now_epoch: float,
) -> tuple[int, list[str]]:
    deleted = 0
    warnings: list[str] = []
    min_age = max(1.0, float(stale_hours)) * 3600.0
    for directory in directories:
        try:
            entries = list(directory.iterdir()) if directory.is_dir() else []
        except OSError as exc:
            warnings.append(f"Geçici dosya alanı okunamadı ({directory}): {type(exc).__name__}: {exc}")
            continue
        for path in entries:
            match = _TEMP_RE.fullmatch(path.name)
            if not match or not path.is_file():
                continue
            try:
                age = now_epoch - path.stat().st_mtime
                if age < min_age:
                    continue
                pid = int(match.group(1))
                if _pid_is_running(pid):
                    continue
                # Only old, PID-tagged application temporary files are eligible.
                path.unlink()
                deleted += 1
            except FileNotFoundError:
                continue
            except (OSError, ValueError) as exc:
                warnings.append(f"Geçici dosya silinemedi ({path.name}): {type(exc).__name__}: {exc}")
    return deleted, warnings


def _month_end(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def _archive_path(archive_dir: Path, year: int, month: int) -> Path:
    return archive_dir / f"binance_candidates_history_archive_{year:04d}{month:02d}.zip"


def _verify_archive(path: Path) -> dict[str, dict[str, Any]]:
    """Verify ZIP CRCs, manifest schema, each CSV's exact bytes and SHA-256."""
    with zipfile.ZipFile(path, "r") as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError(f"ZIP CRC doğrulaması başarısız: {bad_member}")
        names = set(archive.namelist())
        if _MANIFEST_NAME not in names:
            raise ValueError("SHA-256 manifesti bulunamadı.")
        manifest = json.loads(archive.read(_MANIFEST_NAME).decode("utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ValueError("Manifest şeması desteklenmiyor.")
        files = manifest.get("files")
        if not isinstance(files, list) or not files:
            raise ValueError("Manifest içinde kaynak listesi bulunamadı.")
        verified: dict[str, dict[str, Any]] = {}
        expected_names = {_MANIFEST_NAME}
        for item in files:
            if not isinstance(item, dict):
                raise ValueError("Manifest kaydı geçersiz.")
            name = str(item.get("name") or "")
            if not name or Path(name).name != name or not _CANDIDATE_RE.fullmatch(name):
                raise ValueError("Manifest içinde güvenli olmayan dosya adı var.")
            member = f"csv/{name}"
            expected_names.add(member)
            if member not in names:
                raise ValueError(f"Arşiv üyesi eksik: {member}")
            payload = archive.read(member)
            digest = _sha256(payload)
            if digest != item.get("sha256") or len(payload) != item.get("size_bytes"):
                raise ValueError(f"SHA-256/boyut uyuşmazlığı: {name}")
            if _csv_row_count(payload) != item.get("data_rows"):
                raise ValueError(f"CSV satır sayısı uyuşmazlığı: {name}")
            verified[name] = {**item, "sha256": digest}
        if names != expected_names:
            raise ValueError("Arşivde manifest dışında veya manifestte olmayan üyeler var.")
        return verified


def _create_month_archive(
    archive_path: Path, source_files: list[Path], *, created_at_utc: str,
) -> int:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    prepared: list[tuple[Path, bytes, dict[str, Any]]] = []
    for source in sorted(source_files, key=lambda p: p.name.casefold()):
        raw = source.read_bytes()
        parsed = _parse_candidate_name(source)
        if parsed is None:
            continue
        prepared.append((source, raw, {
            "name": source.name,
            "sha256": _sha256(raw),
            "size_bytes": len(raw),
            "data_rows": _csv_row_count(raw),
            "source_date_utc": parsed[0].isoformat(),
            "schema_version": parsed[1],
        }))
    if not prepared:
        return 0

    manifest = {
        "schema_version": 1,
        "archive_type": "monthly_candidate_history_csv",
        "created_at_utc": created_at_utc,
        "files": [metadata for _source, _raw, metadata in prepared],
        "note": "CSV verileri ham baytlarıyla saklanır; kaynaklar SHA-256 ve satır sayısı doğrulanmadan silinmez.",
    }
    temporary = archive_path.with_name(f".{archive_path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for _source, raw, metadata in prepared:
                archive.writestr(f"csv/{metadata['name']}", raw)
            archive.writestr(
                _MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"),
            )
        _verify_archive(temporary)
        # Never overwrite an existing month's archive; caller checks that first.
        if archive_path.exists():
            raise FileExistsError(f"Aylık arşiv zaten mevcut: {archive_path.name}")
        os.replace(temporary, archive_path)
        _verify_archive(archive_path)
        return sum(int(metadata["data_rows"]) for _source, _raw, metadata in prepared)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def run_storage_maintenance(
    data_dir: str | Path,
    log_dir: str | Path,
    run_dir: str | Path,
    report_dir: str | Path,
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Archive complete, aged-out candidate-history months and safely clean app temp files.

    report_dir is accepted to keep the call contract explicit; reports are not cleaned.
    SQLite/WAL/SHM files, local lists, caches, logs, reports and active run markers are never
    targeted. Any failure is returned as a warning instead of interrupting the live scan.
    """
    _ = Path(report_dir)  # intentionally not scanned or modified
    cfg = settings if isinstance(settings, dict) else {}
    result: dict[str, Any] = {
        "candidate_archives_created": 0,
        "candidate_source_files_deleted": 0,
        "candidate_rows_archived": 0,
        "stale_temp_files_deleted": 0,
        "warnings": [],
    }
    if cfg.get("storage_maintenance_enabled", True) is False:
        result["warnings"].append("Depolama bakımı ayarlar.json içinde kapalı.")
        return result

    now_epoch = time.time()
    now_utc = datetime.fromtimestamp(now_epoch, timezone.utc).isoformat(timespec="seconds")
    hot_days_raw = cfg.get("candidate_history_hot_days", 90)
    try:
        if isinstance(hot_days_raw, bool):
            raise ValueError
        hot_days = int(hot_days_raw)
        if not 1 <= hot_days <= 3650:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        hot_days = 90
        result["warnings"].append("candidate_history_hot_days geçersiz; 90 gün varsayılanı kullanıldı.")
    stale_hours_raw = cfg.get("stale_temp_file_hours", 24)
    try:
        stale_hours = float(stale_hours_raw)
        if isinstance(stale_hours_raw, bool) or not (1 <= stale_hours <= 24 * 365):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        stale_hours = 24.0
        result["warnings"].append("stale_temp_file_hours geçersiz; 24 saat varsayılanı kullanıldı.")

    data_path = Path(data_dir)
    log_path = Path(log_dir)
    run_path = Path(run_dir)
    for folder in (data_path, log_path, run_path):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            result["warnings"].append(f"Bakım alanı oluşturulamadı ({folder}): {type(exc).__name__}: {exc}")

    deleted_temp, temp_warnings = _clean_stale_temp_files(
        [data_path, log_path, run_path], stale_hours=stale_hours, now_epoch=now_epoch,
    )
    result["stale_temp_files_deleted"] = deleted_temp
    result["warnings"].extend(temp_warnings)

    cutoff_date = datetime.fromtimestamp(now_epoch, timezone.utc).date().toordinal() - hot_days
    cutoff_day = date.fromordinal(cutoff_date)
    groups: dict[tuple[int, int], list[Path]] = {}
    try:
        history_files = list(data_path.glob("binance_candidates_history_*_v*.csv"))
    except OSError as exc:
        result["warnings"].append(f"Aday geçmişi dizini okunamadı: {type(exc).__name__}: {exc}")
        return result

    for source in history_files:
        parsed = _parse_candidate_name(source)
        if parsed is None:
            continue
        source_day, _version = parsed
        # Whole months are archived only after the last day of that month has aged out.
        if _month_end(source_day) >= cutoff_day:
            continue
        groups.setdefault((source_day.year, source_day.month), []).append(source)

    archive_dir = data_path / _ARCHIVE_DIRNAME
    for (year, month), files in sorted(groups.items()):
        target = _archive_path(archive_dir, year, month)
        try:
            if target.exists():
                verified = _verify_archive(target)
                expected_source_names = {p.name for p in files}
                verified_names = set(verified)
                if not expected_source_names.issubset(verified_names):
                    result["warnings"].append(
                        f"Mevcut aylık arşiv yeni kaynakla uyuşmuyor; kaynaklar korundu: {target.name}"
                    )
                    continue
            else:
                _create_month_archive(target, files, created_at_utc=now_utc)
                result["candidate_archives_created"] += 1
                verified = _verify_archive(target)

            # Re-read every source immediately before deletion to avoid removing a file that
            # changed after the archived bytes were collected. On any mismatch, keep it.
            for source in files:
                metadata = verified.get(source.name)
                if metadata is None:
                    continue
                current = source.read_bytes()
                if _sha256(current) != metadata.get("sha256") or len(current) != metadata.get("size_bytes"):
                    result["warnings"].append(f"Kaynak arşivden sonra değişti; silinmedi: {source.name}")
                    continue
                try:
                    source.unlink()
                    result["candidate_source_files_deleted"] += 1
                    result["candidate_rows_archived"] += int(metadata.get("data_rows", 0))
                except OSError as exc:
                    result["warnings"].append(f"Arşivlenen kaynak silinemedi ({source.name}): {type(exc).__name__}: {exc}")
        except Exception as exc:
            result["warnings"].append(
                f"Aday CSV aylık arşivi doğrulanamadı ({target.name}): {type(exc).__name__}: {str(exc)[:250]}. Kaynaklar korunmuştur."
            )

    return result
