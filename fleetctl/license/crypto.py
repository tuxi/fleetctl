"""
Cryptographic operations for license management.

Supports Ed25519 (recommended) and RSA-2048 for license signing/verification.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional, Tuple, Union

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa, ed448, padding
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)
from cryptography.exceptions import InvalidSignature


@dataclass(frozen=True)
class KeyPair:
    """Asymmetric key pair for license signing/verification."""

    private_key: bytes  # PEM-encoded private key
    public_key: bytes   # PEM-encoded public key
    algorithm: str      # "ed25519" or "rsa-2048"

    @classmethod
    def generate(cls, algorithm: str = "ed25519") -> "KeyPair":
        """Generate a new key pair."""
        if algorithm == "ed25519":
            private_key = ed25519.Ed25519PrivateKey.generate()
            public_key = private_key.public_key()
        elif algorithm == "rsa-2048":
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )
            public_key = private_key.public_key()
        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return cls(
            private_key=private_pem,
            public_key=public_pem,
            algorithm=algorithm,
        )

    @classmethod
    def load_private(cls, pem: bytes, password: Optional[bytes] = None) -> "KeyPair":
        """Load a key pair from PEM-encoded private key."""
        private_key = serialization.load_pem_private_key(pem, password=password)
        public_key = private_key.public_key()

        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        # Determine algorithm from key type
        if isinstance(private_key, ed25519.Ed25519PrivateKey):
            algorithm = "ed25519"
        elif isinstance(private_key, rsa.RSAPrivateKey):
            algorithm = "rsa-2048"
        else:
            raise ValueError("Unsupported key type")

        return cls(
            private_key=private_pem,
            public_key=public_pem,
            algorithm=algorithm,
        )

    @classmethod
    def load_public(cls, pem: bytes) -> "KeyPair":
        """Load a public key only (for verification)."""
        public_key = serialization.load_pem_public_key(pem)

        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        if isinstance(public_key, ed25519.Ed25519PublicKey):
            algorithm = "ed25519"
        elif isinstance(public_key, rsa.RSAPublicKey):
            algorithm = "rsa-2048"
        else:
            raise ValueError("Unsupported key type")

        return cls(
            private_key=b"",  # No private key
            public_key=public_pem,
            algorithm=algorithm,
        )

    def sign(self, data: bytes) -> bytes:
        """Sign data with the private key."""
        if not self.private_key:
            raise ValueError("No private key available for signing")

        private_key = serialization.load_pem_private_key(self.private_key, password=None)

        if self.algorithm == "ed25519":
            signature = private_key.sign(data)
        elif self.algorithm == "rsa-2048":
            signature = private_key.sign(
                data,
                padding=serialization.padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                algorithm=hashes.SHA256(),
            )
        else:
            raise ValueError(f"Unsupported algorithm: {self.algorithm}")

        return signature

    def verify(self, data: bytes, signature: bytes) -> bool:
        """Verify a signature against the public key."""
        public_key = serialization.load_pem_public_key(self.public_key)

        try:
            if self.algorithm == "ed25519":
                public_key.verify(signature, data)
            elif self.algorithm == "rsa-2048":
                public_key.verify(
                    signature,
                    data,
                    padding=padding.PSS(
                        mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH,
                    ),
                    algorithm=hashes.SHA256(),
                )
            else:
                raise ValueError(f"Unsupported algorithm: {self.algorithm}")
            return True
        except InvalidSignature:
            return False

    def public_key_b64(self) -> str:
        """Return public key as base64-encoded PEM."""
        return base64.b64encode(self.public_key).decode("ascii")

    def private_key_b64(self) -> str:
        """Return private key as base64-encoded PEM."""
        return base64.b64encode(self.private_key).decode("ascii")


class LicenseSigner:
    """Signs license data with a private key."""

    def __init__(self, keypair: KeyPair):
        self.keypair = keypair

    def sign_license(self, license_data: dict) -> str:
        """Sign license data and return base64-encoded signature."""
        # Create canonical representation for signing
        import json
        canonical = json.dumps(license_data, sort_keys=True, separators=(",", ":")).encode()
        signature = self.keypair.sign(canonical)
        return base64.b64encode(signature).decode("ascii")


class LicenseVerifier:
    """Verifies license signatures with a public key."""

    def __init__(self, keypair: KeyPair):
        self.keypair = keypair

    def verify_license(self, license_data: dict, signature_b64: str) -> bool:
        """Verify a license signature."""
        import json
        canonical = json.dumps(license_data, sort_keys=True, separators=(",", ":")).encode()
        signature = base64.b64decode(signature_b64)
        return self.keypair.verify(canonical, signature)


def generate_device_fingerprint() -> str:
    """Generate a device fingerprint for binding."""
    import uuid
    import platform
    import hashlib

    # Collect system identifiers
    identifiers = [
        platform.node(),           # hostname
        platform.machine(),        # architecture
        platform.processor(),      # processor
        platform.platform(),       # platform string
    ]

    # Add MAC addresses if available
    try:
        import uuid as uuid_module
        mac = uuid_module.getnode()
        identifiers.append(f"mac:{mac:012x}")
    except Exception:
        pass

    # Create deterministic fingerprint
    data = "|".join(filter(None, identifiers)).encode()
    return hashlib.sha256(data).hexdigest()[:32]


def encrypt_data(data: bytes, key: bytes) -> bytes:
    """Encrypt data with AES-256-GCM."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext


def decrypt_data(encrypted: bytes, key: bytes) -> bytes:
    """Decrypt data with AES-256-GCM."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    aesgcm = AESGCM(key)
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]
    return aesgcm.decrypt(nonce, ciphertext, None)


def derive_key(password: str, salt: bytes) -> bytes:
    """Derive encryption key from password using PBKDF2."""
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return kdf.derive(password.encode())