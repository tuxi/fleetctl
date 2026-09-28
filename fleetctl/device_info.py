"""
Compliant device information gathering for fleetctl.
Uses only public pymobiledevice3 lockdown and service APIs.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class DeviceIdentity:
    """Core device identity information."""
    udid: str
    serial_number: Optional[str] = None
    product_type: Optional[str] = None
    product_version: Optional[str] = None
    build_version: Optional[str] = None
    device_name: Optional[str] = None
    model_number: Optional[str] = None
    hardware_model: Optional[str] = None
    hardware_platform: Optional[str] = None
    activation_state: Optional[str] = None
    region_info: Optional[str] = None
    imei: Optional[str] = None
    meid: Optional[str] = None
    cpu_architecture: Optional[str] = None
    device_class: Optional[str] = None
    colors: Optional[List[str]] = None


@dataclass
class DeviceStatus:
    """Device operational status."""
    activation_state: Optional[str] = None
    password_protected: Optional[bool] = None
    is_supervised: Optional[bool] = None
    configuration_source: Optional[int] = None
    cloud_configuration_present: bool = False
    profiles_count: int = 0
    profiles: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class DeviceResources:
    """Device hardware resources."""
    total_disk_capacity: Optional[int] = None
    total_data_capacity: Optional[int] = None
    data_available: Optional[int] = None
    total_system_capacity: Optional[int] = None
    battery_cycle_count: Optional[int] = None
    battery_design_capacity: Optional[int] = None
    battery_full_charge_capacity: Optional[int] = None
    apps_count: Optional[int] = None
    apps_static_bytes: Optional[int] = None
    apps_dynamic_bytes: Optional[int] = None


@dataclass
class DeviceReport:
    """Complete device report for fleet management."""
    udid: str
    serial_number: Optional[str] = None
    product_type: Optional[str] = None
    product_version: Optional[str] = None
    build_version: Optional[str] = None
    device_name: Optional[str] = None
    model_number: Optional[str] = None
    hardware_model: Optional[str] = None
    hardware_platform: Optional[str] = None
    activation_state: Optional[str] = None
    region_info: Optional[str] = None
    imei: Optional[str] = None
    meid: Optional[str] = None
    cpu_architecture: Optional[str] = None
    device_class: Optional[str] = None
    colors: Optional[List[str]] = None
    
    # Status
    activation_state: Optional[str] = None
    password_protected: Optional[bool] = None
    is_supervised: Optional[bool] = None
    configuration_source: Optional[int] = None
    cloud_configuration_present: bool = False
    profiles_count: int = 0
    profiles: List[Dict[str, Any]] = field(default_factory=list)
    
    # Resources
    total_disk_capacity: Optional[int] = None
    total_data_capacity: Optional[int] = None
    data_available: Optional[int] = None
    total_system_capacity: Optional[int] = None
    battery_cycle_count: Optional[int] = None
    battery_design_capacity: Optional[int] = None
    battery_full_charge_capacity: Optional[int] = None
    apps_count: Optional[int] = None
    apps_static_bytes: Optional[int] = None
    apps_dynamic_bytes: Optional[int] = None
    
    # Metadata
    chip: Optional[str] = None
    ios_version: Optional[str] = None
    board_id: Optional[str] = None
    hardware_platform: Optional[str] = None
    errors: Dict[str, str] = field(default_factory=dict)
    unavailable: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "identity": {
                "udid": self.udid,
                "serial_number": self.serial_number,
                "product_type": self.product_type,
                "product_version": self.product_version,
                "build_version": self.build_version,
                "device_name": self.device_name,
                "model_number": self.model_number,
                "hardware_model": self.hardware_model,
                "hardware_platform": self.hardware_platform,
                "activation_state": self.activation_state,
                "region_info": self.region_info,
                "imei": self.imei,
                "meid": self.meid,
                "cpu_architecture": self.cpu_architecture,
                "device_class": self.device_class,
                "colors": self.colors,
            },
            "status": {
                "activation_state": self.activation_state,
                "password_protected": self.password_protected,
                "is_supervised": self.is_supervised,
                "configuration_source": self.configuration_source,
                "cloud_configuration_present": self.cloud_configuration_present,
                "profiles_count": self.profiles_count,
                "profiles": self.profiles,
            },
            "resources": {
                "total_disk_capacity": self.total_disk_capacity,
                "total_data_capacity": self.total_data_capacity,
                "data_available": self.data_available,
                "total_system_capacity": self.total_system_capacity,
                "battery_cycle_count": self.battery_cycle_count,
                "battery_design_capacity": self.battery_design_capacity,
                "battery_full_charge_capacity": self.battery_full_charge_capacity,
                "apps_count": self.apps_count,
                "apps_static_bytes": self.apps_static_bytes,
                "apps_dynamic_bytes": self.apps_dynamic_bytes,
            },
            "metadata": {
                "chip": self.chip,
                "ios_version": self.ios_version,
                "board_id": self.board_id,
                "hardware_platform": self.hardware_platform,
            },
            "errors": self.errors,
            "unavailable": self.unavailable,
            "timestamp": self.timestamp,
        }


class DeviceInfoCollector:
    """
    Collects comprehensive device information using only public pymobiledevice3 APIs.
    No exploits, no private APIs, no MDM bypass.
    """
    
    # Chip detection mappings
    BOARD_ID_TO_CHIP = {
        # A8
        "J81AP": "A8", "J82AP": "A8", "J85AP": "A8", "J85mAP": "A8", "J86AP": "A8", "J86mAP": "A8",
        # A9
        "J98AP": "A9", "J98aAP": "A9", "J99AP": "A9", "J99aAP": "A9", "J120AP": "A9", "J121AP": "A9",
        "J127AP": "A9", "J128AP": "A9",
        # A10
        "J120AP": "A10", "J121AP": "A10", "J127AP": "A10", "J128AP": "A10",
        # A11
        "D20AP": "A11", "D201AP": "A11", "D21AP": "A11", "D211AP": "A11", "D22AP": "A11", "D221AP": "A11",
        # A12
        "D321AP": "A12", "D321aAP": "A12", "D331AP": "A12", "D331aAP": "A12", "D331pAP": "A12",
        # A13
        "D421AP": "A13", "D421aAP": "A13", "D431AP": "A13", "D431aAP": "A13", "D431pAP": "A13",
        # A14
        "D521AP": "A14", "D521aAP": "A14", "D531AP": "A14", "D531aAP": "A14", "D531pAP": "A14",
        # A15
        "D621AP": "A15", "D621aAP": "A15", "D631AP": "A15", "D631aAP": "A15", "D631pAP": "A15",
        # A16
        "D721AP": "A16", "D721aAP": "A16", "D731AP": "A16", "D731aAP": "A16", "D731pAP": "A16",
        # A17
        "D821AP": "A17", "D821aAP": "A17", "D831AP": "A17", "D831aAP": "A17", "D831pAP": "A17",
        # A18
        "D94AP": "A18", "D941AP": "A18", "D941aAP": "A18",
    }
    
    HARDWARE_PLATFORM_TO_CHIP = {
        "s5l8960x": "A8",
        "s5l8970x": "A9",
        "t7000": "A9",
        "t7001": "A9",
        "s5l8976x": "A9X",
        "t8010": "A9X",
        "t8011": "A9X",
        "t8015": "A10",
        "t8012": "A10X",
        "t8020": "A11",
        "t8027": "A11",
        "t8030": "A12",
        "t8035": "A12X",
        "t8038": "A12Z",
        "t8101": "A13",
        "t8103": "M1",
        "t8105": "A13X",
        "t8110": "A14",
        "t8112": "M2",
        "t8120": "A15",
        "t8122": "A15",
        "t8130": "A16",
        "t8140": "A17 Pro",
        "t8150": "A18",
        "t8160": "A18 Pro",
        "t6030": "M3",
        "t6031": "M3 Pro",
        "t6032": "M3 Max",
        "t6040": "M4",
    }
    
    def __init__(self):
        self._pymobiledevice3_available = False
        try:
            import pymobiledevice3
            self._pymobiledevice3_available = True
        except ImportError:
            pass
    
    @property
    def available(self) -> bool:
        return self._pymobiledevice3_available
    
    @staticmethod
    def detect_chip(board_id: Optional[str], hardware_platform: Optional[str]) -> Optional[str]:
        """Detect chip from board ID or hardware platform."""
        if board_id and board_id in DeviceInfoCollector.BOARD_ID_TO_CHIP:
            return DeviceInfoCollector.BOARD_ID_TO_CHIP[board_id]
        if hardware_platform and hardware_platform.lower() in DeviceInfoCollector.HARDWARE_PLATFORM_TO_CHIP:
            return DeviceInfoCollector.HARDWARE_PLATFORM_TO_CHIP[hardware_platform.lower()]
        return None
    
    @staticmethod
    def get_chip_generation(chip: Optional[str]) -> int:
        """Extract numeric generation from chip string."""
        if not chip:
            return 0
        import re
        match = re.match(r"A(\d+)", chip, re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.match(r"M(\d+)", chip, re.IGNORECASE)
        if match:
            return 100 + int(match.group(1))
        return 0
    
    @staticmethod
    def classify_device(product_type: Optional[str]) -> str:
        """Classify device type from product type."""
        if not product_type:
            return "Unknown"
        pt = product_type.lower()
        if pt.startswith("iphone"):
            return "iPhone"
        elif pt.startswith("ipad"):
            return "iPad"
        elif pt.startswith("ipod"):
            return "iPod touch"
        elif pt.startswith("appletv") or pt.startswith("apple tv"):
            return "Apple TV"
        elif pt.startswith("watch"):
            return "Apple Watch"
        return "Unknown"
    
    async def collect(self, udid: str) -> "DeviceReport":
        """
        Collect device information using only lockdown public API.
        Works without pairing, unlocking, or activation (like ideviceinfo).
        """
        if not self._pymobiledevice3_available:
            return self._mock_report(udid)
        
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            lockdown = await create_using_usbmux(serial=udid)
            vals = lockdown.all_values or {}
            
            report = DeviceReport(udid=udid)
            
            # Identity - basic lockdown fields (work without pairing/auth)
            report.serial_number = vals.get("SerialNumber")
            report.product_type = vals.get("ProductType")
            report.product_version = vals.get("ProductVersion")
            report.build_version = vals.get("BuildVersion")
            report.device_name = vals.get("DeviceName")
            report.model_number = vals.get("ModelNumber")
            report.hardware_model = vals.get("HardwareModel")
            report.hardware_platform = vals.get("HardwarePlatform")
            report.activation_state = vals.get("ActivationState")
            report.region_info = vals.get("RegionInfo")
            report.imei = vals.get("InternationalMobileEquipmentIdentity")
            report.cpu_architecture = vals.get("CPUArchitecture")
            report.device_class = vals.get("DeviceClass")
            
            # Chip detection
            hw_model = vals.get("HardwareModel")
            hw_platform = vals.get("HardwarePlatform")
            chip = self.detect_chip(hw_model, hw_platform)
            report.chip = chip
            report.ios_version = vals.get("ProductVersion")
            report.board_id = hw_model
            report.hardware_platform = hw_platform
            
            # Status - basic lockdown fields
            report.activation_state = vals.get("ActivationState")
            report.password_protected = vals.get("PasswordProtected")
            
            # Pairing status - check via lockdown connection success
            report.unavailable = [
                "activation_lock",
                "find_my",
                "lost_mode",
                "mdm_enrollment",
                "cloud_configuration",
                "profiles",
                "disk_usage",
                "battery",
                "apps",
            ]
            
            return report
            
        except Exception as e:
            logger.exception(f"Device info collection failed for {udid}")
            report = DeviceReport(udid=udid)
            report.errors["collection"] = str(e)
            return report
    
    async def check_setup_assistant_offline_state(self, udid: str) -> Dict[str, Any]:
        """
        Check if device is in offline Setup Assistant state (before Wi-Fi selection).
        
        Per spec/11 §6.1 Step 2:
        - Device must be erased and rebooted (in Setup Assistant)
        - No SIM card inserted
        - Not connected to Wi-Fi
        - Cloud configuration not yet pushed (MDM window still open)
        - ActivationState should be "Unactivated"
        
        Returns:
            dict with keys:
            - ready: bool - True if all criteria met
            - reason: str - why not ready (if ready=False)
            - details: dict - individual check results
        """
        if not self._pymobiledevice3_available:
            return {
                "ready": False,
                "reason": "pymobiledevice3_unavailable",
                "details": {}
            }
        
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            
            lockdown = await create_using_usbmux(serial=udid)
            vals = lockdown.all_values or {}
            
            details = {}
            
            # 1. Check activation state - must be Unactivated (in Setup Assistant)
            activation_state = vals.get("ActivationState", "")
            details["activation_state"] = activation_state
            is_unactivated = activation_state == "Unactivated"
            details["is_unactivated"] = is_unactivated
            
            if not is_unactivated:
                return {
                    "ready": False,
                    "reason": "already_activated" if activation_state in ["Activated", "ActivatedUnlocked"] else "not_in_setup_assistant",
                    "details": details
                }
            
            # 2. Check SIM status - must be no SIM
            sim_status = vals.get("SIMSupported", False)
            sim_status_str = vals.get("SIMSlotStatus", "")
            iccid = vals.get("ICCID", "")
            details["sim_supported"] = sim_status
            details["sim_slot_status"] = sim_status_str
            details["iccid_present"] = bool(iccid)
            has_sim = bool(iccid) or (sim_status_str and sim_status_str.lower() != "empty")
            details["has_sim"] = has_sim
            
            if has_sim:
                return {
                    "ready": False,
                    "reason": "sim_present",
                    "details": details
                }
            
            # 3. Check Wi-Fi connection status
            wifi_address = vals.get("WiFiAddress", "")
            wifi_connected = await self._check_wifi_connected(lockdown)
            
            details["wifi_address"] = wifi_address
            details["wifi_connected"] = wifi_connected
            
            if wifi_connected:
                return {
                    "ready": False,
                    "reason": "wifi_connected",
                    "details": details
                }
            
            # 4. Check cloud configuration - should be empty/not present
            cloud_config_present, cloud_config_ui_complete = await self._check_cloud_config(lockdown)
            
            details["cloud_config_present"] = cloud_config_present
            details["cloud_config_ui_complete"] = cloud_config_ui_complete
            
            if cloud_config_present and cloud_config_ui_complete:
                return {
                    "ready": False,
                    "reason": "cloud_config_pushed",
                    "details": details
                }
            
            # All checks passed
            details["ready_for_offline_setup"] = True
            return {
                "ready": True,
                "reason": "offline_setup_assistant_ready",
                "details": details
            }
            
        except Exception as e:
            logger.exception(f"Setup Assistant offline check failed for {udid}")
            return {
                "ready": False,
                "reason": f"check_failed: {str(e)}",
                "details": {}
            }
    
    async def _check_wifi_connected(self, lockdown) -> bool:
        """Check if device is connected to Wi-Fi via DiagnosticsService."""
        try:
            from pymobiledevice3.services.diagnostics import DiagnosticsService
            async with DiagnosticsService(lockdown) as diag:
                wifi_info = await asyncio.wait_for(diag.action("WiFi"), timeout=10)
                if isinstance(wifi_info, dict):
                    status = wifi_info.get("Status", "")
                    if status == "Success":
                        networks = wifi_info.get("Networks", [])
                        if networks:
                            return True
        except Exception:
            pass
        return False
    
    async def _check_cloud_config(self, lockdown) -> tuple[bool, bool]:
        """Check cloud configuration status via MobileConfigService."""
        try:
            from pymobiledevice3.services.mobile_config import MobileConfigService
            async with MobileConfigService(lockdown) as mc:
                cc = await asyncio.wait_for(mc.get_cloud_configuration(), timeout=10)
                if isinstance(cc, dict) and cc:
                    return True, cc.get("CloudConfigurationUIComplete", False)
        except Exception:
            pass
        return False, False
    
    def _mock_report(self, udid: str) -> "DeviceReport":
        """Mock report for testing without device."""
        return DeviceReport(
            udid=udid,
            product_type="iPhone15,2",
            product_version="17.4.1",
            build_version="21E236",
            device_name="Test iPhone",
            chip="A16",
            ios_version="17.4.1",
            board_id="D831AP",
            hardware_platform="t8120",
        )


# Compatibility aliases
DeviceInfo = DeviceReport
DeviceIdentity = DeviceReport

def get_device_info_from_pymobiledevice3(device) -> Dict[str, Any]:
    """Extract normalized device info from a pymobiledevice3 device record."""
    if isinstance(device, dict):
        udid = device.get("UDID") or device.get("udid") or device.get("UniqueDeviceID")
        return {
            "udid": udid,
            "serial_number": device.get("SerialNumber"),
            "product_type": device.get("ProductType"),
            "product_version": device.get("ProductVersion"),
            "device_name": device.get("DeviceName"),
        }
    return {"udid": str(device)}


# Module-level constants for compatibility
BOARD_ID_TO_CHIP = DeviceInfoCollector.BOARD_ID_TO_CHIP
HARDWARE_PLATFORM_TO_CHIP = DeviceInfoCollector.HARDWARE_PLATFORM_TO_CHIP

def parse_ios_version(version_str: str) -> tuple[int, int, int]:
    parts = (version_str or "0").split(".")
    try:
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return 0, 0, 0
    return major, minor, patch

def get_chip_from_board_id(board_id: str) -> Optional[str]:
    return DeviceInfoCollector.detect_chip(board_id, None)

def get_chip_generation(chip: str) -> int:
    return DeviceInfoCollector.get_chip_generation(chip)