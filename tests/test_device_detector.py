"""
Tests for device_detector module.
"""

import pytest
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


class TestParseIOSVersion:
    """Tests for parse_ios_version function."""
    
    def test_valid_versions(self):
        assert parse_ios_version("17.4.1") == (17, 4, 1)
        assert parse_ios_version("18.0") == (18, 0, 0)
        assert parse_ios_version("16.7.1") == (16, 7, 1)
        assert parse_ios_version("26.0") == (26, 0, 0)
        assert parse_ios_version("27.0.1") == (27, 0, 1)
    
    def test_invalid_versions(self):
        assert parse_ios_version("invalid") == (0, 0, 0)
        assert parse_ios_version("") == (0, 0, 0)
        assert parse_ios_version("17") == (17, 0, 0)
        assert parse_ios_version("17.4") == (17, 4, 0)


class TestChipDetection:
    """Tests for chip detection."""
    
    def test_board_id_to_chip(self):
        assert get_chip_from_board_id("D321AP") == "A12"
        assert get_chip_from_board_id("D621AP") == "A15"
        assert get_chip_from_board_id("D94AP") == "A18"
        assert get_chip_from_board_id("D20AP") == "A11"
        assert get_chip_from_board_id("UNKNOWN") is None
    
    def test_hardware_platform_to_chip(self):
        from fleetctl.device_detector import HARDWARE_PLATFORM_TO_CHIP
        assert HARDWARE_PLATFORM_TO_CHIP["t8101"] == "A13"
        assert HARDWARE_PLATFORM_TO_CHIP["t8150"] == "A18"
        assert HARDWARE_PLATFORM_TO_CHIP["t6040"] == "M4"
        assert HARDWARE_PLATFORM_TO_CHIP["unknown"] is None
    
    def test_chip_generation(self):
        assert get_chip_generation("A12") == 12
        assert get_chip_generation("A17 Pro") == 17
        assert get_chip_generation("M1") == 101
        assert get_chip_generation("M2") == 102
        assert get_chip_generation("M4") == 104
        assert get_chip_generation("Unknown") == 0


class TestDeviceClassifier:
    """Tests for device classification."""
    
    def test_classify_iphone(self):
        assert DeviceClassifier.classify("iPhone15,2") == "iPhone"
        assert DeviceClassifier.classify("iPhone13,3") == "iPhone"
    
    def test_classify_ipad(self):
        assert DeviceClassifier.classify("iPad13,8") == "iPad"
        assert DeviceClassifier.classify("iPad14,1") == "iPad"
    
    def test_classify_other(self):
        assert DeviceClassifier.classify("iPod9,1") == "iPod touch"
        assert DeviceClassifier.classify("AppleTV6,2") == "Apple TV"
        assert DeviceClassifier.classify("Watch6,1") == "Apple Watch"
        assert DeviceClassifier.classify("Unknown") == "Unknown"


class TestDecideStrategy:
    """Tests for strategy decision (compliant mode returns unsupported)."""
    
    def test_all_unsupported_in_compliant_mode(self):
        from fleetctl.device_detector import DeviceInfo
        
        test_cases = [
            ("A11", "15.5"),
            ("A12", "17.4.1"),
            ("A15", "18.1"),
            ("A15", "18.2"),
            ("A15", "26.1"),
            ("A15", "26.2"),
            ("A15", "16.6"),
            ("A18", "18.0"),
        ]
        
        for chip, ios in test_cases:
            info = DeviceInfo(chip=chip, ios_version=ios, board_id="", udid="test")
            result = decide_strategy(info)
            assert result["supported"] is False
            assert result["strategy"] == "unsupported"


class TestDeviceDetector:
    """Tests for DeviceDetector class."""
    
    @pytest.fixture
    def detector(self):
        return DeviceDetector()
    
    def test_detector_initialization(self, detector):
        assert detector is not None
        assert hasattr(detector, '_pymobiledevice3_available')
    
    def test_mock_report(self, detector):
        report = detector._mock_report("test-udid")
        assert report.udid == "test-udid"
        assert report.chip == "A16"
        assert report.ios_version == "17.4.1"


class TestDataClasses:
    """Tests for data classes."""
    
    def test_device_identity(self):
        identity = DeviceIdentity(
            udid="test-udid",
            serial_number="ABC123",
            product_type="iPhone15,2",
            product_version="17.4.1",
        )
        assert identity.udid == "test-udid"
        assert identity.serial_number == "ABC123"
    
    def test_device_report(self):
        report = DeviceReport(
            udid="test-udid",
            chip="A16",
            ios_version="17.4.1",
        )
        assert report.udid == "test-udid"
        assert report.chip == "A16"
        assert report.ios_version == "17.4.1"
    
    def test_device_report_to_dict(self):
        report = DeviceReport(
            udid="test-udid",
            chip="A16",
            ios_version="17.4.1",
        )
        d = report.to_dict()
        assert d["identity"]["udid"] == "test-udid"
        assert d["metadata"]["chip"] == "A16"
        assert d["metadata"]["ios_version"] == "17.4.1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])