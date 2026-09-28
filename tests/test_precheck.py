"""
Tests for the precheck module and the `fleetctl precheck` command.
"""

import argparse
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pymobiledevice3.lockdown
import pymobiledevice3.services.mobile_config

from fleetctl import main
from fleetctl.precheck import (
    run_precheck_steps,
    format_precheck_text,
    generate_precheck_report,
    check_erase_availability,
    check_usb_pairing,
    ERASE_GUIDANCE,
    PRECHECK_SCHEMA_VERSION,
)


# ---------------------------------------------------------------- #
# Helpers                                                          #
# ---------------------------------------------------------------- #

class FakeCollector:
    """Stand-in for DeviceInfoCollector.check_setup_assistant_offline_state."""

    def __init__(self, ready=True, reason="offline_setup_assistant_ready", details=None):
        self.ready = ready
        self.reason = reason
        self.details = details if details is not None else {"is_unactivated": ready}
        self.calls = 0

    async def check_setup_assistant_offline_state(self, udid):
        self.calls += 1
        return {"ready": self.ready, "reason": self.reason, "details": self.details}


def _ok(status="AVAILABLE", details="ok"):
    return {"passed": True, "status": status, "details": details}


def _fail(status="ERROR", details="boom"):
    return {"passed": False, "status": status, "details": details}


async def _step1_ok(udid):
    return _ok()


async def _step3_ok(udid):
    return _ok("PAIRED", "USB pairing working")


async def _step1_fail(udid):
    return _fail("UNAVAILABLE")


# ---------------------------------------------------------------- #
# run_precheck_steps                                               #
# ---------------------------------------------------------------- #

class TestRunPrecheckSteps:
    async def test_all_pass(self):
        result = await run_precheck_steps(
            "udid-1", FakeCollector(ready=True),
            device_info={"device_name": "iPhone", "product_type": "iPhone13,3", "product_version": "17.0"},
            check_step1=_step1_ok, check_step3=_step3_ok,
        )
        assert result["overall_passed"] is True
        assert result["udid"] == "udid-1"
        assert result["device_name"] == "iPhone"
        assert set(result["steps"]) == {"erase_available", "setup_assistant_offline", "usb_pairing"}
        assert result["steps"]["setup_assistant_offline"]["passed"] is True

    async def test_step2_failure_marks_overall_failed(self):
        result = await run_precheck_steps(
            "udid-1", FakeCollector(ready=False, reason="already_activated"),
            check_step1=_step1_ok, check_step3=_step3_ok,
        )
        assert result["overall_passed"] is False
        assert result["steps"]["setup_assistant_offline"]["status"] == "already_activated"

    async def test_step1_failure_marks_overall_failed(self):
        result = await run_precheck_steps(
            "udid-1", FakeCollector(ready=True),
            check_step1=_step1_fail, check_step3=_step3_ok,
        )
        assert result["overall_passed"] is False

    async def test_on_step_callback_order(self):
        seen = []
        await run_precheck_steps(
            "udid-1", FakeCollector(ready=True),
            check_step1=_step1_ok, check_step3=_step3_ok,
            on_step=lambda name, res: seen.append(name),
        )
        assert seen == ["erase_available", "setup_assistant_offline", "usb_pairing"]


# ---------------------------------------------------------------- #
# format_precheck_text                                             #
# ---------------------------------------------------------------- #

class TestFormatText:
    async def test_contains_summary_and_marks(self):
        result = await run_precheck_steps(
            "udid-xyz", FakeCollector(ready=False, reason="already_activated"),
            device_info={"device_name": "iPhone"},
            check_step1=_step1_ok, check_step3=_step3_ok,
        )
        text = format_precheck_text(result)
        assert "PRE-CHECK SUMMARY: FAILED" in text
        assert "udid-xyz" in text
        assert "[OK]" in text and "[FAIL]" in text


# ---------------------------------------------------------------- #
# generate_precheck_report                                         #
# ---------------------------------------------------------------- #

class TestReport:
    def _sample(self):
        return [{
            "udid": "udid-1", "device_name": "iPhone", "product_type": "iPhone13,3",
            "product_version": "17.0", "overall_passed": True, "checked_at": "2026-01-01T00:00:00Z",
            "steps": {
                "erase_available": _ok(),
                "setup_assistant_offline": _ok(),
                "usb_pairing": _ok("PAIRED"),
            },
        }]

    def test_json_report(self):
        data = json.loads(generate_precheck_report(self._sample(), "json", title="T").decode())
        assert data["schema_version"] == PRECHECK_SCHEMA_VERSION
        assert data["report_type"] == "precheck"
        assert data["summary"] == {"total": 1, "passed": 1, "failed": 0}
        assert data["prechecks"][0]["udid"] == "udid-1"

    def test_html_report(self):
        html = generate_precheck_report(self._sample(), "html", title="Audit").decode()
        assert "<!DOCTYPE html>" in html
        assert "Audit" in html
        assert "iPhone" in html
        assert 'class="badge ok"' in html

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            generate_precheck_report(self._sample(), "xml")

    def test_html_escapes(self):
        sample = self._sample()
        sample[0]["device_name"] = "<script>x</script>"
        html = generate_precheck_report(sample, "html").decode()
        assert "<script>x</script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------- #
# Step functions (mocked lockdown)                                 #
# ---------------------------------------------------------------- #

