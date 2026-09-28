"""
Compliant three-step manual gateway pre-check (三步手工门验证).

This module performs **read-only** checks that help an operator decide whether a
device is ready for the offline Setup Assistant gateway described in spec/11
§6.1. It does **not** modify the device and does **not** attempt any enrollment
or Remote Management bypass.

Steps:
    1. Erase availability  -- can "Erase All Content and Settings" be used?
    2. Offline Setup Assistant -- is the device at/near the Wi-Fi-before state?
    3. USB pairing -- is the lockdown/pairing channel healthy?

All checks use only public pymobiledevice3 APIs (lockdown / mobileconfig).
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

PRECHECK_SCHEMA_VERSION = "1.0"

# Guidance shown after Step 1 when the device must be erased by hand.
# The tool never performs the erase itself: erasing is a destructive, user-owned
# action performed on-device (Settings -> General -> Transfer or Reset iPhone).
ERASE_GUIDANCE = (
    "Manual step required on the device:\n"
    "  1. On the device: Settings -> General -> Transfer or Reset iPhone -> Erase All Content and Settings\n"
    "  2. Wait for the device to reboot into the Setup Assistant.\n"
    "  3. Stay OFFLINE: do not insert a SIM and do not join Wi-Fi.\n"
    "  4. Walk through language/region -> Quick Start -> Set Up Manually -> Data & Privacy,\n"
    "     then STOP on the screen before Wi-Fi/network selection.\n"
    "  5. Re-run: fleetctl precheck --udid <UDID>  (Step 2 should now pass)"
)

WAIT_ACK_PROMPT = (
    'After erasing on the device, it will reboot into the Setup Assistant.\n'
    'Type "READY" to poll for the offline Setup Assistant state (Ctrl+C to skip): '
)


async def check_erase_availability(udid: str) -> Dict[str, Any]:
    """Step 1: Check whether 'Erase All Content and Settings' is available.

    Read-only. Inspects activation state, supervision (via cloud configuration)
    and passcode protection.
    """
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.mobile_config import MobileConfigService

        lockdown = await create_using_usbmux(serial=udid)
        vals = lockdown.all_values or {}

        activation_state = vals.get("ActivationState", "")

        is_supervised = False
        try:
            async with MobileConfigService(lockdown) as mc:
                cc = await mc.get_cloud_configuration()
                if isinstance(cc, dict):
                    is_supervised = cc.get("IsSupervised", False)
        except Exception:
            pass

        password_protected = vals.get("PasswordProtected", False)

        if activation_state in ["Unactivated", "ActivatedUnlocked"]:
            return {
                "passed": True,
                "status": "AVAILABLE",
                "details": (
                    f"Activation state: {activation_state}, "
                    f"Supervised: {is_supervised}, Passcode: {password_protected}"
                ),
            }
        elif activation_state == "Activated":
            if password_protected:
                return {
                    "passed": True,
                    "status": "AVAILABLE_WITH_PASSCODE",
                    "details": f"Activation state: {activation_state}, Passcode required",
                }
            return {
                "passed": True,
                "status": "AVAILABLE",
                "details": f"Activation state: {activation_state}",
            }
        else:
            return {
                "passed": False,
                "status": "UNAVAILABLE",
                "details": (
                    f"Activation state: {activation_state} - "
                    "device may be in recovery/DFU mode"
                ),
            }
    except Exception as e:
        return {"passed": False, "status": "ERROR", "details": f"Failed to check: {e}"}


async def check_usb_pairing(udid: str) -> Dict[str, Any]:
    """Step 3: Check that the USB pairing/lockdown channel works."""
    try:
        from pymobiledevice3.lockdown import create_using_usbmux

        lockdown = await create_using_usbmux(serial=udid)
        vals = lockdown.all_values or {}

        device_name = vals.get("DeviceName", "Unknown")
        product_type = vals.get("ProductType", "Unknown")

        return {
            "passed": True,
            "status": "PAIRED",
            "details": f"USB pairing working. Device: {device_name} ({product_type})",
        }
    except Exception as e:
        error_msg = str(e).lower()
        if "pair" in error_msg or "trust" in error_msg:
            return {
                "passed": False,
                "status": "NOT_PAIRED",
                "details": f"Device not paired/trusted: {e}",
            }
        return {
            "passed": False,
            "status": "ERROR",
            "details": f"USB connection failed: {e}",
        }


async def run_precheck_steps(
    udid: str,
    collector: Any,
    device_info: Optional[Dict[str, Any]] = None,
    check_step1: Any = None,
    check_step3: Any = None,
    on_step: Any = None,
) -> Dict[str, Any]:
    """Run the three read-only pre-check steps for one device.

    Args:
        udid: Device UDID.
        collector: A ``DeviceInfoCollector`` providing
            ``check_setup_assistant_offline_state``.
        device_info: Optional enumerate() record for name/model/version.
        check_step1 / check_step3: Overridable step functions (for testing).
        on_step: Optional callback ``(step_name, step_result)`` invoked after
            each step completes (for progress reporting).

    Returns:
        Structured result dict with ``steps`` and ``overall_passed``.
    """
    step1_fn = check_step1 or check_erase_availability
    step3_fn = check_step3 or check_usb_pairing

    step1 = await step1_fn(udid)
    if on_step:
        on_step("erase_available", step1)

    raw2 = await collector.check_setup_assistant_offline_state(udid)
    step2 = {
        "passed": bool(raw2.get("ready", False)),
        "status": raw2.get("reason", "unknown"),
        "details": raw2.get("details", {}),
    }
    if on_step:
        on_step("setup_assistant_offline", step2)

    step3 = await step3_fn(udid)
    if on_step:
        on_step("usb_pairing", step3)

    device_info = device_info or {}
    overall = all(s["passed"] for s in (step1, step2, step3))

    return {
        "udid": udid,
        "device_name": device_info.get("device_name"),
        "product_type": device_info.get("product_type"),
        "product_version": device_info.get("product_version"),
        "steps": {
            "erase_available": step1,
            "setup_assistant_offline": step2,
            "usb_pairing": step3,
        },
        "overall_passed": overall,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }


def step_label(name: str) -> str:
    return {
        "erase_available": "Step 1 (Erase Available)",
        "setup_assistant_offline": "Step 2 (Setup Assistant)",
        "usb_pairing": "Step 3 (USB Pairing)",
    }.get(name, name)


def format_precheck_text(result: Dict[str, Any]) -> str:
    """Render a single pre-check result as human-readable text."""
    lines: List[str] = []
    udid = result.get("udid", "")
    lines.append(f"\n{'=' * 60}")
    lines.append(f"Pre-check for device: {udid}")
    if result.get("device_name"):
        lines.append(f"  Name: {result.get('device_name')}")
    if result.get("product_type"):
        lines.append(f"  Model: {result.get('product_type')}")
    if result.get("product_version"):
        lines.append(f"  iOS: {result.get('product_version')}")
    lines.append(f"{'=' * 60}")

    steps = result.get("steps", {})
    ordered = ["erase_available", "setup_assistant_offline", "usb_pairing"]
    for i, key in enumerate(ordered, start=1):
        s = steps.get(key, {})
        lines.append(f"\n[Step {i}/3] {key.replace('_', ' ')}")
        lines.append(f"  Result: {s.get('status', 'unknown')}")
        details = s.get("details")
        if isinstance(details, dict):
            for k, v in details.items():
                lines.append(f"    {k}: {v}")
        elif details:
            lines.append(f"  Details: {details}")

    overall = result.get("overall_passed", False)
    lines.append(f"\n{'=' * 60}")
    lines.append(f"PRE-CHECK SUMMARY: {'PASSED' if overall else 'FAILED'}")
    lines.append(f"{'=' * 60}")
    for key in ordered:
        ok = steps.get(key, {}).get("passed", False)
        lines.append(f"  {step_label(key):<26} {'[OK]' if ok else '[FAIL]'}")

    return "\n".join(lines)


# ---------------------------------------------------------------- #
# Audit report generation                                          #
# ---------------------------------------------------------------- #

def _summary_counts(prechecks: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "total": len(prechecks),
        "passed": sum(1 for p in prechecks if p.get("overall_passed")),
        "failed": sum(1 for p in prechecks if not p.get("overall_passed")),
    }


def generate_precheck_report(
    prechecks: List[Dict[str, Any]],
    format: str = "json",
    title: str = "fleetctl Pre-check Audit Report",
    company_name: Optional[str] = None,
) -> bytes:
    """Generate an audit report (JSON or HTML) for pre-check results."""
    if format == "json":
        report = {
            "schema_version": PRECHECK_SCHEMA_VERSION,
            "report_type": "precheck",
            "metadata": {
                "title": title,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "device_count": len(prechecks),
                "company": company_name,
                "generator": "fleetctl",
            },
            "summary": _summary_counts(prechecks),
            "prechecks": prechecks,
        }
        return json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8")

    if format == "html":
        return _generate_precheck_html(prechecks, title, company_name).encode("utf-8")

    raise ValueError(f"Unsupported report format: {format} (expected json|html)")


def _badge(passed: bool) -> str:
    if passed:
        return '<span class="badge ok">OK</span>'
    return '<span class="badge fail">FAIL</span>'


def _generate_precheck_html(
    prechecks: List[Dict[str, Any]],
    title: str,
    company_name: Optional[str],
) -> str:
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    counts = _summary_counts(prechecks)
    ordered = ["erase_available", "setup_assistant_offline", "usb_pairing"]

    rows = []
    for p in prechecks:
        steps = p.get("steps", {})
        cells = "".join(
            f"<td>{_badge(steps.get(k, {}).get('passed', False))}"
            f"<div class='status'>{html.escape(str(steps.get(k, {}).get('status', '')))}</div></td>"
            for k in ordered
        )
        overall = p.get("overall_passed", False)
        rows.append(
            "<tr>"
            f"<td><div class='name'>{html.escape(str(p.get('device_name') or 'Unknown'))}</div>"
            f"<div class='udid'>{html.escape(str(p.get('udid', '')))}</div></td>"
            f"<td>{html.escape(str(p.get('product_type') or 'Unknown'))}</td>"
            f"<td>{html.escape(str(p.get('product_version') or 'Unknown'))}</td>"
            f"{cells}"
            f"<td>{_badge(overall)}</td>"
            "</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>
  :root {{ --ok:#34C759; --fail:#FF3B30; --primary:#007AFF; --bg:#F5F5F7; --border:#D2D2D7; }}
  * {{ box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;
         margin:0; padding:24px; background:var(--bg); color:#1D1D1F; }}
  .container {{ max-width:1200px; margin:0 auto; background:#fff; border-radius:12px;
               box-shadow:0 2px 10px rgba(0,0,0,.08); overflow:hidden; }}
  header {{ background:linear-gradient(135deg,#007AFF,#5856D6); color:#fff; padding:28px; }}
  header h1 {{ margin:0; font-size:24px; }}
  header .meta {{ margin-top:10px; font-size:13px; opacity:.95; display:flex; gap:18px; flex-wrap:wrap; }}
  .content {{ padding:24px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:16px; margin-bottom:24px; }}
  .card {{ background:var(--bg); border:1px solid var(--border); border-radius:8px; padding:18px; text-align:center; }}
  .card .v {{ font-size:30px; font-weight:700; }}
  .card .l {{ font-size:12px; text-transform:uppercase; letter-spacing:.6px; color:#86868B; margin-top:4px; }}
  .table-wrap {{ overflow-x:auto; border:1px solid var(--border); border-radius:8px; }}
  table {{ width:100%; min-width:820px; border-collapse:collapse; font-size:14px; }}
  th {{ text-align:left; padding:12px 14px; background:var(--bg); font-size:12px;
        text-transform:uppercase; letter-spacing:.6px; border-bottom:2px solid var(--border); }}
  td {{ padding:12px 14px; border-bottom:1px solid var(--border); vertical-align:top; }}
  .name {{ font-weight:600; }}
  .udid {{ font-family:'SF Mono',Monaco,monospace; font-size:11px; color:#86868B; }}
  .status {{ font-size:11px; color:#86868B; margin-top:4px; }}
  .badge {{ display:inline-block; padding:3px 10px; border-radius:100px; font-size:12px; font-weight:600; }}
  .badge.ok {{ background:rgba(52,199,89,.15); color:var(--ok); }}
  .badge.fail {{ background:rgba(255,59,48,.15); color:var(--fail); }}
  footer {{ padding:16px 24px; background:var(--bg); border-top:1px solid var(--border);
            font-size:12px; color:#86868B; text-align:center; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>{html.escape(title)}</h1>
    <div class="meta">
      <span>Generated: {ts}</span>
      <span>Devices: {counts['total']}</span>
      {f'<span>Company: {html.escape(company_name)}</span>' if company_name else ''}
      <span>Schema: v{PRECHECK_SCHEMA_VERSION}</span>
    </div>
  </header>
  <div class="content">
    <div class="cards">
      <div class="card"><div class="v">{counts['total']}</div><div class="l">Total</div></div>
      <div class="card"><div class="v" style="color:var(--ok)">{counts['passed']}</div><div class="l">Passed</div></div>
      <div class="card"><div class="v" style="color:var(--fail)">{counts['failed']}</div><div class="l">Failed</div></div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Device</th><th>Model</th><th>iOS</th>
            <th>Step 1 Erase</th><th>Step 2 Setup</th><th>Step 3 USB</th><th>Overall</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows) if rows else '<tr><td colspan="7">No devices</td></tr>'}
        </tbody>
      </table>
    </div>
  </div>
  <footer>Generated by fleetctl &bull; read-only pre-check &bull; {ts}</footer>
</div>
</body>
</html>"""
