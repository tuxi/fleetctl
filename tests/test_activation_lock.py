"""
Tests for the activation lock probe (激活锁判定).

The probe is what tells a clean device from one locked to another Apple
account -- ``ActivationState`` alone cannot.
"""

import pymobiledevice3.lockdown
import pymobiledevice3.services.mobile_activation
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fleetctl.activation_lock import (
    ACTIVATION_SCHEMA_VERSION,
    ActivationProbe,
    LockVerdict,
    classify_activation_response,
    probe_activation_lock,
)


# ---------------------------------------------------------------- #
# Fixtures                                                         #
# ---------------------------------------------------------------- #

ACTIVATION_LOCK_FORM = b"""<?xml version="1.0" encoding="UTF-8"?>
<document>
  <page>
    <navigationBar title="Activation Lock"/>
    <tableView>
      <section>
        <footer>This iPhone is linked to an Apple account. Enter the Apple account
        and password that were used to set up this iPhone. d&#8226;&#8226;&#8226;&#8226;&#8226;@6&#8226;&#8226;&#8226;&#8226;&#8226;.com</footer>
      </section>
    </tableView>
  </page>
  <serverInfo protocolVersion="3"/>
</document>
"""

REMOTE_MANAGEMENT_FORM = b"""<?xml version="1.0" encoding="UTF-8"?>
<document>
  <page>
    <navigationBar title="Remote Management"/>
    <tableView>
      <section>
        <footer>This iPhone is managed by Acme Corporation.</footer>
      </section>
    </tableView>
  </page>
  <serverInfo protocolVersion="3"/>
</document>
"""

UNKNOWN_FORM = b"""<?xml version="1.0" encoding="UTF-8"?>
<document>
  <page>
    <navigationBar title="Sign In"/>
    <tableView><section><footer>Please continue.</footer></section></tableView>
  </page>
  <serverInfo protocolVersion="3"/>
</document>
"""


class TestClassify:
    def test_activation_record_is_clean(self):
        probe = classify_activation_response(
            "text/xml; charset=utf-8", b"<plist/>", activation_state="Unactivated"
        )
        assert probe.verdict is LockVerdict.CLEAN
        assert probe.passed is True

    def test_activation_lock_form(self):
        probe = classify_activation_response(
            "application/x-buddyml", ACTIVATION_LOCK_FORM, activation_state="Unactivated"
        )
        assert probe.verdict is LockVerdict.ICLOUD_LOCK
        assert probe.passed is False
        assert probe.masked_account == "d•••••@6•••••.com"
        assert "Apple account" in (probe.server_message or "")

    def test_remote_management_form(self):
        probe = classify_activation_response(
            "application/x-buddyml", REMOTE_MANAGEMENT_FORM
        )
        assert probe.verdict is LockVerdict.MDM_LOCK
        assert probe.organization == "Acme Corporation"

    def test_unknown_form_is_not_clean(self):
        probe = classify_activation_response("application/x-buddyml", UNKNOWN_FORM)
        assert probe.verdict is LockVerdict.UNDETERMINED
        assert probe.passed is False

    def test_malformed_xml_is_not_clean(self):
        probe = classify_activation_response("application/x-buddyml", b"<broken")
        assert probe.verdict is LockVerdict.UNDETERMINED

    def test_missing_content_type(self):
        probe = classify_activation_response("", b"...")
        assert probe.verdict is LockVerdict.UNDETERMINED

    def test_unexpected_content_type(self):
        probe = classify_activation_response("text/html", b"<html/>")
        assert probe.verdict is LockVerdict.UNDETERMINED

    def test_to_dict_shape(self):
        probe = ActivationProbe(LockVerdict.CLEAN)
        data = probe.to_dict()
        assert data["schema_version"] == ACTIVATION_SCHEMA_VERSION
        assert data["verdict"] == "clean"
        assert data["passed"] is True
        assert data["checked_at"]


# ---------------------------------------------------------------- #
# Probe                                                            #
# ---------------------------------------------------------------- #

class FakeService:
    """Stands in for MobileActivationService."""

    def __init__(self, state="Unactivated", response=None, error=None):
        self._state = state
        self._response = response or (b"<plist/>", {"Content-Type": "text/xml"})
        self._error = error
        self.posts = []
        self.applied = False

    async def state(self):
        if self._error:
            raise self._error
        return self._state

    async def create_activation_session_info(self):
        return {"handshake": True}

    async def create_activation_info_with_session(self, handshake):
        return {"info": True}

    def post(self, url, data=None, headers=None):
        self.posts.append(url)
        if len(self.posts) == 1:
            return b"<handshake/>", {"Content-Type": "text/xml"}
        return self._response

    async def activate_with_session(self, *args, **kwargs):  # must never be called
        self.applied = True


def _probe_with(service):
    lockdown = MagicMock()
    with patch.object(
        pymobiledevice3.lockdown, "create_using_usbmux", AsyncMock(return_value=lockdown)
    ), patch.object(
        pymobiledevice3.services.mobile_activation,
        "MobileActivationService",
        return_value=service,
    ):
        return _run(probe_activation_lock("udid-1"))


def _run(coro):
    import asyncio

    return asyncio.run(coro)


class TestProbe:
    def test_clean_device(self):
        service = FakeService(response=(b"<plist/>", {"Content-Type": "text/xml"}))
        probe = _probe_with(service)
        assert probe.verdict is LockVerdict.CLEAN
        assert probe.activation_state == "Unactivated"
        assert service.applied is False

    def test_icloud_locked_device(self):
        service = FakeService(
            response=(ACTIVATION_LOCK_FORM, {"Content-Type": "application/x-buddyml"})
        )
        probe = _probe_with(service)
        assert probe.verdict is LockVerdict.ICLOUD_LOCK
        assert probe.masked_account == "d•••••@6•••••.com"
        assert service.applied is False

    def test_mdm_device(self):
        service = FakeService(
            response=(REMOTE_MANAGEMENT_FORM, {"Content-Type": "application/x-buddyml"})
        )
        probe = _probe_with(service)
        assert probe.verdict is LockVerdict.MDM_LOCK
        assert service.applied is False

    def test_activated_device_requires_erase(self):
        service = FakeService(state="Activated")
        probe = _probe_with(service)
        assert probe.verdict is LockVerdict.PENDING_ERASE
        assert probe.passed is False
        assert service.posts == []

    def test_connection_error_is_undetermined(self):
        service = FakeService(error=RuntimeError("no device"))
        probe = _probe_with(service)
        assert probe.verdict is LockVerdict.UNDETERMINED
        assert "no device" in (probe.error or "")

    def test_never_applies_activation_record(self):
        service = FakeService(response=(b"<plist/>", {"Content-Type": "text/xml"}))
        _probe_with(service)
        assert service.applied is False
