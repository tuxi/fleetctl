"""SQLite storage for devices and archived reports.

Replaces the earlier single JSON file: devices keep their full dictionary in a
`data` column while the fields we filter on (serial, status, stage) are real
columns, so the table stays queryable without giving up unknown fields.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

LEGACY_FILE = "devices.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    serial TEXT,
    status TEXT,
    stage TEXT,
    updated_at TEXT,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status);
CREATE INDEX IF NOT EXISTS idx_devices_stage ON devices(stage);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT,
    serial TEXT,
    report_no TEXT,
    generated_at TEXT,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_serial ON reports(serial);

CREATE TABLE IF NOT EXISTS prices (
    product_type TEXT NOT NULL,
    capacity TEXT NOT NULL,
    grade_a INTEGER,
    grade_b INTEGER,
    grade_c INTEGER,
    updated_at TEXT,
    PRIMARY KEY (product_type, capacity)
);
"""


def data_dir() -> str:
    override = os.environ.get("FLEETCTL_DATA_DIR")
    if override:
        path = override
    elif sys.platform == "darwin":
        path = os.path.expanduser("~/Library/Application Support/fleetctl")
    else:
        path = os.path.expanduser("~/.fleetctl")
    os.makedirs(path, exist_ok=True)
    return path


def db_path() -> str:
    return os.path.join(data_dir(), "fleetctl.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init() -> None:
    with session() as conn:
        conn.executescript(SCHEMA)
    _migrate_legacy()


def _migrate_legacy() -> None:
    legacy = os.path.join(data_dir(), LEGACY_FILE)
    if not os.path.exists(legacy):
        return
    with session() as conn:
        existing = conn.execute("SELECT COUNT(*) AS n FROM devices").fetchone()["n"]
    if existing:
        return

    try:
        with open(legacy, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return

    rows = payload if isinstance(payload, list) else payload.get("devices", [])
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    if rows:
        replace_devices(rows)


def list_devices() -> list[dict]:
    with session() as conn:
        rows = conn.execute("SELECT data FROM devices ORDER BY updated_at ASC").fetchall()
    devices = []
    for row in rows:
        try:
            devices.append(json.loads(row["data"]))
        except ValueError:
            continue
    return devices


def replace_devices(devices: list[dict]) -> int:
    now = _now()
    rows = [
        (
            str(item.get("id") or ""),
            str(item.get("serial") or ""),
            str(item.get("status") or ""),
            str(item.get("stage") or ""),
            now,
            json.dumps(item, ensure_ascii=False),
        )
        for item in devices
        if item.get("id")
    ]
    with session() as conn:
        conn.execute("DELETE FROM devices")
        conn.executemany(
            "INSERT OR REPLACE INTO devices (id, serial, status, stage, updated_at, data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def add_report(device: dict, report: dict) -> int:
    payload = {"device": device, "report": report}
    with session() as conn:
        cursor = conn.execute(
            "INSERT INTO reports (device_id, serial, report_no, generated_at, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                str(device.get("id") or ""),
                str(device.get("serial") or ""),
                str(report.get("report_no") or ""),
                str(report.get("generated_at") or _now()),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        return int(cursor.lastrowid or 0)


def list_reports(limit: int = 50) -> list[dict]:
    with session() as conn:
        rows = conn.execute(
            "SELECT id, device_id, serial, report_no, generated_at, data FROM reports "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    reports = []
    for row in rows:
        try:
            payload = json.loads(row["data"])
        except ValueError:
            payload = {}
        device = payload.get("device") or {}
        report = payload.get("report") or {}
        reports.append(
            {
                "id": row["id"],
                "device_id": row["device_id"],
                "serial": row["serial"],
                "report_no": row["report_no"],
                "generated_at": row["generated_at"],
                "name": device.get("name") or "",
                "status": (report.get("verdict") or {}).get("status") or device.get("status") or "",
            }
        )
    return reports


def get_report(report_id: int) -> Optional[dict]:
    with session() as conn:
        row = conn.execute("SELECT data FROM reports WHERE id = ?", (report_id,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["data"])
    except ValueError:
        return None


def list_prices() -> list[dict]:
    with session() as conn:
        rows = conn.execute(
            "SELECT product_type, capacity, grade_a, grade_b, grade_c, updated_at "
            "FROM prices ORDER BY product_type, capacity"
        ).fetchall()
    return [dict(row) for row in rows]


def replace_prices(rows: list[dict]) -> int:
    now = _now()
    values = [
        (
            str(item.get("product_type") or ""),
            str(item.get("capacity") or ""),
            item.get("grade_a"),
            item.get("grade_b"),
            item.get("grade_c"),
            now,
        )
        for item in rows
        if item.get("product_type") and item.get("capacity")
    ]
    with session() as conn:
        conn.execute("DELETE FROM prices")
        conn.executemany(
            "INSERT OR REPLACE INTO prices "
            "(product_type, capacity, grade_a, grade_b, grade_c, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            values,
        )
    return len(values)
