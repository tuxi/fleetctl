"""
Test that all fleetctl python-core modules can be imported correctly.
"""

import pytest


def test_import_device_detector():
    from fleetctl.device_detector import (
        DeviceDetector,
        DeviceReport,
        DeviceIdentity,
        DeviceStatus,
        DeviceResources,
        ChipDetector,
        DeviceClassifier,
        decide_strategy,
        get_device_info_from_pymobiledevice3,
        parse_ios_version,
        get_chip_from_board_id,
        get_chip_generation,
        BOARD_ID_TO_CHIP,
        HARDWARE_PLATFORM_TO_CHIP,
        RestoreStrategy,
        StrategyResult,
        DeviceInfo,
    )
    assert DeviceDetector is not None


def test_import_backup_parser():
    from fleetctl.backup_parser import (
        BackupParser,
        BackupSummary,
        BackupManifest,
        BackupInfo,
        BackupStatus,
        AppInfo,
        ManifestDBParser,
        parse_backup,
        open_manifest_db,
    )
    assert BackupParser is not None


def test_import_device_info():
    from fleetctl.device_info import (
        DeviceInfoCollector,
        DeviceReport,
        DeviceIdentity,
        DeviceStatus,
        DeviceResources,
        get_device_info_from_pymobiledevice3,
        parse_ios_version,
        get_chip_from_board_id,
        get_chip_generation,
        BOARD_ID_TO_CHIP,
        HARDWARE_PLATFORM_TO_CHIP,
    )
    assert DeviceInfoCollector is not None


def test_import_config_writer():
    from fleetctl.config_writer import (
        ConfigWriter,
        CloudConfiguration,
        ConfigurationResult,
        SkipSetupOptions,
        create_enterprise_config,
        create_skip_setup_config,
        ConfigurationSource,
    )
    assert ConfigWriter is not None


def test_import_wipe_manager():
    from fleetctl.wipe_manager import (
        WipeManager,
        WipeOptions,
        WipeResult,
        WipeMethod,
        WipeCertificate,
        quick_wipe,
        full_wipe_with_certificate,
    )
    assert WipeManager is not None


def test_import_report_generator():
    from fleetctl.report_generator import (
        ReportGenerator,
        JSONReportGenerator,
        CSVReportGenerator,
        HTMLReportGenerator,
        PDFReportGenerator,
        ReportGeneratorFactory,
        ReportConfig,
        generate_device_report,
    )
    assert ReportGenerator is not None


def test_import_usb_manager():
    from fleetctl.usb_manager import (
        USBDeviceManager,
        BulkOperationManager,
        DeviceFilter,
        DeviceConnection,
        DeviceConnectionState,
        create_device_manager,
    )
    assert USBDeviceManager is not None


def test_import_license():
    from fleetctl.license import (
        DeviceFingerprint,
        DeviceNotBoundError,
        KeyPair,
        License,
        LicenseError,
        LicenseExpiredError,
        LicenseFeatures,
        LicenseInvalidError,
        LicenseRevokedError,
        LicenseSigner,
        LicenseStatus,
        LicenseVerifier,
    )
    assert License() is not None
    assert LicenseStatus.VALID.value == "valid"
    assert KeyPair is not None
    assert DeviceFingerprint is not None


def test_import_all():
    """Test that all modules can be imported together."""
    import fleetctl
    assert fleetctl is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])