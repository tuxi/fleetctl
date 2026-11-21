"""
Activation lock probe (激活锁判定).

Answers one question: **would Apple's activation server let this device
activate?** It sends the standard activation request used by every iPhone at
setup time, inspects the server's reply, and then *stops*. The activation record
returned on success is never applied to the device, so the probe is read-only.

Three outcomes matter:

    CLEAN         server accepted the request, no lock challenge
    ICLOUD_LOCK   server asked for an Apple account (activation lock)
    MDM_LOCK      server replied with remote management

Everything else is reported as PENDING_ERASE or UNDETERMINED rather than being
guessed. A device that is already activated cannot be judged without erasing
it, and a network error is not evidence of a clean device.

Compliance: uses only the public activation service and the public activation
endpoints. No bypass, no credential submission, no private entitlement.
"""

from __future__ import annotations

import asyncio
import plistlib
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, Optional

ACTIVATION_SCHEMA_VERSION = "1.0"


class LockVerdict(str, Enum):
    """What Apple's activation server said about this device."""

    CLEAN = "clean"
    ICLOUD_LOCK = "icloud_lock"
    MDM_LOCK = "mdm_lock"
    PENDING_ERASE = "pending_erase"
    UNDETERMINED = "undetermined"


@dataclass
class ActivationProbe:
    """Result of one activation probe."""

    verdict: LockVerdict
    activation_state: Optional[str] = None
    masked_account: Optional[str] = None
    organization: Optional[str] = None
    server_title: Optional[str] = None
    server_message: Optional[str] = None
    error: Optional[str] = None
    checked_at: str = ""

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = datetime.now(UTC).isoformat()

    @property
    def passed(self) -> bool:
        """Only a server-confirmed clean device passes."""
        return self.verdict is LockVerdict.CLEAN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": ACTIVATION_SCHEMA_VERSION,
            "verdict": self.verdict.value,
            "passed": self.passed,
            "activation_state": self.activation_state,
            "masked_account": self.masked_account,
            "organization": self.organization,
            "server_title": self.server_title,
            "server_message": self.server_message,
            "error": self.error,
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------- #
# Response classification                                          #
# ---------------------------------------------------------------- #

# The server masks the account itself (``d•••••@6•••••.com``), so the pattern
# has to accept the bullet characters it uses for redaction.
_ACCOUNT_RE = re.compile(r"[A-Za-z0-9._%+\-•*]+@[A-Za-z0-9.\-•*]+\.[A-Za-z]{2,}")

_MDM_HINTS = (
    "remote management",
    "device management",
    "managed by",
    "远程管理",
    "设备管理",
    "受管理",
)

_LOCK_HINTS = (
    "activation lock",
    "apple account",
    "物主锁定",
    "linked to an apple account",
)

_GENERIC_MDM_TITLES = {"remote management", "device management", "mdm"}


