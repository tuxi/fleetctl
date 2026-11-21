"""
License data models.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid


class LicenseStatus(str, Enum):
    """License status enumeration."""
    VALID = "valid"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INVALID = "invalid"
    PENDING = "pending"
    GRACE_PERIOD = "grace_period"


@dataclass
class LicenseFeatures:
    """License feature set."""
    features: Set[str] = field(default_factory=set)

    def __post_init__(self):
        if isinstance(self.features, list):
            self.features = set(self.features)

    def has(self, feature: str) -> bool:
        return feature in self.features

    def add(self, feature: str) -> "LicenseFeatures":
        self.features.add(feature)
        return self

    def remove(self, feature: str) -> "LicenseFeatures":
        self.features.discard(feature)
        return self

    def to_list(self) -> List[str]:
        return sorted(self.features)

    @classmethod
    def default(cls) -> "LicenseFeatures":
        return cls(features={
            "device_management",
            "device_wipe",
            "device_precheck",
            "report_generation",
            "backup_parsing",
            "config_writing",
        })

    @classmethod
    def enterprise(cls) -> "LicenseFeatures":
        return cls(features={
            "device_management",
            "device_wipe",
            "device_precheck",
            "report_generation",
            "backup_parsing",
            "config_writing",
            "mdm_integration",
            "bulk_operations",
            "adaptive_concurrency",
            "checkpoint_resume",
            "audit_logging",
            "compliance_reports",
            "siem_integration",
            "gdpr_compliance",
        })


@dataclass
class License:
    """License model with cryptographic signing."""
    # Core identification
    license_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: int = 1

    # License metadata
    issued_at: int = field(default_factory=lambda: int(time.time()))
    expires_at: Optional[int] = None
    grace_period_days: int = 7

    # Features and limits
    features: LicenseFeatures = field(default_factory=LicenseFeatures.default)
    max_devices: int = 100
    max_users: int = 10

    # Ownership
    organization: str = ""
    issued_to: str = ""
    issued_by: str = "fleetctl"

    # Device binding
    bound_devices: List[Dict] = field(default_factory=list)
    max_device_bindings: int = 1

    # Status
    status: str = "pending"
    revoked: bool = False
    revoked_at: Optional[int] = None
    revoked_reason: str = ""

    # Cryptographic
    signature: str = ""
    public_key: str = ""

    # Timestamps
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self):
        if isinstance(self.features, dict):
            self.features = LicenseFeatures(features=self.features)
        elif isinstance(self.features, list):
            self.features = LicenseFeatures(features=set(self.features))

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        # Convert enums to values
        data["features"] = self.features.to_list()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "License":
        """Create License from dictionary."""
        if "features" in data and isinstance(data["features"], list):
            data["features"] = LicenseFeatures(features=set(data["features"]))
        return cls(**data)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str) -> "License":
        """Create License from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def is_expired(self) -> bool:
        """Check if license is expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def is_valid(self) -> bool:
        """Check if license is currently valid."""
        if self.revoked:
            return False
        if self.is_expired():
            return False
        return True

    def days_until_expiry(self) -> Optional[int]:
        """Days until license expires."""
        if self.expires_at is None:
            return None
        remaining = self.expires_at - time.time()
        if remaining <= 0:
            return 0
        return int(remaining / 86400) + 1

    def is_in_grace_period(self) -> bool:
        """Check if in grace period after expiry."""
        if not self.is_expired():
            return False
        grace_end = self.expires_at + (self.grace_period_days * 86400)
        return time.time() < grace_end

    def is_bound_to_device(self, device_fingerprint: "DeviceFingerprint") -> bool:
        """Check if license is bound to a specific device."""
        if not self.bound_devices:
            return False
        for bound in self.bound_devices:
            fp = DeviceFingerprint.from_dict(bound)
            if fp.matches(device_fingerprint):
                return True
        return False

    def bind_device(self, device_fingerprint: "DeviceFingerprint") -> bool:
        """Bind license to a device."""
        if len(self.bound_devices) >= self.max_device_bindings:
            return False
        if not self.is_bound_to_device(device_fingerprint):
            self.bound_devices.append(device_fingerprint.to_dict())
            self.updated_at = int(time.time())
            return True
        return True

    def revoke(self, reason: str = "") -> None:
        """Revoke the license."""
        self.revoked = True
        self.revoked_at = int(time.time())
        self.revoked_reason = reason
        self.status = "revoked"
        self.updated_at = int(time.time())

    def renew(self, days: int = 365) -> None:
        """Renew license for additional days."""
        if self.expires_at and self.expires_at > time.time():
            self.expires_at += days * 86400
        else:
            self.expires_at = int(time.time()) + days * 86400
        self.status = "valid"
        self.revoked = False
        self.revoked_at = None
        self.revoked_reason = ""
        self.updated_at = int(time.time())

    def to_signed_dict(self, private_key: str) -> dict:
        """Create a signed dictionary representation."""
        data = self.to_dict()
        # Remove signature for signing
        data.pop("signature", None)
        return data

    @classmethod
    def create_trial(cls, organization: str, days: int = 30) -> "License":
        """Create a trial license."""
        return cls(
            organization=organization,
            expires_at=int(time.time()) + days * 86400,
            features=LicenseFeatures.default(),
            max_devices=5,
            max_users=5,
            status="valid",
        )

    @classmethod
    def create_enterprise(cls, organization: str, days: int = 365) -> "License":
        """Create an enterprise license."""
        return cls(
            organization=organization,
            expires_at=int(time.time()) + days * 86400,
            features=LicenseFeatures.enterprise(),
            max_devices=1000,
            max_users=100,
            status="valid",
        )


@dataclass
class DeviceFingerprint:
    """Device fingerprint for license binding."""
    udid: str = ""
    serial_number: str = ""
    product_type: str = ""
    hardware_model: str = ""
    cpu_architecture: str = ""
    mac_addresses: List[str] = field(default_factory=list)
    disk_serial: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "udid": self.udid,
            "serial_number": self.serial_number,
            "product_type": self.product_type,
            "hardware_model": self.hardware_model,
            "cpu_architecture": self.cpu_architecture,
            "mac_addresses": self.mac_addresses,
            "disk_serial": self.disk_serial,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceFingerprint":
        return cls(**data)

    def matches(self, other: "DeviceFingerprint", threshold: float = 0.8) -> bool:
        """Check if two fingerprints match above threshold."""
        if self.udid and other.udid and self.udid == other.udid:
            return True
        if self.serial_number and other.serial_number and self.serial_number == other.serial_number:
            return True

        matches = 0
        total = 0
        for attr in ["product_type", "hardware_model", "cpu_architecture"]:
            if getattr(self, attr) and getattr(other, attr):
                total += 1
                if getattr(self, attr) == getattr(other, attr):
                    matches += 1
        if total == 0:
            # Nothing comparable: refuse rather than treat two blank
            # fingerprints as the same device.
            return False
        return (matches / total) >= threshold


class LicenseError(Exception):
    """License-related errors."""
    pass


class LicenseExpiredError(LicenseError):
    """License has expired."""
    pass


class LicenseRevokedError(LicenseError):
    """License has been revoked."""
    pass


class LicenseInvalidError(LicenseError):
    """License is invalid."""
    pass


class DeviceNotBoundError(LicenseError):
    """Device not bound to license."""
    pass