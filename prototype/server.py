#!/usr/bin/env python3
"""Local bridge for the fleetctl prototype.

Serves the static prototype and exposes two read-only endpoints backed by the
fleetctl engine:

    GET /api/devices              connected devices (deduped by UDID)
    GET /api/inspect?udid=...     activation lock probe against Apple

No write operations, no bypass. If no device is connected the endpoints return
an empty list and the page keeps its mock data.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "4174"))
MAX_BODY = 4 * 1024 * 1024

# Map the engine's verdict onto the prototype's four status colours.
STATUS = {
    "clean": "clean",
    "icloud_lock": "lock",
    "mdm_lock": "mdm",
    "pending_erase": "unknown",
    "undetermined": "unknown",
}


async def collect_devices() -> list[dict]:
    from pymobiledevice3.lockdown import create_using_usbmux

    from fleetctl.usb_manager import USBDeviceManager

    entries = await USBDeviceManager().enumerate()
    seen: set[str] = set()
    devices: list[dict] = []

    for entry in entries:
        udid = entry.get("udid")
        if not udid or udid in seen:
            continue
        seen.add(udid)

        info: dict = {}
        try:
            lockdown = await create_using_usbmux(serial=udid)
            info = lockdown.all_values or {}
        except Exception:
            pass

        devices.append(
            {
                "udid": udid,
                "name": info.get("DeviceName") or entry.get("device_name") or "iPhone",
                "product_type": info.get("ProductType") or entry.get("product_type") or "—",
                "ios": info.get("ProductVersion") or entry.get("product_version") or "—",
                "serial": info.get("SerialNumber") or "—",
                "imei": info.get("InternationalMobileEquipmentIdentity") or "—",
                "region": info.get("RegionInfo") or "—",
                "activation_state": info.get("ActivationState") or "—",
            }
        )

    return devices


async def inspect(udid: str) -> dict:
    from fleetctl.activation_lock import probe_activation_lock

    probe = await probe_activation_lock(udid)
    payload = probe.to_dict()
    payload["status"] = STATUS.get(payload.get("verdict"), "unknown")
    return payload


# ---------------------------------------------------------------- #
# Local store: devices registered by hand survive restarts        #
# ---------------------------------------------------------------- #

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


def store_path() -> str:
    return os.path.join(data_dir(), "devices.json")


def load_store() -> list[dict]:
    try:
        with open(store_path(), encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return []
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    rows = payload.get("devices")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def save_store(devices: list[dict]) -> None:
    path = store_path()
    tmp = f"{path}.tmp"
    payload = {
        "version": 1,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "devices": devices,
    }
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)

        if parsed.path == "/api/health":
            self._send_json({"ok": True})
            return

        if parsed.path == "/api/devices":
            try:
                self._send_json({"ok": True, "devices": asyncio.run(collect_devices())})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        if parsed.path == "/api/inspect":
            udid = (parse_qs(parsed.query).get("udid") or [""])[0]
            if not udid:
                self._send_json({"ok": False, "error": "udid required"}, 400)
                return
            try:
                self._send_json({"ok": True, "probe": asyncio.run(inspect(udid))})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        if parsed.path == "/api/store":
            try:
                self._send_json({"ok": True, "devices": load_store(), "path": store_path()})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        super().do_GET()

    def do_PUT(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        if parsed.path != "/api/store":
            self._send_json({"ok": False, "error": "not found"}, 404)
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._send_json({"ok": False, "error": "invalid body size"}, 400)
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"ok": False, "error": "invalid json"}, 400)
            return

        devices = payload.get("devices") if isinstance(payload, dict) else None
        if not isinstance(devices, list):
            self._send_json({"ok": False, "error": "devices must be a list"}, 400)
            return

        rows = [row for row in devices if isinstance(row, dict)]
        try:
            save_store(rows)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        self._send_json({"ok": True, "count": len(rows), "path": store_path()})

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib naming
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _cors_headers(self) -> None:
        # The Tauri shell serves the UI from tauri://localhost, so the bridge
        # must allow cross-origin reads.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        # Keep the console readable; one line per API call is enough.
        if self.path.startswith("/api/"):
            print(f"[api] {self.command} {self.path}")


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"fleetctl prototype: http://localhost:{PORT}")
    print("  GET /api/devices")
    print("  GET /api/inspect?udid=...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
