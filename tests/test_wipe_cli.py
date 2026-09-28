"""
Tests for the destructive `fleetctl wipe` CLI confirmation gate.
"""

import argparse
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from fleetctl import main
from fleetctl.wipe_manager import WipeResult


def _args(**over):
    base = dict(
        udid="u1", method="full", preserve_data_plan=False, disallow_proximity=False,
        verify=True, no_certificate=False, confirm=False, certificate=None,
        certificate_format="json", company=None, json=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


class _FakeUSBManager:
    def __init__(self, devices):
        self._devices = devices

    async def enumerate(self):
        return self._devices


def _patch_env(monkeypatch, wipe_result):
    monkeypatch.setattr(
        main, "USBDeviceManager",
        lambda: _FakeUSBManager([{"udid": "u1", "device_name": "iPhone", "product_type": "iPhone13,3"}]),
    )
    fake = MagicMock()
    fake.wipe_device = AsyncMock(return_value=wipe_result)
    monkeypatch.setattr(main, "WipeManager", lambda: fake)
    # Avoid the 3-second countdown in tests
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    return fake


class TestConfirmWipeHelper:
    def test_aborts_on_wrong_text(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", lambda *a, **k: "nope")
        assert main._confirm_wipe([{"udid": "u1"}]) is False
        assert "Aborted" in capsys.readouterr().out

    def test_proceeds_on_wipe(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda *a, **k: "WIPE")
        monkeypatch.setattr(main.time, "sleep", lambda *_: None)
        assert main._confirm_wipe([{"udid": "u1"}]) is True


class TestCmdWipeConfirmation:
    async def test_requires_confirm_flag(self, monkeypatch):
        fake = _patch_env(monkeypatch, WipeResult(success=True, method="full", udid="u1", message="ok"))
        with pytest.raises(SystemExit) as exc:
            await main.cmd_wipe(_args(confirm=False))
        assert exc.value.code == 1
        fake.wipe_device.assert_not_awaited()

    async def test_aborts_on_wrong_text(self, monkeypatch):
        fake = _patch_env(monkeypatch, WipeResult(success=True, method="full", udid="u1", message="ok"))
        monkeypatch.setattr("builtins.input", lambda *a, **k: "no")
        with pytest.raises(SystemExit) as exc:
            await main.cmd_wipe(_args(confirm=True))
        assert exc.value.code == 1
        fake.wipe_device.assert_not_awaited()

    async def test_proceeds_and_writes_certificate(self, monkeypatch, tmp_path):
        cert = json.dumps({"device": {"udid": "u1"}, "result": "success"})
        fake = _patch_env(
            monkeypatch,
            WipeResult(success=True, method="full", udid="u1", message="ok", certificate=cert),
        )
        monkeypatch.setattr("builtins.input", lambda *a, **k: "WIPE")
        out = tmp_path / "cert.json"
        await main.cmd_wipe(_args(confirm=True, certificate=str(out), certificate_format="json", json=True))
        fake.wipe_device.assert_awaited()
        assert out.exists()
        assert json.loads(out.read_text())["device"]["udid"] == "u1"
