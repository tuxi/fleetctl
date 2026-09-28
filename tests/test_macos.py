"""
Tests for the macOS local-agent module (fleetctl.macos).

All command execution is mocked via a fake runner — no real subprocess runs.
"""

import json
import plistlib

import pytest

from fleetctl.macos import (
    MacInfoCollector,
    CommandRunner,
    run_mac_precheck,
    format_mac_precheck_text,
    generate_mac_precheck_report,
    is_macos,
    _parse_sip,
    _parse_gatekeeper,
    _parse_filevault,
    _parse_mdm_enrollment,
    _parse_profiles_list,
    _parse_battery_percent,
    _parse_disk_plist,
    MACOS_SCHEMA_VERSION,
)


# ---------------------------------------------------------------- #
# Fake runner                                                      #
# ---------------------------------------------------------------- #

class FakeRunner:
    """Returns canned output keyed by '<tool> <first-arg>' or '<tool>'."""

    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    def run(self, args):
        self.calls.append(args)
        tool = args[0].rsplit("/", 1)[-1]
        key = f"{tool} {args[1]}" if len(args) > 1 else tool
        return self.outputs.get(key, self.outputs.get(tool, ""))


SW_VERS = "ProductName:\t\tmacOS\nProductVersion:\t\t26.5.2\nBuildVersion:\t\t25F84\n"

HW = (
    "Hardware:\n\n    Hardware Overview:\n\n"
    "      Model Name: MacBook Pro\n"
    "      Model Identifier: MacBookPro18,3\n"
    "      Model Number: Z15J001GWCH/A\n"
    "      Chip: Apple M1 Pro\n"
    "      Memory: 32 GB\n"
    "      Serial Number (system): Q3K7T4WYCJ\n"
    "      Hardware UUID: A67776F5-6537-5C79-AA2E-2730211A1E06\n"
    "      Provisioning UDID: 00006000-000A044101D8801E\n"
    "      Activation Lock Status: Enabled\n"
)

DISK_PLIST = plistlib.dumps({"TotalSize": 1000000000000, "FreeSpace": 400000000000}).decode()

FULL_OUTPUTS = {
    "sw_vers": SW_VERS,
    "system_profiler SPHardwareDataType": HW,
    "csrutil status": "System Integrity Protection status: enabled.\n",
    "spctl --status": "assessments enabled\n",
    "fdesetup status": "FileVault is Off.\n",
    "profiles status": "Enrolled via DEP: No\nMDM enrollment: No\n",
    "profiles list": "There are no configuration profiles installed.\n",
    "diskutil info": DISK_PLIST,
    "pmset -g": "Now drawing from 'Battery Power'\n -InternalBattery-0 (id=1)\t85%; discharging; present: true\n",
}


def _collector(outputs=None, platform_name="Darwin"):
    return MacInfoCollector(
        runner=FakeRunner(FULL_OUTPUTS if outputs is None else outputs),
        platform_name=platform_name,
    )


# ---------------------------------------------------------------- #
# Platform guard                                                   #
# ---------------------------------------------------------------- #

class TestPlatform:
    def test_is_macos(self):
        assert is_macos("Darwin") is True
        assert is_macos("Linux") is False

    def test_available(self):
        assert _collector().available is True
        assert _collector(platform_name="Linux").available is False

    def test_collect_on_non_macos(self):
        info = _collector(platform_name="Linux").collect()
        assert "platform" in info["errors"]
        assert info["metadata"]["platform"] == "macos"


# ---------------------------------------------------------------- #
# Parsers                                                          #
# ---------------------------------------------------------------- #

class TestParsers:
    def test_sip(self):
        assert _parse_sip("System Integrity Protection status: enabled.") == "enabled"
        assert _parse_sip("System Integrity Protection status: disabled.") == "disabled"
        assert _parse_sip("garbage") is None

    def test_gatekeeper(self):
        assert _parse_gatekeeper("assessments enabled") == "enabled"
        assert _parse_gatekeeper("assessments disabled") == "disabled"

    def test_filevault(self):
        assert _parse_filevault("FileVault is On.") == "On"
        assert _parse_filevault("FileVault is Off.") == "Off"
        assert _parse_filevault("FileVault is Deferred.") == "Deferred"

    def test_mdm_enrollment(self):
        r = _parse_mdm_enrollment("Enrolled via DEP: No\nMDM enrollment: Yes\n")
        assert r["mdm_enrolled"] is True
        assert r["dep_enrolled"] is False

    def test_profiles_list(self):
        assert _parse_profiles_list("There are no configuration profiles installed.") == []
        assert _parse_profiles_list("") == []

    def test_battery_percent(self):
        assert _parse_battery_percent("...\t85%; discharging; present: true") == 85
        assert _parse_battery_percent("no battery") is None

    def test_disk_plist(self):
        d = _parse_disk_plist(DISK_PLIST)
        assert d["total"] == 1000000000000
        assert d["free"] == 400000000000
        assert _parse_disk_plist("not a plist") == {"total": None, "free": None}


