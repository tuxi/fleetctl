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
import base64
import json
import os
import re
import uuid
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import store

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "4174"))
MAX_BODY = 24 * 1024 * 1024
MAX_ATTACHMENT = 12 * 1024 * 1024

# Map the engine's verdict onto the prototype's four status colours.
STATUS = {
    "clean": "clean",
    "icloud_lock": "lock",
    "mdm_lock": "mdm",
    "pending_erase": "unknown",
    "undetermined": "unknown",
}

MODELS_PATH = os.path.join(ROOT, "models.json")


def load_models() -> dict:
    try:
        with open(MODELS_PATH, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    models = payload.get("models")
    return models if isinstance(models, dict) else {}


MODELS = load_models()


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

        # Local Find My flags. These are an advisory for an activated device,
        # not an authoritative lock verdict: Apple only answers that at
        # activation time.
        nvram = info.get("NonVolatileRAM") or {}

        def nvram_text(key: str) -> str:
            value = nvram.get(key)
            if isinstance(value, (bytes, bytearray)):
                return value.decode("utf-8", "replace")
            return value if isinstance(value, str) else ""

        findmy_locked = nvram_text("fm-activation-locked").strip().upper() == "YES"
        findmy_account = nvram_text("fm-account-masked").strip() or None

        # Erase history: the last "Erase All Content and Settings" (EACS) or
        # DFU restore, with its timestamp and reason.
        obliteration = nvram_text("obliteration").strip()
        erase_at = None
        erase_method = None
        erase_reason = None
        if obliteration:
            stamp = re.search(r"@(\d{9,})", obliteration)
            if stamp:
                erase_at = datetime.fromtimestamp(
                    int(stamp.group(1)), timezone.utc
                ).strftime("%Y-%m-%d")
            upper = obliteration.upper()
            erase_method = "EACS" if upper.startswith("EACS") else ("DFU" if "DFU" in upper else None)
            reason = re.search(r"Reason:\s*([^\[\],]+)", obliteration)
            if reason:
                erase_reason = reason.group(1).strip()

        # Kernel panic history: reliability signal.
        panic_raw = nvram_text("panicmedic-timestamps").strip()
        panic_records = 0
        if panic_raw:
            body = panic_raw.split(":", 1)[1] if ":" in panic_raw else panic_raw
            panic_records = len([part for part in body.split(",") if part.strip()])

        devices.append(
            {
                "udid": udid,
                "name": info.get("DeviceName") or entry.get("device_name") or "iPhone",
                "product_type": info.get("ProductType") or entry.get("product_type") or "—",
                "marketing_name": (MODELS.get(info.get("ProductType") or "") or {}).get("name"),
                "model_year": (MODELS.get(info.get("ProductType") or "") or {}).get("year"),
                "chip": (MODELS.get(info.get("ProductType") or "") or {}).get("chip"),
                "ios": info.get("ProductVersion") or entry.get("product_version") or "—",
                "serial": info.get("SerialNumber") or "—",
                "imei": info.get("InternationalMobileEquipmentIdentity") or "—",
                "region": info.get("RegionInfo") or "—",
                "activation_state": info.get("ActivationState") or "—",
                "findmy_locked": findmy_locked,
                "findmy_account": findmy_account,
                "erase_at": erase_at,
                "erase_method": erase_method,
                "erase_reason": erase_reason,
                "panic_records": panic_records,
                "boot_args": nvram_text("boot-args").strip(),
                # PasswordProtected tracks whether the device is locked right
                # now, not whether a passcode was ever set.
                "screen_locked": info.get("PasswordProtected") is True,
                "build_version": info.get("BuildVersion") or "—",
                "baseband_status": info.get("BasebandStatus") or "—",
                "baseband_version": info.get("BasebandVersion") or "—",
                "sim_status": info.get("SIMStatus") or "—",
                "sim_tray": info.get("SIMTrayStatus") or "—",
                "carrier_mcc": info.get("MobileSubscriberCountryCode"),
                "carrier_mnc": info.get("MobileSubscriberNetworkCode"),
                "fusing_status": info.get("FusingStatus"),
                "device_color": info.get("DeviceColor"),
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

def export_dir() -> str:
    downloads = os.path.expanduser("~/Downloads")
    if os.path.isdir(downloads):
        return downloads
    return os.path.expanduser("~/Documents")


def attachments_dir() -> str:
    path = os.path.join(store.data_dir(), "attachments")
    os.makedirs(path, exist_ok=True)
    return path


def write_export(filename: str, content: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:120] or "report.json"
    path = os.path.join(export_dir(), safe)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return path


async def hardware(udid: str) -> dict:
    """Battery readings from the diagnostics service.

    Works on unactivated devices too, which is what a recycler usually has in
    hand. Capacity fields live in the nested BatteryData dictionary on modern
    iOS; the top-level keys are mostly empty there.
    """
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.diagnostics import DiagnosticsService

    lockdown = await create_using_usbmux(serial=udid)
    service = DiagnosticsService(lockdown)
    battery = await service.get_battery()

    data = battery.get("BatteryData") or {}
    design = data.get("DesignCapacity")
    full = data.get("FullChargeCapacity") or data.get("AppleRawMaxCapacity")
    health = round(full / design * 100) if design and full else None

    vendor = battery.get("ManufacturerData")
    if isinstance(vendor, (bytes, bytearray)):
        vendor = vendor.split(b"\x00", 1)[0].decode("utf-8", "replace").strip() or None
    else:
        vendor = None

    return {
        "cycle_count": battery.get("CycleCount"),
        "design_capacity": design,
        "full_capacity": full,
        "health_percent": health,
        "voltage_mv": battery.get("Voltage"),
        "charge_percent": battery.get("CurrentCapacity"),
        "charging": battery.get("IsCharging") is True,
        "external_connected": battery.get("ExternalConnected") is True,
        "battery_serial": battery.get("Serial"),
        "battery_vendor": vendor,
    }


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

        if parsed.path == "/api/models":
            models = [{"product_type": key, **value} for key, value in MODELS.items()]
            models.sort(key=lambda item: (item.get("year") or 0, item.get("name") or ""), reverse=True)
            self._send_json({"ok": True, "models": models})
            return

        if parsed.path == "/api/hardware":
            udid = (parse_qs(parsed.query).get("udid") or [""])[0]
            if not udid:
                self._send_json({"ok": False, "error": "udid required"}, 400)
                return
            try:
                self._send_json({"ok": True, "hardware": asyncio.run(hardware(udid))})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        if parsed.path == "/api/prices":
            try:
                self._send_json({"ok": True, "prices": store.list_prices()})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        if parsed.path == "/api/store":
            try:
                self._send_json({"ok": True, "devices": store.list_devices(), "path": store.db_path()})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        if parsed.path == "/api/receipts":
            try:
                self._send_json({"ok": True, "receipts": store.list_receipts()})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        if parsed.path.startswith("/api/receipts/"):
            try:
                receipt_id = int(parsed.path.rsplit("/", 1)[1])
            except ValueError:
                self._send_json({"ok": False, "error": "invalid id"}, 400)
                return
            try:
                entry = store.get_receipt(receipt_id)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
                return
            if entry is None:
                self._send_json({"ok": False, "error": "not found"}, 404)
            else:
                self._send_json(
                    {"ok": True, "archived": entry["payload"], "sha256": entry["sha256"]}
                )
            return

        if parsed.path == "/api/reports":
            try:
                self._send_json({"ok": True, "reports": store.list_reports()})
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        if parsed.path.startswith("/api/reports/"):
            try:
                report_id = int(parsed.path.rsplit("/", 1)[1])
            except ValueError:
                self._send_json({"ok": False, "error": "invalid id"}, 400)
                return
            try:
                entry = store.get_report(report_id)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
                return
            if entry is None:
                self._send_json({"ok": False, "error": "not found"}, 404)
            else:
                self._send_json(
                    {"ok": True, "archived": entry["payload"], "sha256": entry["sha256"]}
                )
            return

        if parsed.path == "/api/attachments":
            device_id = (parse_qs(parsed.query).get("device_id") or [""])[0]
            try:
                items = store.list_attachments(device_id)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
                return
            for item in items:
                item["url"] = f"/api/attachments/file/{item['id']}"
            self._send_json({"ok": True, "attachments": items})
            return

        if parsed.path.startswith("/api/attachments/file/"):
            try:
                attachment_id = int(parsed.path.rsplit("/", 1)[1])
            except ValueError:
                self._send_json({"ok": False, "error": "invalid id"}, 400)
                return
            row = store.get_attachment(attachment_id)
            if row is None:
                self._send_json({"ok": False, "error": "not found"}, 404)
                return
            try:
                with open(row["path"], "rb") as handle:
                    body = handle.read()
            except OSError:
                self._send_json({"ok": False, "error": "file missing"}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", row.get("mime") or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=300")
            self.end_headers()
            self.wfile.write(body)
            return

        super().do_GET()

    def do_PUT(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        if parsed.path not in ("/api/store", "/api/prices"):
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

        if parsed.path == "/api/prices":
            prices = payload.get("prices") if isinstance(payload, dict) else None
            if not isinstance(prices, list):
                self._send_json({"ok": False, "error": "prices must be a list"}, 400)
                return
            rows = [row for row in prices if isinstance(row, dict)]
            try:
                saved = store.replace_prices(rows)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
                return
            self._send_json({"ok": True, "count": saved})
            return

        devices = payload.get("devices") if isinstance(payload, dict) else None
        if not isinstance(devices, list):
            self._send_json({"ok": False, "error": "devices must be a list"}, 400)
            return

        rows = [row for row in devices if isinstance(row, dict)]
        try:
            saved = store.replace_devices(rows)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        self._send_json({"ok": True, "count": saved, "path": store.db_path()})

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        if parsed.path not in ("/api/export", "/api/reports", "/api/receipts", "/api/attachments"):
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

        if parsed.path == "/api/reports":
            device = payload.get("device") if isinstance(payload, dict) else None
            report = payload.get("report") if isinstance(payload, dict) else None
            if not isinstance(device, dict) or not isinstance(report, dict):
                self._send_json({"ok": False, "error": "device and report required"}, 400)
                return
            try:
                report_id, digest = store.add_report(device, report)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
                return
            self._send_json({"ok": True, "id": report_id, "sha256": digest})
            return

        if parsed.path == "/api/receipts":
            device = payload.get("device") if isinstance(payload, dict) else None
            receipt = payload.get("receipt") if isinstance(payload, dict) else None
            if not isinstance(device, dict) or not isinstance(receipt, dict):
                self._send_json({"ok": False, "error": "device and receipt required"}, 400)
                return
            try:
                receipt_id, digest = store.add_receipt(device, receipt)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
                return
            self._send_json({"ok": True, "id": receipt_id, "sha256": digest})
            return

        if parsed.path == "/api/attachments":
            device_id = str(payload.get("device_id") or "")
            serial = str(payload.get("serial") or "")
            filename = str(payload.get("filename") or "photo.jpg")
            mime = str(payload.get("mime") or "application/octet-stream")
            encoded = payload.get("data")
            if not device_id or not isinstance(encoded, str) or not encoded:
                self._send_json({"ok": False, "error": "device_id and data required"}, 400)
                return
            try:
                raw = base64.b64decode(encoded, validate=True)
            except Exception:
                self._send_json({"ok": False, "error": "invalid base64 data"}, 400)
                return
            if len(raw) > MAX_ATTACHMENT:
                self._send_json({"ok": False, "error": "attachment too large"}, 400)
                return

            safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:80] or "photo"
            path = os.path.join(attachments_dir(), f"{uuid.uuid4().hex}-{safe}")
            try:
                with open(path, "wb") as handle:
                    handle.write(raw)
                attachment_id = store.add_attachment(
                    device_id, serial, filename, mime, len(raw), path
                )
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 500)
                return

            self._send_json(
                {
                    "ok": True,
                    "id": attachment_id,
                    "url": f"/api/attachments/file/{attachment_id}",
                }
            )
            return

        content = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(content, str):
            self._send_json({"ok": False, "error": "content must be a string"}, 400)
            return

        try:
            path = write_export(payload.get("filename") or "report.json", content)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 500)
            return

        self._send_json({"ok": True, "path": path})

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/attachments/"):
            self._send_json({"ok": False, "error": "not found"}, 404)
            return
        try:
            attachment_id = int(parsed.path.rsplit("/", 1)[1])
        except ValueError:
            self._send_json({"ok": False, "error": "invalid id"}, 400)
            return
        try:
            row = store.delete_attachment(attachment_id)
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, 500)
            return
        if row is None:
            self._send_json({"ok": False, "error": "not found"}, 404)
            return
        try:
            os.remove(row["path"])
        except OSError:
            pass
        self._send_json({"ok": True})

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib naming
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _cors_headers(self) -> None:
        # The Tauri shell serves the UI from tauri://localhost, so the bridge
        # must allow cross-origin reads.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
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
    store.init()
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
