"""
Tests for wipe_manager module.
"""

import json

import pytest
from fleetctl.wipe_manager import (
    WipeManager,
    WipeOptions,
    WipeResult,
    WipeMethod,
    WipeCertificate,
    quick_wipe,
    full_wipe_with_certificate,
)


class TestWipeOptions:
    """Tests for WipeOptions dataclass."""

    def test_default_options(self):
        options = WipeOptions()
        assert options.method == "full"
        assert options.preserve_data_plan is False
        assert options.disallow_proximity_setup is False
        assert options.verify_after is True
        assert options.generate_certificate is True
        assert options.certificate_fields == {}

    def test_custom_options(self):
        options = WipeOptions(
            method="quick",
            preserve_data_plan=True,
            disallow_proximity_setup=True,
            verify_after=False,
            generate_certificate=False,
            certificate_fields={"verifier": "test"},
        )
        assert options.method == "quick"
        assert options.preserve_data_plan is True
        assert options.disallow_proximity_setup is True
        assert options.verify_after is False
        assert options.generate_certificate is False
        assert options.certificate_fields == {"verifier": "test"}


class TestWipeMethod:
    """Tests for WipeMethod enum."""

    def test_methods(self):
        assert WipeMethod.QUICK == "quick"
        assert WipeMethod.FULL == "full"
        assert WipeMethod.NIST_800_88_CLEAR == "nist_clear"
        assert WipeMethod.NIST_800_88_PURGE == "nist_purge"
        assert WipeMethod.NIST_800_88_DESTROY == "nist_destroy"


class TestWipeResult:
    """Tests for WipeResult dataclass."""

    def test_success_result(self):
        result = WipeResult(
            success=True,
            method="full",
            udid="test-udid",
            message="Success",
            details={"key": "value"},
            certificate="cert-data",
        )
        assert result.success is True
        assert result.method == "full"
        assert result.udid == "test-udid"
        assert result.message == "Success"
        assert result.details == {"key": "value"}
        assert result.certificate == "cert-data"
        assert result.error_code is None

    def test_error_result(self):
        result = WipeResult(
            success=False,
            method="full",
            udid="test-udid",
            message="Failed",
            error_code="WIPE_FAILED",
            details={"error": "error details"},
        )
        assert result.success is False
        assert result.error_code == "WIPE_FAILED"
        assert result.details == {"error": "error details"}


class TestWipeManager:
    """Tests for WipeManager class."""

    @pytest.fixture
    def manager(self):
        return WipeManager()

    def test_manager_initialization(self, manager):
        assert manager is not None
        assert hasattr(manager, "_pymobiledevice3_available")

    def test_manager_available_property(self, manager):
        # available mirrors whether the hard dependency is importable
        import importlib.util
        expected = importlib.util.find_spec("pymobiledevice3") is not None
        assert manager.available is expected

    def test_wipe_method_enum(self):
        assert WipeMethod.QUICK == "quick"
        assert WipeMethod.FULL == "full"
        assert WipeMethod.NIST_800_88_CLEAR == "nist_clear"
        assert WipeMethod.NIST_800_88_PURGE == "nist_purge"
        assert WipeMethod.NIST_800_88_DESTROY == "nist_destroy"


def _sample_certificate():
    return WipeCertificate.build_certificate(
        udid="test-udid",
        serial_number="ABC123",
        product_type="iPhone15,2",
        product_version="17.4.1",
        method="full",
        started_at="2024-01-15T10:00:00Z",
        completed_at="2024-01-15T10:05:00Z",
        success=True,
        verifier="fleetctl",
    )


class TestWipeCertificate:
    """Tests for WipeCertificate class."""

    def test_generate_certificate(self):
        cert = json.loads(
            WipeCertificate.generate(
                udid="test-udid",
                serial_number="ABC123",
                product_type="iPhone15,2",
                product_version="17.4.1",
                method="full",
                started_at="2024-01-15T10:00:00Z",
                completed_at="2024-01-15T10:05:00Z",
                success=True,
                verifier="fleetctl",
            )
        )
        assert cert["certificate_version"] == "1.0"
        assert cert["standard"] == "NIST SP 800-88 Rev. 1"
        assert cert["wipe_method"] == "full"
        assert cert["device"]["udid"] == "test-udid"
        assert cert["device"]["serial_number"] == "ABC123"
        assert cert["device"]["product_type"] == "iPhone15,2"
        assert cert["device"]["ios_version"] == "17.4.1"
        assert cert["result"] == "success"
        assert cert["verifier"] == "fleetctl"
        assert "certificate_id" in cert
        assert cert["hash_algorithm"] == "SHA-256"

    def test_generate_hash(self):
        hash_val = WipeCertificate.generate_hash("test data")
        assert len(hash_val) == 64  # SHA-256 hex length
        assert all(c in "0123456789abcdef" for c in hash_val)

    def test_build_certificate_structure(self):
        cert = _sample_certificate()
        assert set(cert) >= {
            "certificate_version", "standard", "wipe_method", "device",
            "timestamps", "result", "verifier", "certificate_id", "hash_algorithm",
        }
        assert cert["device"]["ios_version"] == "17.4.1"

    def test_generate_pdf_returns_pdf_bytes(self):
        pytest.importorskip("reportlab")
        pdf = WipeCertificate.generate_pdf(_sample_certificate())
        assert isinstance(pdf, bytes)
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 1000

    def test_generate_pdf_accepts_json_string(self):
        pytest.importorskip("reportlab")
        cert_json = WipeCertificate.generate(
            udid="u", serial_number="S", product_type="iPhone15,2",
            product_version="17.4.1", method="full",
            started_at="t0", completed_at="t1", success=True,
        )
        pdf = WipeCertificate.generate_pdf(cert_json)
        assert pdf.startswith(b"%PDF")

    def test_generate_pdf_failed_result(self):
        pytest.importorskip("reportlab")
        cert = _sample_certificate()
        cert["result"] = "failed"
        pdf = WipeCertificate.generate_pdf(cert, organization="ACME")
        assert pdf.startswith(b"%PDF")

    def test_write_json(self, tmp_path):
        out = tmp_path / "cert.json"
        WipeCertificate.write(_sample_certificate(), out, "json")
        data = json.loads(out.read_text())
        assert data["device"]["udid"] == "test-udid"

    def test_write_pdf(self, tmp_path):
        pytest.importorskip("reportlab")
        out = tmp_path / "cert.pdf"
        WipeCertificate.write(_sample_certificate(), out, "pdf")
        assert out.read_bytes().startswith(b"%PDF")

    def test_write_invalid_format(self, tmp_path):
        with pytest.raises(ValueError):
            WipeCertificate.write(_sample_certificate(), tmp_path / "x", "xml")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