def _parse_buddyml(content: bytes) -> tuple[Optional[str], Optional[str], str]:
    """Extract title/description from a BuddyML activation form."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None, None, content.decode("utf-8", "replace")

    navigation = root.find("page/navigationBar")
    title = navigation.get("title") if navigation is not None else None

    footer = root.find("page/tableView/section/footer")
    description = footer.text.strip() if footer is not None and footer.text else None

    all_text = " ".join(t.strip() for t in root.itertext() if t and t.strip())
    return title, description, all_text


def _extract_account(text: str) -> Optional[str]:
    match = _ACCOUNT_RE.search(text or "")
    return match.group(0) if match else None


def _extract_organization(
    title: Optional[str], description: Optional[str]
) -> Optional[str]:
    match = re.search(r"managed by\s+([^.;\n]+)", description or "", re.IGNORECASE)
    if match:
        return match.group(1).strip()
    if title and title.strip().lower() not in _GENERIC_MDM_TITLES:
        return title.strip()
    return None


def classify_activation_response(
    content_type: str,
    content: bytes,
    activation_state: Optional[str] = None,
) -> ActivationProbe:
    """Turn an activation server reply into a verdict.

    ``application/x-buddyml`` is a challenge form: the server wants something
    from the user. ``text/xml`` is an activation record, meaning it accepted the
    request. Anything else is reported as undetermined rather than guessed.
    """
    content_type = (content_type or "").lower()

    if "buddyml" in content_type:
        title, description, all_text = _parse_buddyml(content)
        haystack = f"{title or ''} {description or ''} {all_text}".lower()
        account = _extract_account(f"{description or ''} {all_text}")

        if "activation lock" in haystack or "物主锁定" in haystack:
            return ActivationProbe(
                LockVerdict.ICLOUD_LOCK,
                activation_state=activation_state,
                masked_account=account,
                server_title=title,
                server_message=description,
            )

        if any(hint in haystack for hint in _MDM_HINTS):
            return ActivationProbe(
                LockVerdict.MDM_LOCK,
                activation_state=activation_state,
                organization=_extract_organization(title, description),
                server_title=title,
                server_message=description,
            )

        if any(hint in haystack for hint in _LOCK_HINTS):
            return ActivationProbe(
                LockVerdict.ICLOUD_LOCK,
                activation_state=activation_state,
                masked_account=account,
                server_title=title,
                server_message=description,
            )

        return ActivationProbe(
            LockVerdict.UNDETERMINED,
            activation_state=activation_state,
            server_title=title,
            server_message=description,
            error="Unrecognized activation challenge form",
        )

    if "xml" in content_type:
        return ActivationProbe(
            LockVerdict.CLEAN,
            activation_state=activation_state,
            server_message="Activation server accepted the request; no lock challenge returned",
        )

    if not content_type:
        return ActivationProbe(
            LockVerdict.UNDETERMINED,
            activation_state=activation_state,
            error="Activation response carried no Content-Type",
        )

    return ActivationProbe(
        LockVerdict.UNDETERMINED,
        activation_state=activation_state,
        error=f"Unexpected activation Content-Type: {content_type}",
    )


# ---------------------------------------------------------------- #
# Probe                                                            #
# ---------------------------------------------------------------- #

async def probe_activation_lock(udid: str) -> ActivationProbe:
    """Ask Apple's activation server whether ``udid`` may activate.

    Read-only in the sense that matters: the returned activation record is
    inspected but never applied, and no Apple ID credentials are ever sent.
    """
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.mobile_activation import (
            ACTIVATION_DEFAULT_URL,
            ACTIVATION_DRM_HANDSHAKE_DEFAULT_URL,
            DEFAULT_HEADERS,
            MobileActivationService,
        )
    except ImportError as exc:  # pragma: no cover - dependency guard
        return ActivationProbe(
            LockVerdict.UNDETERMINED, error=f"pymobiledevice3 unavailable: {exc}"
        )

    try:
        lockdown = await create_using_usbmux(serial=udid)
        service = MobileActivationService(lockdown)

        state = await service.state()
        if state != "Unactivated":
            # An in-system device tells us nothing: the half-cleaned case
            # (signed out of iCloud but Find My still on) looks identical to
            # a clean one until it is erased.
            return ActivationProbe(
                LockVerdict.PENDING_ERASE,
                activation_state=state,
                server_message=(
                    "Device is already activated. Activation lock can only be "
                    "verified after erasing and re-probing in Setup Assistant."
                ),
            )

        session_info = await service.create_activation_session_info()
        headers: Dict[str, Any] = {"Content-Type": "application/x-apple-plist"}
        headers.update(DEFAULT_HEADERS)
        handshake, _ = service.post(
            ACTIVATION_DRM_HANDSHAKE_DEFAULT_URL,
            data=plistlib.dumps(session_info),
            headers=headers,
        )
        activation_info = await service.create_activation_info_with_session(handshake)

        content, response_headers = service.post(
            ACTIVATION_DEFAULT_URL,
            data={"activation-info": plistlib.dumps(activation_info)},
        )
        content_type = ""
        if response_headers is not None:
            content_type = response_headers.get("Content-Type", "") or ""

        return classify_activation_response(content_type, content, activation_state=state)

    except Exception as exc:
        return ActivationProbe(LockVerdict.UNDETERMINED, error=str(exc))


# ---------------------------------------------------------------- #
# Post-erase verification                                          #
# ---------------------------------------------------------------- #

VERIFY_SCHEMA_VERSION = "1.0"

# Verdicts that end polling: no amount of waiting changes them.
_DECISIVE = frozenset(
    {LockVerdict.CLEAN, LockVerdict.ICLOUD_LOCK, LockVerdict.MDM_LOCK}
)

_EXIT_CODES = {
    LockVerdict.CLEAN: 0,
    LockVerdict.ICLOUD_LOCK: 1,
    LockVerdict.MDM_LOCK: 1,
    LockVerdict.PENDING_ERASE: 2,
    LockVerdict.UNDETERMINED: 2,
}


@dataclass
class VerifyResult:
    """Outcome of a post-erase verification run."""

    udid: str
    probe: ActivationProbe
    attempts: int = 1
    waited_seconds: float = 0.0

    @property
    def verdict(self) -> LockVerdict:
        return self.probe.verdict

    @property
    def passed(self) -> bool:
        return self.probe.verdict is LockVerdict.CLEAN

    @property
    def exit_code(self) -> int:
        return _EXIT_CODES[self.probe.verdict]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": VERIFY_SCHEMA_VERSION,
            "udid": self.udid,
            "verified": self.passed,
            "verdict": self.probe.verdict.value,
            "exit_code": self.exit_code,
            "attempts": self.attempts,
            "waited_seconds": round(self.waited_seconds, 1),
            "probe": self.probe.to_dict(),
        }


async def verify_device(
    udid: str,
    timeout: float = 0.0,
    interval: float = 5.0,
    probe: Any = None,
    sleep: Any = None,
    clock: Any = None,
) -> VerifyResult:
    """Verify that an erased device will activate.

    Run this **after** the erase: the device reboots into Setup Assistant and
    the probe gets a definitive answer from Apple. With ``timeout > 0`` it keeps
    polling until the device comes back or a decisive verdict arrives, which is
    what you want when erasing and verifying in one sitting.

    ``timeout=0`` performs a single probe.
    """
    probe_fn = probe or probe_activation_lock
    sleep_fn = sleep or asyncio.sleep
    now = clock or time.monotonic

    start = now()
    attempts = 0

    while True:
        result = await probe_fn(udid)
        attempts += 1
        if result.verdict in _DECISIVE:
            break
        elapsed = now() - start
        if elapsed >= timeout:
            break
        delay = min(interval, timeout - elapsed) if interval > 0 else 0
        await sleep_fn(delay)

    return VerifyResult(
        udid=udid,
        probe=result,
        attempts=attempts,
        waited_seconds=max(now() - start, 0.0),
    )


def format_verify_text(result: VerifyResult) -> str:
    """Render a verification result for a human operator."""
    probe = result.probe
    verdict = probe.verdict

    headline = {
        LockVerdict.CLEAN: "PASSED - this device will activate",
        LockVerdict.ICLOUD_LOCK: "BLOCKED - iCloud Activation Lock",
        LockVerdict.MDM_LOCK: "BLOCKED - MDM Remote Management",
        LockVerdict.PENDING_ERASE: "NOT VERIFIED - device is still activated",
        LockVerdict.UNDETERMINED: "NOT VERIFIED - could not reach the activation server",
    }[verdict]

    lines = [
        "",
        "=" * 60,
        f"VERIFICATION: {headline}",
        "=" * 60,
        f"  Device: {result.udid}",
        f"  Verdict: {verdict.value}",
    ]
    if probe.activation_state:
        lines.append(f"  Activation state: {probe.activation_state}")
    if probe.masked_account:
        lines.append(f"  Linked Apple account: {probe.masked_account}")
    if probe.organization:
        lines.append(f"  Organization: {probe.organization}")
    if probe.server_title:
        lines.append(f"  Server title: {probe.server_title}")
    if probe.server_message:
        lines.append(f'  Server: "{probe.server_message}"')
    if probe.error:
        lines.append(f"  Error: {probe.error}")
    lines.append(f"  Probes: {result.attempts}  Waited: {result.waited_seconds:.1f}s")

    if verdict is LockVerdict.CLEAN:
        lines.append("  Result: safe to hand over / confirm receipt.")
    elif verdict is LockVerdict.ICLOUD_LOCK:
        lines.append("  Result: do not erase again; it ends on the same screen.")
        lines.append("  Release: account holder signs out, or Apple with a purchase receipt.")
    elif verdict is LockVerdict.MDM_LOCK:
        lines.append("  Result: do not erase again; erasing does not remove MDM.")
        lines.append("  Release: only the owning organization can release it.")
    elif verdict is LockVerdict.PENDING_ERASE:
        lines.append("  Result: erase the device first, then re-run verify --wait 300.")
    else:
        lines.append("  Result: treat as unverified. Retry on a stable connection.")

    lines.append("=" * 60)
    return "\n".join(lines)
