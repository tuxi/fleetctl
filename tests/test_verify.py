"""
Tests for post-erase verification (擦除后激活锁复验).
"""

import argparse
import json
from unittest.mock import AsyncMock

import pytest

from fleetctl import main
from fleetctl.activation_lock import (
    ActivationProbe,
    LockVerdict,
    VerifyResult,
    format_verify_text,
    verify_device,
)


# ---------------------------------------------------------------- #
# Helpers                                                          #
# ---------------------------------------------------------------- #

class TickClock:
    """Monotonic clock that advances one second per call."""

    def __init__(self, step=1.0):
        self.value = 0.0
        self.step = step

    def __call__(self):
        self.value += self.step
        return self.value


def _probe(verdict, **kwargs):
    return ActivationProbe(verdict, **kwargs)


def _sequence(*verdicts):
    """Probe stub returning the given verdicts in order, then repeating the last."""
    calls = {"n": 0}

    async def probe(udid):
        index = min(calls["n"], len(verdicts) - 1)
        calls["n"] += 1
        return _probe(verdicts[index])

    return probe


# ---------------------------------------------------------------- #
# verify_device                                                    #
# ---------------------------------------------------------------- #

class TestVerifyDevice:
    async def test_clean_stops_immediately(self):
        result = await verify_device("udid-1", probe=_sequence(LockVerdict.CLEAN))
        assert result.passed is True
        assert result.exit_code == 0
        assert result.attempts == 1

    async def test_icloud_lock_is_blocking(self):
        result = await verify_device(
            "udid-1",
            probe=_sequence(LockVerdict.ICLOUD_LOCK),
        )
        assert result.passed is False
        assert result.exit_code == 1

    async def test_mdm_lock_is_blocking(self):
        result = await verify_device("udid-1", probe=_sequence(LockVerdict.MDM_LOCK))
        assert result.exit_code == 1

    async def test_pending_erase_single_probe(self):
        result = await verify_device(
            "udid-1", timeout=0, probe=_sequence(LockVerdict.PENDING_ERASE)
        )
        assert result.verdict is LockVerdict.PENDING_ERASE
        assert result.exit_code == 2
        assert result.attempts == 1

    async def test_polls_until_decisive(self):
        probe = _sequence(
            LockVerdict.PENDING_ERASE, LockVerdict.PENDING_ERASE, LockVerdict.CLEAN
        )
        sleep = AsyncMock()
        result = await verify_device(
            "udid-1", timeout=100, interval=1, probe=probe,
            sleep=sleep, clock=TickClock(),
        )
        assert result.attempts == 3
        assert result.exit_code == 0
        assert sleep.await_count == 2

    async def test_timeout_leaves_undetermined(self):
        result = await verify_device(
            "udid-1", timeout=5, interval=1,
            probe=_sequence(LockVerdict.UNDETERMINED),
            sleep=AsyncMock(), clock=TickClock(),
        )
        assert result.verdict is LockVerdict.UNDETERMINED
        assert result.exit_code == 2
        assert result.attempts > 1

    async def test_to_dict_shape(self):
        result = await verify_device("udid-1", probe=_sequence(LockVerdict.CLEAN))
        data = result.to_dict()
        assert data["udid"] == "udid-1"
        assert data["verified"] is True
        assert data["verdict"] == "clean"
        assert data["exit_code"] == 0
        assert data["probe"]["verdict"] == "clean"


# ---------------------------------------------------------------- #
# format_verify_text                                               #
# ---------------------------------------------------------------- #

class TestFormat:
    @pytest.mark.parametrize(
        "verdict, expected",
        [
            (LockVerdict.CLEAN, "PASSED"),
            (LockVerdict.ICLOUD_LOCK, "BLOCKED - iCloud Activation Lock"),
            (LockVerdict.MDM_LOCK, "BLOCKED - MDM Remote Management"),
            (LockVerdict.PENDING_ERASE, "still activated"),
            (LockVerdict.UNDETERMINED, "could not reach"),
        ],
    )
    def test_headlines(self, verdict, expected):
        text = format_verify_text(VerifyResult("udid-1", _probe(verdict)))
        assert expected in text

    def test_shows_masked_account(self):
        probe = _probe(LockVerdict.ICLOUD_LOCK, masked_account="d•••••@6•••••.com")
        text = format_verify_text(VerifyResult("udid-1", probe))
        assert "d•••••@6•••••.com" in text
        assert "purchase receipt" in text

    def test_shows_organization(self):
        probe = _probe(LockVerdict.MDM_LOCK, organization="Acme Corp")
        text = format_verify_text(VerifyResult("udid-1", probe))
        assert "Acme Corp" in text


# ---------------------------------------------------------------- #
# cmd_verify                                                       #
# ---------------------------------------------------------------- #

class FakeManager:
    def __init__(self, devices):
        self._devices = devices

    async def enumerate(self):
        return self._devices


def _args(**over):
    base = dict(udid=None, wait=0, interval=5.0, json=False, report=None)
    base.update(over)
    return argparse.Namespace(**base)


DEVICE = {"udid": "00008101-AAAA", "device_name": "iPhone"}


def _patch(monkeypatch, devices, result):
    monkeypatch.setattr(main, "USBDeviceManager", lambda: FakeManager(devices))

    async def fake_verify(udid, timeout=0.0, interval=5.0):
        return VerifyResult(udid=udid, probe=result)

    monkeypatch.setattr(main, "verify_device", fake_verify)


class TestCmdVerify:
    async def test_clean_device_exits_zero(self, monkeypatch, capsys):
        _patch(monkeypatch, [DEVICE], _probe(LockVerdict.CLEAN))
        code = await main.cmd_verify(_args())
        assert code == 0
        assert "PASSED" in capsys.readouterr().out

    async def test_locked_device_exits_one(self, monkeypatch, capsys):
        _patch(monkeypatch, [DEVICE], _probe(LockVerdict.ICLOUD_LOCK))
        code = await main.cmd_verify(_args(udid="00008101-AAAA"))
        assert code == 1
        assert "BLOCKED" in capsys.readouterr().out

    async def test_no_devices(self, monkeypatch, capsys):
        _patch(monkeypatch, [], _probe(LockVerdict.CLEAN))
        code = await main.cmd_verify(_args())
        assert code == 2
        assert "No devices connected." in capsys.readouterr().out

    async def test_multiple_devices_requires_udid(self, monkeypatch, capsys):
        _patch(monkeypatch, [DEVICE, {"udid": "second"}], _probe(LockVerdict.CLEAN))
        code = await main.cmd_verify(_args())
        assert code == 2
        assert "Pass --udid" in capsys.readouterr().out

    async def test_json_output(self, monkeypatch, capsys):
        _patch(monkeypatch, [DEVICE], _probe(LockVerdict.CLEAN))
        await main.cmd_verify(_args(json=True))
        out = capsys.readouterr().out
        payload = json.loads(out[out.index("{"):])
        assert payload["verified"] is True

    async def test_report_written(self, monkeypatch, tmp_path):
        _patch(monkeypatch, [DEVICE], _probe(LockVerdict.MDM_LOCK))
        path = tmp_path / "verify.json"
        await main.cmd_verify(_args(udid="00008101-AAAA", report=str(path)))
        data = json.loads(path.read_text())
        assert data["verdict"] == "mdm_lock"
        assert data["exit_code"] == 1