# ---------------------------------------------------------------- #
# Inventory                                                        #
# ---------------------------------------------------------------- #

class TestInventory:
    def test_collect_maps_fields(self):
        info = _collector().collect()
        ident = info["identity"]
        assert ident["product_type"] == "MacBookPro18,3"
        assert ident["serial_number"] == "Q3K7T4WYCJ"
        assert ident["product_version"] == "26.5.2"
        assert ident["build_version"] == "25F84"
        assert ident["device_name"] == "MacBook Pro"
        assert ident["device_class"] == "Mac"
        assert ident["udid"] == "00006000-000A044101D8801E"

        status = info["status"]
        assert status["sip"] == "enabled"
        assert status["gatekeeper"] == "enabled"
        assert status["filevault"] == "Off"
        assert status["mdm_enrolled"] is False
        assert status["activation_lock"] == "Enabled"

        meta = info["metadata"]
        assert meta["platform"] == "macos"
        assert meta["chip"] == "Apple M1 Pro"
        assert meta["memory"] == "32 GB"

        res = info["resources"]
        assert res["total_disk_capacity"] == 1000000000000
        assert res["data_available"] == 400000000000
        assert res["battery_percent"] == 85

    def test_collect_defensive_on_empty_output(self):
        info = _collector(outputs={}).collect()
        assert "hardware" in info["errors"]
        assert "software" in info["errors"]
        assert "sip" in info["unavailable"]
        assert info["identity"]["product_type"] is None


# ---------------------------------------------------------------- #
# Pre-check                                                        #
# ---------------------------------------------------------------- #

class TestPrecheck:
    def test_run_precheck_structure(self):
        result = run_mac_precheck(_collector())
        assert set(result["checks"]) == {"sip", "filevault", "secure_boot", "mdm_enrollment"}
        assert result["checks"]["sip"]["passed"] is True
        assert result["checks"]["filevault"]["passed"] is False  # Off
        assert result["overall_passed"] is False
        assert result["product_type"] == "MacBookPro18,3"

    def test_run_precheck_all_pass(self):
        outputs = dict(FULL_OUTPUTS)
        outputs["fdesetup status"] = "FileVault is On.\n"
        result = run_mac_precheck(_collector(outputs))
        assert result["overall_passed"] is True

    def test_format_text(self):
        text = format_mac_precheck_text(run_mac_precheck(_collector()))
        assert "MAC PRE-CHECK SUMMARY: FAILED" in text
        assert "System Integrity Protection" in text
        assert "[OK]" in text and "[FAIL]" in text


# ---------------------------------------------------------------- #
# Reports                                                          #
# ---------------------------------------------------------------- #

class TestReports:
    def _results(self):
        return [run_mac_precheck(_collector())]

    def test_json_report(self):
        data = json.loads(generate_mac_precheck_report(self._results(), "json").decode())
        assert data["schema_version"] == MACOS_SCHEMA_VERSION
        assert data["report_type"] == "mac_precheck"
        assert data["summary"]["total"] == 1

    def test_html_report(self):
        html = generate_mac_precheck_report(self._results(), "html", title="Audit").decode()
        assert "<!DOCTYPE html>" in html
        assert "Audit" in html
        assert 'class="badge' in html

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            generate_mac_precheck_report(self._results(), "xml")


# ---------------------------------------------------------------- #
# CommandRunner (no real execution)                                #
# ---------------------------------------------------------------- #

class TestCommandRunner:
    def test_run_returns_empty_on_failure(self):
        runner = CommandRunner(timeout=0.001)
        # A non-existent binary must not raise; returns "".
        assert runner.run(["/nonexistent/binary-xyz"]) == ""