class TestStepFunctions:
    async def test_erase_available_when_activated(self):
        ld = MagicMock()
        ld.all_values = {"ActivationState": "Activated", "PasswordProtected": False}
        with patch.object(pymobiledevice3.lockdown, "create_using_usbmux", return_value=ld), \
             patch.object(pymobiledevice3.services.mobile_config, "MobileConfigService"):
            result = await check_erase_availability("udid-1")
        assert result["passed"] is True
        assert result["status"] == "AVAILABLE"

    async def test_erase_unavailable_in_recovery(self):
        ld = MagicMock()
        ld.all_values = {"ActivationState": "Recovery"}
        with patch.object(pymobiledevice3.lockdown, "create_using_usbmux", return_value=ld), \
             patch.object(pymobiledevice3.services.mobile_config, "MobileConfigService"):
            result = await check_erase_availability("udid-1")
        assert result["passed"] is False
        assert result["status"] == "UNAVAILABLE"

    async def test_usb_pairing_ok(self):
        ld = MagicMock()
        ld.all_values = {"DeviceName": "iPhone", "ProductType": "iPhone13,3"}
        with patch.object(pymobiledevice3.lockdown, "create_using_usbmux", return_value=ld):
            result = await check_usb_pairing("udid-1")
        assert result["passed"] is True
        assert result["status"] == "PAIRED"

    async def test_usb_pairing_not_paired(self):
        with patch.object(pymobiledevice3.lockdown, "create_using_usbmux",
                          side_effect=Exception("Pairing required")):
            result = await check_usb_pairing("udid-1")
        assert result["passed"] is False
        assert result["status"] == "NOT_PAIRED"


# ---------------------------------------------------------------- #
# cmd_precheck CLI integration                                     #
# ---------------------------------------------------------------- #

class FakeManager:
    def __init__(self, devices):
        self._devices = devices

    async def enumerate(self):
        return self._devices


def _args(**over):
    base = dict(udid=None, json=False, confirm=False, wait=0,
                report=None, report_format="json",
                title="fleetctl Pre-check Audit Report", company=None)
    base.update(over)
    return argparse.Namespace(**base)


DEVICE = {"udid": "00008101-AAAA", "device_name": "iPhone",
          "product_type": "iPhone13,3", "product_version": "17.0"}


def _patch_env(monkeypatch, devices, precheck_result):
    monkeypatch.setattr(main, "USBDeviceManager", lambda: FakeManager(devices))

    async def fake_run(udid, collector, device_info=None, **kwargs):
        cb = kwargs.get("on_step")
        if cb:
            for name in ("erase_available", "setup_assistant_offline", "usb_pairing"):
                cb(name, precheck_result["steps"][name])
        return precheck_result

    monkeypatch.setattr(main, "run_precheck_steps", fake_run)


def _result(overall, s1, s2, s3, udid="00008101-AAAA"):
    return {
        "udid": udid, "device_name": "iPhone", "product_type": "iPhone13,3",
        "product_version": "17.0", "overall_passed": overall, "checked_at": "2026-01-01T00:00:00Z",
        "steps": {"erase_available": s1, "setup_assistant_offline": s2, "usb_pairing": s3},
    }


class TestCmdPrecheck:
    async def test_json_output(self, monkeypatch, capsys):
        res = _result(True, _ok(), _ok(), _ok("PAIRED"))
        _patch_env(monkeypatch, [DEVICE], res)
        await main.cmd_precheck(_args(udid="00008101-AAAA", json=True))
        out = capsys.readouterr().out
        assert "PRE-CHECK SUMMARY: PASSED" in out
        payload = json.loads(out[out.index("{"):])
        assert payload["overall_passed"] is True

    async def test_guidance_printed_when_step2_fails(self, monkeypatch, capsys):
        res = _result(False, _ok(), _fail("already_activated"), _ok("PAIRED"))
        _patch_env(monkeypatch, [DEVICE], res)
        await main.cmd_precheck(_args(udid="00008101-AAAA"))
        out = capsys.readouterr().out
        assert "manual erase" in out.lower()
        assert "PRE-CHECK SUMMARY: FAILED" in out

    async def test_no_devices(self, monkeypatch, capsys):
        _patch_env(monkeypatch, [], _result(True, _ok(), _ok(), _ok()))
        await main.cmd_precheck(_args())
        assert "No devices connected." in capsys.readouterr().out

    async def test_report_written_json(self, monkeypatch, capsys, tmp_path):
        res = _result(True, _ok(), _ok(), _ok("PAIRED"))
        _patch_env(monkeypatch, [DEVICE], res)
        out_path = tmp_path / "audit.json"
        await main.cmd_precheck(_args(udid="00008101-AAAA", report=str(out_path), report_format="json"))
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert data["summary"]["passed"] == 1

    async def test_report_written_html(self, monkeypatch, tmp_path):
        res = _result(True, _ok(), _ok(), _ok("PAIRED"))
        _patch_env(monkeypatch, [DEVICE], res)
        out_path = tmp_path / "audit.html"
        await main.cmd_precheck(_args(udid="00008101-AAAA", report=str(out_path), report_format="html"))
        assert "<!DOCTYPE html>" in out_path.read_text()

    async def test_confirm_wait_updates_step2(self, monkeypatch, capsys):
        # Step 2 fails initially, then the polled collector reports ready.
        res = _result(False, _ok(), _fail("requires_erase"), _ok("PAIRED"))
        _patch_env(monkeypatch, [DEVICE], res)

        fake_collector = FakeCollector(ready=True, reason="offline_setup_assistant_ready")
        monkeypatch.setattr(main, "DeviceInfoCollector", lambda: fake_collector)

        async def fake_wait(collector, udid, timeout, interval=5.0):
            return True

        monkeypatch.setattr(main, "_wait_for_offline_setup_assistant", fake_wait)
        monkeypatch.setattr("builtins.input", lambda *a, **k: "READY")

        await main.cmd_precheck(_args(udid="00008101-AAAA", confirm=True, wait=1))
        out = capsys.readouterr().out
        assert "PRE-CHECK SUMMARY: PASSED" in out
