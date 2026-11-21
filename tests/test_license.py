"""
Tests for the license data models.

These guard the surviving definition of each class: models.py previously
defined LicenseStatus, LicenseFeatures, DeviceFingerprint and
LicenseRevokedError twice, and the later definition silently won.
"""

import pytest

from fleetctl.license.models import (
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


class TestLicenseStatus:
    def test_is_enum_with_grace_period(self):
        assert LicenseStatus.VALID.value == "valid"
        # GRACE_PERIOD only exists in the definition that used to be overridden.
        assert LicenseStatus.GRACE_PERIOD.value == "grace_period"

    def test_all_members(self):
        assert {s.value for s in LicenseStatus} == {
            "valid", "expired", "revoked", "invalid", "pending", "grace_period",
        }


class TestLicenseFeatures:
    def test_is_a_dataclass_wrapping_strings(self):
        features = LicenseFeatures(features={"device_wipe"})
        assert features.has("device_wipe") is True
        assert features.has("rbac") is False
        assert features.to_list() == ["device_wipe"]

    def test_default_set(self):
        features = LicenseFeatures.default()
        assert len(features.to_list()) == 6
        assert features.has("device_precheck")

    def test_enterprise_is_a_superset(self):
        enterprise = LicenseFeatures.enterprise()
        assert set(enterprise.to_list()) >= set(LicenseFeatures.default().to_list())
        assert enterprise.has("mdm_integration")
        assert len(enterprise.to_list()) == 14

    def test_accepts_list(self):
        assert LicenseFeatures(features=["a", "b"]).to_list() == ["a", "b"]


class TestDeviceFingerprint:
    def test_constructible_with_no_arguments(self):
        # The overridden definition required every field.
        assert DeviceFingerprint().udid == ""

    def test_matches_on_udid(self):
        a = DeviceFingerprint(udid="udid-1")
        b = DeviceFingerprint(udid="udid-1")
        assert a.matches(b) is True

    def test_matches_on_serial(self):
        a = DeviceFingerprint(serial_number="SN1")
        b = DeviceFingerprint(serial_number="SN1")
        assert a.matches(b) is True

    def test_dict_round_trip(self):
        fp = DeviceFingerprint(udid="udid-1", serial_number="SN1")
        assert DeviceFingerprint.from_dict(fp.to_dict()).udid == "udid-1"

    def test_blank_fingerprints_do_not_match(self):
        assert DeviceFingerprint().matches(DeviceFingerprint()) is False

    def test_different_udids_without_hardware_do_not_match(self):
        assert DeviceFingerprint(udid="u1").matches(DeviceFingerprint(udid="u2")) is False

    def test_matching_hardware_matches(self):
        a = DeviceFingerprint(
            product_type="iPhone16,1", hardware_model="D83AP", cpu_architecture="arm64e"
        )
        b = DeviceFingerprint(
            product_type="iPhone16,1", hardware_model="D83AP", cpu_architecture="arm64e"
        )
        assert a.matches(b) is True

    def test_differing_hardware_does_not_match(self):
        a = DeviceFingerprint(
            product_type="iPhone15,2", hardware_model="D63AP", cpu_architecture="arm64e"
        )
        b = DeviceFingerprint(
            product_type="iPhone16,1", hardware_model="D83AP", cpu_architecture="arm64e"
        )
        assert a.matches(b) is False


class TestLicense:
    def test_trial_is_valid(self):
        license_ = License.create_trial("ACME", days=30)
        assert license_.is_valid() is True
        assert license_.days_until_expiry() == 30

    def test_enterprise_features(self):
        license_ = License.create_enterprise("ACME")
        assert license_.features.has("mdm_integration") is True

    def test_revoke(self):
        license_ = License.create_trial("ACME")
        license_.revoke("chargeback")
        assert license_.is_valid() is False
        assert license_.status == "revoked"

    def test_json_round_trip(self):
        license_ = License.create_trial("ACME")
        restored = License.from_json(license_.to_json())
        assert restored.organization == "ACME"
        assert restored.features.to_list() == license_.features.to_list()


class TestDeviceBinding:
    def test_bind_same_device_twice_does_not_raise(self):
        license_ = License.create_trial("ACME")
        license_.max_device_bindings = 5
        device = DeviceFingerprint(udid="udid-1")

        assert license_.bind_device(device) is True
        # Used to raise TypeError: DeviceFingerprint(**device_fingerprint)
        assert license_.bind_device(device) is True
        assert len(license_.bound_devices) == 1

    def test_is_bound_after_binding(self):
        license_ = License.create_trial("ACME")
        license_.max_device_bindings = 5
        license_.bind_device(DeviceFingerprint(udid="udid-1"))
        assert license_.is_bound_to_device(DeviceFingerprint(udid="udid-1")) is True

    def test_not_bound_before_any_binding(self):
        license_ = License.create_trial("ACME")
        assert license_.is_bound_to_device(DeviceFingerprint(udid="udid-1")) is False

    def test_respects_max_device_bindings(self):
        license_ = License.create_trial("ACME")
        license_.max_device_bindings = 1
        assert license_.bind_device(DeviceFingerprint(udid="a")) is True
        assert license_.bind_device(DeviceFingerprint(udid="b")) is False

    def test_distinct_udids_bind_separately(self):
        license_ = License.create_trial("ACME")
        license_.max_device_bindings = 5
        license_.bind_device(DeviceFingerprint(udid="a"))
        license_.bind_device(DeviceFingerprint(udid="b"))
        assert len(license_.bound_devices) == 2


class TestErrors:
    @pytest.mark.parametrize(
        "error",
        [LicenseExpiredError, LicenseRevokedError, LicenseInvalidError, DeviceNotBoundError],
    )
    def test_subclasses(self, error):
        assert issubclass(error, LicenseError)
