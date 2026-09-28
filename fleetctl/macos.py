"""
Compliant macOS device management (local agent).

Runs **on the Mac itself** and uses only public macOS command-line tools
(system_profiler, sw_vers, csrutil, spctl, fdesetup, profiles, diskutil, pmset).

Read-only: this module performs no writes, requires no sudo, and does not
attempt any MDM / activation bypass. Write operations (profile install/remove,
FileVault enable, erase) are intentionally out of scope for this stage.
"""

from __future__ import annotations

import html
import json
import platform
import plistlib
import subprocess
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

MACOS_SCHEMA_VERSION = "1.0"

# Absolute tool paths (preferred); the runner falls back to PATH lookup.
_TOOLS: Dict[str, str] = {
    "system_profiler": "/usr/sbin/system_profiler",
    "sw_vers": "/usr/bin/sw_vers",
    "csrutil": "/usr/bin/csrutil",
    "spctl": "/usr/sbin/spctl",
    "fdesetup": "/usr/bin/fdesetup",
    "profiles": "/usr/bin/profiles",
    "diskutil": "/usr/sbin/diskutil",
    "pmset": "/usr/bin/pmset",
    "sysctl": "/usr/sbin/sysctl",
}

# Human labels for the read-only pre-check items.
MAC_CHECK_LABELS: Dict[str, str] = {
    "sip": "System Integrity Protection",
    "filevault": "FileVault",
    "secure_boot": "Secure Boot",
    "mdm_enrollment": "MDM Enrollment",
}


class CommandRunner:
    """Executes a native command and returns stdout.

    Injectable so tests can supply canned output without spawning processes.
    """

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def run(self, args: List[str]) -> str:
        try:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=self.timeout
            )
            return proc.stdout or ""
        except (subprocess.SubprocessError, OSError):
            return ""


def is_macos(platform_name: Optional[str] = None) -> bool:
    """Return True when running on macOS."""
    return (platform_name or platform.system()) == "Darwin"


def _tool(name: str) -> str:
    return _TOOLS.get(name, name)


# ---------------------------------------------------------------- #
# Parsing helpers                                                  #
# ---------------------------------------------------------------- #

