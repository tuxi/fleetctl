"""
Tests for device_info module.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import pymobiledevice3.services.diagnostics
import pymobiledevice3.services.mobile_config
import pymobiledevice3.lockdown
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


class TestDeviceInfoCollector:
    """Tests for DeviceInfoCollector class."""
    
    @pytest.fixture
    def collector(self):
        return DeviceInfoCollector()
    
    def test_collector_initialization(self, collector):
        assert collector is not None
        assert hasattr(collector, '_pymobiledevice3_available')
    
    def test_collector_available_property(self, collector):
        # available mirrors whether the hard dependency is importable
        import importlib.util
        expected = importlib.util.find_spec("pymobiledevice3") is not None
        assert collector.available is expected
    
    def test_detect_chip(self):
        assert DeviceInfoCollector.detect_chip("D321AP", None) == "A12"
        assert DeviceInfoCollector.detect_chip(None, "t8101") == "A13"
        assert DeviceInfoCollector.detect_chip("UNKNOWN", "unknown") is None
    
    def test_get_chip_generation(self):
        assert DeviceInfoCollector.get_chip_generation("A12") == 12
        assert DeviceInfoCollector.get_chip_generation("A17 Pro") == 17
        assert DeviceInfoCollector.get_chip_generation("M1") == 101
        assert DeviceInfoCollector.get_chip_generation("M2") == 102
        assert DeviceInfoCollector.get_chip_generation("Unknown") == 0
    
    def test_classify_device(self):
        assert DeviceInfoCollector.classify_device("iPhone15,2") == "iPhone"
        assert DeviceInfoCollector.classify_device("iPad14,1") == "iPad"
        assert DeviceInfoCollector.classify_device("iPod9,1") == "iPod touch"
        assert DeviceInfoCollector.classify_device("AppleTV6,2") == "Apple TV"
        assert DeviceInfoCollector.classify_device("Watch6,1") == "Apple Watch"
        assert DeviceInfoCollector.classify_device("Unknown") == "Unknown"
    
    def test_mock_report(self, collector):
        report = collector._mock_report("test-udid")
        assert report.udid == "test-udid"
        assert report.chip == "A16"
        assert report.ios_version == "17.4.1"
        assert report.product_type == "iPhone15,2"


class TestSetupAssistantOfflineState:
    """Tests for check_setup_assistant_offline_state method."""
    
    @pytest.fixture
    def collector(self):
        return DeviceInfoCollector()
    
    @pytest.mark.asyncio
    async def test_already_activated(self, collector):
        """Test device that is already activated."""
        with patch.object(pymobiledevice3.lockdown, "create_using_usbmux") as mock_create:
            mock_lockdown = MagicMock()
            mock_lockdown.all_values = {
                "ActivationState": "Activated",
                "SerialNumber": "TEST123",
            }
            mock_create.return_value = mock_lockdown
            
            result = await collector.check_setup_assistant_offline_state("test-udid")
            
            assert result["ready"] is False
            assert result["reason"] == "already_activated"
            assert result["details"]["activation_state"] == "Activated"
            assert result["details"]["is_unactivated"] is False
    
    @pytest.mark.asyncio
    async def test_activated_unlocked(self, collector):
        """Test device that is activated unlocked."""
        with patch.object(pymobiledevice3.lockdown, "create_using_usbmux") as mock_create:
            mock_lockdown = MagicMock()
            mock_lockdown.all_values = {
                "ActivationState": "ActivatedUnlocked",
            }
            mock_create.return_value = mock_lockdown
            
            result = await collector.check_setup_assistant_offline_state("test-udid")
            
            assert result["ready"] is False
            assert result["reason"] == "already_activated"
    
    @pytest.mark.asyncio
    async def test_unactivated_no_sim_no_wifi_no_cloud_config(self, collector):
        """Test device in ideal offline Setup Assistant state."""
        with patch.object(pymobiledevice3.lockdown, "create_using_usbmux") as mock_create, \
             patch.object(pymobiledevice3.services.mobile_config, "MobileConfigService") as mock_mc_class, \
             patch.object(pymobiledevice3.services.diagnostics, "DiagnosticsService") as mock_diag_class:
            
            mock_lockdown = MagicMock()
            mock_lockdown.all_values = {
                "ActivationState": "Unactivated",
                "ICCID": "",
                "SIMSlotStatus": "empty",
                "WiFiAddress": "aa:bb:cc:dd:ee:ff",
            }
            mock_create.return_value = mock_lockdown
            
            # Mock MobileConfigService - no cloud config
            mock_mc = AsyncMock()
            mock_mc.get_cloud_configuration.return_value = {}
            mock_mc_class.return_value.__aenter__.return_value = mock_mc
            
            # Mock DiagnosticsService - no WiFi networks
            mock_diag = AsyncMock()
            mock_diag.action.return_value = {"Status": "Success", "Networks": []}
            mock_diag_class.return_value.__aenter__.return_value = mock_diag
            
            result = await collector.check_setup_assistant_offline_state("test-udid")
            
            assert result["ready"] is True
            assert result["reason"] == "offline_setup_assistant_ready"
            assert result["details"]["is_unactivated"] is True
            assert result["details"]["has_sim"] is False
            assert result["details"]["wifi_connected"] is False
            assert result["details"]["cloud_config_present"] is False
    
    @pytest.mark.asyncio
    async def test_unactivated_with_sim(self, collector):
        """Test device in Setup Assistant but with SIM inserted."""
        with patch.object(pymobiledevice3.lockdown, "create_using_usbmux") as mock_create:
            mock_lockdown = MagicMock()
            mock_lockdown.all_values = {
                "ActivationState": "Unactivated",
                "ICCID": "89860012345678901234",
                "SIMSlotStatus": "ready",
            }
            mock_create.return_value = mock_lockdown
            
            result = await collector.check_setup_assistant_offline_state("test-udid")
            
            assert result["ready"] is False
            assert result["reason"] == "sim_present"
            assert result["details"]["has_sim"] is True
            assert result["details"]["iccid_present"] is True
    
    @pytest.mark.asyncio
    async def test_unactivated_with_wifi(self, collector):
        """Test device in Setup Assistant but connected to WiFi."""
        with patch.object(pymobiledevice3.lockdown, "create_using_usbmux") as mock_create, \
             patch.object(pymobiledevice3.services.mobile_config, "MobileConfigService") as mock_mc_class, \
             patch.object(pymobiledevice3.services.diagnostics, "DiagnosticsService") as mock_diag_class:
            
            mock_lockdown = MagicMock()
            mock_lockdown.all_values = {
                "ActivationState": "Unactivated",
                "ICCID": "",
                "SIMSlotStatus": "empty",
                "WiFiAddress": "aa:bb:cc:dd:ee:ff",
            }
            mock_create.return_value = mock_lockdown
            
            # Mock MobileConfigService - no cloud config
            mock_mc = AsyncMock()
            mock_mc.get_cloud_configuration.return_value = {}
            mock_mc_class.return_value.__aenter__.return_value = mock_mc
            
            # Mock DiagnosticsService - WiFi connected
            mock_diag = AsyncMock()
            mock_diag.action.return_value = {
                "Status": "Success", 
                "Networks": [{"SSID": "TestNetwork", "BSSID": "aa:bb:cc:dd:ee:ff"}]
            }
            mock_diag_class.return_value.__aenter__.return_value = mock_diag
            
            result = await collector.check_setup_assistant_offline_state("test-udid")
            
            assert result["ready"] is False
            assert result["reason"] == "wifi_connected"
            assert result["details"]["wifi_connected"] is True
    
    @pytest.mark.asyncio
    async def test_unactivated_with_cloud_config(self, collector):
        """Test device in Setup Assistant but cloud config already pushed."""
        with patch.object(pymobiledevice3.lockdown, "create_using_usbmux") as mock_create, \
             patch.object(pymobiledevice3.services.mobile_config, "MobileConfigService") as mock_mc_class, \
             patch.object(pymobiledevice3.services.diagnostics, "DiagnosticsService") as mock_diag_class:
            
            mock_lockdown = MagicMock()
            mock_lockdown.all_values = {
                "ActivationState": "Unactivated",
                "ICCID": "",
                "SIMSlotStatus": "empty",
            }
            mock_create.return_value = mock_lockdown
            
            # Mock MobileConfigService - cloud config present and UI complete
            mock_mc = AsyncMock()
            mock_mc.get_cloud_configuration.return_value = {
                "CloudConfigurationUIComplete": True,
                "IsSupervised": True,
            }
            mock_mc_class.return_value.__aenter__.return_value = mock_mc
            
            # Mock DiagnosticsService - no WiFi networks
            mock_diag = AsyncMock()
            mock_diag.action.return_value = {"Status": "Success", "Networks": []}
            mock_diag_class.return_value.__aenter__.return_value = mock_diag
            
            result = await collector.check_setup_assistant_offline_state("test-udid")
            
            assert result["ready"] is False
            assert result["reason"] == "cloud_config_pushed"
            assert result["details"]["cloud_config_present"] is True
            assert result["details"]["cloud_config_ui_complete"] is True
    
    @pytest.mark.asyncio
    async def test_device_not_found(self, collector):
        """Test when device is not connected."""
        from pymobiledevice3.exceptions import DeviceNotFoundError
        with patch.object(pymobiledevice3.lockdown, "create_using_usbmux") as mock_create:
            mock_create.side_effect = DeviceNotFoundError("test-udid", "Device not found")
            
            result = await collector.check_setup_assistant_offline_state("test-udid")
            
            assert result["ready"] is False
            assert "check_failed" in result["reason"]
            assert "Device not found" in result["reason"]
    
    @pytest.mark.asyncio
    async def test_pymobiledevice3_unavailable(self, collector):
        """Test when pymobiledevice3 is not available."""
        collector._pymobiledevice3_available = False
        
        result = await collector.check_setup_assistant_offline_state("test-udid")
        
        assert result["ready"] is False
        assert result["reason"] == "pymobiledevice3_unavailable"


# ... rest of the file unchanged


class TestDeviceReport:
    """Tests for DeviceReport dataclass."""
    
    def test_device_report_creation(self):
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
            serial_number="ABC123",
        )
        d = report.to_dict()
        
        assert d["identity"]["udid"] == "test-udid"
        assert d["metadata"]["chip"] == "A16"
        assert d["metadata"]["ios_version"] == "17.4.1"
        assert d["identity"]["serial_number"] == "ABC123"


class TestDeviceIdentity:
    """Tests for DeviceIdentity dataclass."""
    
    def test_device_identity(self):
        identity = DeviceIdentity(
            udid="test-udid",
            serial_number="ABC123",
            product_type="iPhone15,2",
            product_version="17.4.1",
        )
        assert identity.udid == "test-udid"
        assert identity.serial_number == "ABC123"
        assert identity.product_type == "iPhone15,2"
        assert identity.product_version == "17.4.1"


class TestDeviceStatus:
    """Tests for DeviceStatus dataclass."""
    
    def test_device_status(self):
        status = DeviceStatus(
            activation_state="Activated",
            password_protected=True,
            is_supervised=True,
        )
        assert status.activation_state == "Activated"
        assert status.password_protected is True
        assert status.is_supervised is True


class TestDeviceResources:
    """Tests for DeviceResources dataclass."""
    
    def test_device_resources(self):
        resources = DeviceResources(
            total_disk_capacity=128 * 1024**3,
            data_available=64 * 1024**3,
            battery_cycle_count=100,
        )
        assert resources.total_disk_capacity == 128 * 1024**3
        assert resources.data_available == 64 * 1024**3
        assert resources.battery_cycle_count == 100


class TestDeviceReportDataclass:
    """Tests for DeviceReport dataclass."""
    
    def test_device_report_creation(self):
        report = DeviceReport(
            udid="test-udid",
            serial_number="ABC123",
            product_type="iPhone15,2",
            product_version="17.4.1",
            chip="A16",
        )
        assert report.udid == "test-udid"
        assert report.serial_number == "ABC123"
        assert report.product_type == "iPhone15,2"
        assert report.product_version == "17.4.1"
        assert report.chip == "A16"
    
    def test_device_report_to_dict(self):
        report = DeviceReport(
            udid="test-udid",
            chip="A16",
            ios_version="17.4.1",
            serial_number="ABC123",
        )
        d = report.to_dict()
        
        assert d["identity"]["udid"] == "test-udid"
        assert d["metadata"]["chip"] == "A16"
        assert d["metadata"]["ios_version"] == "17.4.1"
        assert d["identity"]["serial_number"] == "ABC123"


class TestCompatibilityFunctions:
    """Tests for compatibility functions."""
    
    def test_parse_ios_version(self):
        assert parse_ios_version("17.4.1") == (17, 4, 1)
        assert parse_ios_version("18.0") == (18, 0, 0)
        assert parse_ios_version("16.7.1") == (16, 7, 1)
        assert parse_ios_version("26.0") == (26, 0, 0)
        assert parse_ios_version("invalid") == (0, 0, 0)
        assert parse_ios_version("") == (0, 0, 0)
    
    def test_get_chip_from_board_id(self):
        assert get_chip_from_board_id("D321AP") == "A12"
        assert get_chip_from_board_id("D621AP") == "A15"
        assert get_chip_from_board_id("D94AP") == "A18"
        assert get_chip_from_board_id("D20AP") == "A11"
        assert get_chip_from_board_id("UNKNOWN") is None
    
    def test_get_chip_generation(self):
        assert get_chip_generation("A12") == 12
        assert get_chip_generation("A17 Pro") == 17
        assert get_chip_generation("M1") == 101
        assert get_chip_generation("M2") == 102
        assert get_chip_generation("Unknown") == 0
    
    def test_get_device_info_from_pymobiledevice3(self):
        device = {"UDID": "test-udid"}
        info = get_device_info_from_pymobiledevice3(device)
        assert info["udid"] == "test-udid"


class TestConstants:
    """Tests for module constants."""
    
    def test_board_id_to_chip(self):
        assert BOARD_ID_TO_CHIP["D321AP"] == "A12"
        assert BOARD_ID_TO_CHIP["D621AP"] == "A15"
        assert BOARD_ID_TO_CHIP["D94AP"] == "A18"
    
    def test_hardware_platform_to_chip(self):
        assert HARDWARE_PLATFORM_TO_CHIP["t8101"] == "A13"
        assert HARDWARE_PLATFORM_TO_CHIP["t8150"] == "A18"
        assert HARDWARE_PLATFORM_TO_CHIP["t6040"] == "M4"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])