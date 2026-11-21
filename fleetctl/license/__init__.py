"""
License management module for fleetctl.

Provides license generation, activation, verification, and revocation
with cryptographic signing (Ed25519/RSA) and device binding.
"""

from .models import (
    DeviceFingerprint,
    DeviceNotBoundError,
    License,
    LicenseError,
    LicenseExpiredError,
    LicenseFeatures,
    LicenseInvalidError,
    LicenseRevokedError,
    LicenseStatus,
)
from .crypto import KeyPair, LicenseSigner, LicenseVerifier

__all__ = [
    "DeviceFingerprint",
    "DeviceNotBoundError",
    "License",
    "LicenseError",
    "LicenseExpiredError",
    "LicenseFeatures",
    "LicenseInvalidError",
    "LicenseRevokedError",
    "LicenseStatus",
    "KeyPair",
    "LicenseSigner",
    "LicenseVerifier",
]