def _parse_key_values(text: str) -> Dict[str, str]:
    """Parse 'Key: Value' lines (system_profiler / sw_vers / profiles)."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if key:
                out[key] = value
    return out


def _ci_get(mapping: Dict[str, str], key: str, default: Optional[str] = None) -> Optional[str]:
    """Case-insensitive lookup (system_profiler key casing varies by version)."""
    key_l = key.lower()
    for k, v in mapping.items():
        if k.lower() == key_l:
            return v
    return default


def _parse_sip(text: str) -> Optional[str]:
    """Return 'enabled' / 'disabled' from `csrutil status`."""
    lowered = text.lower()
    if "status: enabled" in lowered:
        return "enabled"
    if "status: disabled" in lowered:
        return "disabled"
    return None


def _parse_gatekeeper(text: str) -> Optional[str]:
    """Return 'enabled' / 'disabled' from `spctl --status`."""
    lowered = text.lower()
    if "assessments enabled" in lowered:
        return "enabled"
    if "assessments disabled" in lowered:
        return "disabled"
    return None


def _parse_filevault(text: str) -> Optional[str]:
    """Return 'On' / 'Off' / 'Deferred' from `fdesetup status`."""
    lowered = text.lower()
    if "filevault is on" in lowered:
        return "On"
    if "filevault is off" in lowered:
        return "Off"
    if "deferred" in lowered:
        return "Deferred"
    return None


def _parse_mdm_enrollment(text: str) -> Dict[str, Any]:
    """Parse `profiles status -type enrollment`."""
    kv = _parse_key_values(text)
    enrolled = None
    for key, value in kv.items():
        if "mdm enrollment" in key.lower():
            enrolled = value.strip().lower() in ("yes", "true")
    dep = None
    for key, value in kv.items():
        if "dep" in key.lower():
            dep = value.strip().lower() in ("yes", "true")
    return {"mdm_enrolled": enrolled, "dep_enrolled": dep, "raw": kv}


def _parse_profiles_list(text: str) -> List[str]:
    """Return installed profile identifiers/names from `profiles list`."""
    lowered = text.lower()
    if "no configuration profiles" in lowered or not text.strip():
        return []
    names: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.endswith(":"):
            continue
        # `profiles list` prints indented attribute lines; keep the profile name.
        if "attribute:" in stripped.lower():
            continue
        names.append(stripped)
    return names


def _parse_battery_percent(text: str) -> Optional[int]:
    """Extract the battery percentage from `pmset -g batt`."""
    for token in text.replace("\t", " ").split():
        if "%" in token:
            try:
                return int(token.split("%")[0])
            except ValueError:
                continue
    return None


def _parse_disk_plist(text: str) -> Dict[str, Optional[int]]:
    """Parse `diskutil info -plist /` into total/free bytes."""
    try:
        data = plistlib.loads(text.encode("utf-8"))
    except Exception:
        return {"total": None, "free": None}
    total = data.get("TotalSize") or data.get("APFSContainerSize")
    free = data.get("FreeSpace") or data.get("APFSContainerFree")
    return {
        "total": int(total) if isinstance(total, (int, float)) else None,
        "free": int(free) if isinstance(free, (int, float)) else None,
    }


# ---------------------------------------------------------------- #
# Inventory collector                                              #
# ---------------------------------------------------------------- #

class MacInfoCollector:
    """Collects macOS inventory using only public command-line tools."""

    def __init__(
        self,
        runner: Optional[CommandRunner] = None,
        platform_name: Optional[str] = None,
    ):
        self._runner = runner or CommandRunner()
        self._platform = platform_name or platform.system()

    @property
    def available(self) -> bool:
        return self._platform == "Darwin"

    def _run(self, tool: str, *args: str) -> str:
        return self._runner.run([_tool(tool), *args])

    def collect(self) -> Dict[str, Any]:
        """Collect Mac inventory as a report-compatible device dict."""
        if not self.available:
            return {
                "identity": {"udid": None, "device_class": "Mac"},
                "status": {},
                "resources": {},
                "metadata": {"platform": "macos"},
                "errors": {"platform": f"macOS required (running on {self._platform})"},
                "unavailable": [],
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }

        errors: Dict[str, str] = {}
        unavailable: List[str] = []

        sw = _parse_key_values(self._run("sw_vers"))
        hw = _parse_key_values(self._run("system_profiler", "SPHardwareDataType"))
        sip = _parse_sip(self._run("csrutil", "status"))
        gatekeeper = _parse_gatekeeper(self._run("spctl", "--status"))
        filevault = _parse_filevault(self._run("fdesetup", "status"))
        enrollment = _parse_mdm_enrollment(self._run("profiles", "status", "-type", "enrollment"))
        profiles = _parse_profiles_list(self._run("profiles", "list"))
        disk = _parse_disk_plist(self._run("diskutil", "info", "-plist", "/"))
        battery = _parse_battery_percent(self._run("pmset", "-g", "batt"))

        model_identifier = _ci_get(hw, "Model Identifier")
        chip = _ci_get(hw, "Chip")
        serial = _ci_get(hw, "Serial Number (system)") or _ci_get(hw, "Serial Number (System)")
        udid = _ci_get(hw, "Provisioning UDID") or _ci_get(hw, "Hardware UUID")
        os_version = sw.get("ProductVersion")
        build = sw.get("BuildVersion")

        if not hw:
            errors["hardware"] = "system_profiler returned no data"
        if not sw:
            errors["software"] = "sw_vers returned no data"
        if sip is None:
            unavailable.append("sip")
        if filevault is None:
            unavailable.append("filevault")
        if enrollment.get("mdm_enrolled") is None:
            unavailable.append("mdm_enrollment")

        return {
            "identity": {
                "udid": udid,
                "serial_number": serial,
                "product_type": model_identifier,
                "product_version": os_version,
                "build_version": build,
                "device_name": _ci_get(hw, "Model Name"),
                "model_number": _ci_get(hw, "Model Number"),
                "hardware_model": model_identifier,
                "hardware_platform": chip,
                "activation_state": None,
                "region_info": None,
                "imei": None,
                "meid": None,
                "cpu_architecture": platform.machine(),
                "device_class": "Mac",
                "colors": None,
            },
            "status": {
                "activation_state": None,
                "password_protected": None,
                "is_supervised": None,
                "configuration_source": None,
                "cloud_configuration_present": enrollment.get("mdm_enrolled"),
                "profiles_count": len(profiles),
                "profiles": profiles,
                "sip": sip,
                "gatekeeper": gatekeeper,
                "filevault": filevault,
                "mdm_enrolled": enrollment.get("mdm_enrolled"),
                "dep_enrolled": enrollment.get("dep_enrolled"),
                "activation_lock": _ci_get(hw, "Activation Lock Status"),
            },
            "resources": {
                "total_disk_capacity": disk.get("total"),
                "total_data_capacity": disk.get("total"),
                "data_available": disk.get("free"),
                "total_system_capacity": None,
                "battery_cycle_count": None,
                "battery_design_capacity": None,
                "battery_full_charge_capacity": None,
                "battery_percent": battery,
                "apps_count": None,
                "apps_static_bytes": None,
                "apps_dynamic_bytes": None,
            },
            "metadata": {
                "platform": "macos",
                "chip": chip,
                "ios_version": os_version,  # report compatibility (OS version)
                "os_version": os_version,
                "board_id": model_identifier,
                "hardware_platform": chip,
                "memory": _ci_get(hw, "Memory"),
            },
            "errors": errors,
            "unavailable": unavailable,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


# ---------------------------------------------------------------- #
# Read-only pre-check                                              #
# ---------------------------------------------------------------- #

def run_mac_precheck(collector: Optional[MacInfoCollector] = None) -> Dict[str, Any]:
    """Run read-only macOS readiness checks.

    Checks: SIP, FileVault, Secure Boot (best-effort), MDM enrollment.
    No writes, no sudo.
    """
    collector = collector or MacInfoCollector()
    info = collector.collect()
    status = info.get("status", {})
    identity = info.get("identity", {})

    sip = status.get("sip")
    filevault = status.get("filevault")
    mdm_enrolled = status.get("mdm_enrolled")

    checks: Dict[str, Dict[str, Any]] = {}

    checks["sip"] = {
        "passed": sip == "enabled",
        "status": sip or "unknown",
        "details": "System Integrity Protection is enabled" if sip == "enabled"
        else f"System Integrity Protection is {sip or 'unknown'}",
    }
    checks["filevault"] = {
        "passed": filevault == "On",
        "status": filevault or "unknown",
        "details": "FileVault is On" if filevault == "On"
        else f"FileVault is {filevault or 'unknown'}",
    }
    # Secure Boot is not reliably queryable on all Macs; informational only.
    checks["secure_boot"] = {
        "passed": True,
        "status": "unknown",
        "details": "Secure Boot status is not exposed by public tools on this Mac",
    }
    checks["mdm_enrollment"] = {
        "passed": True,
        "status": "enrolled" if mdm_enrolled else "not_enrolled",
        "details": "Mac is already MDM-enrolled" if mdm_enrolled
        else "Mac is not MDM-enrolled",
    }

    overall = all(c["passed"] for c in checks.values())

    return {
        "udid": identity.get("udid"),
        "device_name": identity.get("device_name"),
        "product_type": identity.get("product_type"),
        "product_version": identity.get("product_version"),
        "checks": checks,
        "overall_passed": overall,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }


def format_mac_precheck_text(result: Dict[str, Any]) -> str:
    """Render a Mac pre-check result as human-readable text."""
    lines: List[str] = []
    lines.append(f"\n{'=' * 60}")
    lines.append("Mac pre-check")
    if result.get("device_name"):
        lines.append(f"  Name: {result.get('device_name')}")
    if result.get("product_type"):
        lines.append(f"  Model: {result.get('product_type')}")
    if result.get("product_version"):
        lines.append(f"  macOS: {result.get('product_version')}")
    lines.append(f"{'=' * 60}")

    checks = result.get("checks", {})
    for i, (key, check) in enumerate(checks.items(), start=1):
        label = MAC_CHECK_LABELS.get(key, key)
        lines.append(f"\n[{i}/{len(checks)}] {label}")
        lines.append(f"  Result: {check.get('status', 'unknown')}")
        if check.get("details"):
            lines.append(f"  Details: {check['details']}")

    overall = result.get("overall_passed", False)
    lines.append(f"\n{'=' * 60}")
    lines.append(f"MAC PRE-CHECK SUMMARY: {'PASSED' if overall else 'FAILED'}")
    lines.append(f"{'=' * 60}")
    for key, check in checks.items():
        label = MAC_CHECK_LABELS.get(key, key)
        lines.append(f"  {label:<28} {'[OK]' if check.get('passed') else '[FAIL]'}")
    return "\n".join(lines)


def _mac_summary_counts(results: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "total": len(results),
        "passed": sum(1 for r in results if r.get("overall_passed")),
        "failed": sum(1 for r in results if not r.get("overall_passed")),
    }


def generate_mac_precheck_report(
    results: List[Dict[str, Any]],
    format: str = "json",
    title: str = "fleetctl macOS Pre-check Audit Report",
    company_name: Optional[str] = None,
) -> bytes:
    """Generate a macOS pre-check audit report (JSON or HTML)."""
    if format == "json":
        report = {
            "schema_version": MACOS_SCHEMA_VERSION,
            "report_type": "mac_precheck",
            "metadata": {
                "title": title,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "device_count": len(results),
                "company": company_name,
                "generator": "fleetctl",
            },
            "summary": _mac_summary_counts(results),
            "prechecks": results,
        }
        return json.dumps(report, indent=2, ensure_ascii=False).encode("utf-8")

    if format == "html":
        return _generate_mac_precheck_html(results, title, company_name).encode("utf-8")

    raise ValueError(f"Unsupported report format: {format} (expected json|html)")


def _badge(passed: bool) -> str:
    return '<span class="badge ok">OK</span>' if passed else '<span class="badge fail">FAIL</span>'


def _generate_mac_precheck_html(
    results: List[Dict[str, Any]], title: str, company_name: Optional[str]
) -> str:
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    counts = _mac_summary_counts(results)
    keys = list(MAC_CHECK_LABELS.keys())

    rows = []
    for r in results:
        checks = r.get("checks", {})
        cells = "".join(
            f"<td>{_badge(checks.get(k, {}).get('passed', False))}"
            f"<div class='status'>{html.escape(str(checks.get(k, {}).get('status', '')))}</div></td>"
            for k in keys
        )
        rows.append(
            "<tr>"
            f"<td><div class='name'>{html.escape(str(r.get('device_name') or 'Mac'))}</div>"
            f"<div class='udid'>{html.escape(str(r.get('udid') or ''))}</div></td>"
            f"<td>{html.escape(str(r.get('product_type') or 'Unknown'))}</td>"
            f"<td>{html.escape(str(r.get('product_version') or 'Unknown'))}</td>"
            f"{cells}"
            f"<td>{_badge(r.get('overall_passed', False))}</td>"
            "</tr>"
        )

    headers = "".join(f"<th>{html.escape(MAC_CHECK_LABELS[k])}</th>" for k in keys)

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
      <span>Macs: {counts['total']}</span>
      {f'<span>Company: {html.escape(company_name)}</span>' if company_name else ''}
      <span>Schema: v{MACOS_SCHEMA_VERSION}</span>
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
          <tr><th>Mac</th><th>Model</th><th>macOS</th>{headers}<th>Overall</th></tr>
        </thead>
        <tbody>
          {''.join(rows) if rows else '<tr><td colspan="8">No Macs</td></tr>'}
        </tbody>
      </table>
    </div>
  </div>
  <footer>Generated by fleetctl &bull; read-only macOS pre-check &bull; {ts}</footer>
</div>
</body>
</html>"""
