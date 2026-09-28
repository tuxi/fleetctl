"""
Compliant device detection for fleetctl.
Uses only public pymobiledevice3 lockdown APIs.
No exploits, no private APIs, no MDM bypass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import re


class DeviceClass(Enum):
    """Device classification for fleet management."""
    IPHONE = "iPhone"
    IPAD = "iPad"
    IPOD_TOUCH = "iPod touch"
    APPLE_TV = "Apple TV"
    APPLE_WATCH = "Apple Watch"
    UNKNOWN = "Unknown"


@dataclass
class DeviceIdentity:
    """Core device identity information."""
    udid: str
    serial_number: Optional[str] = None
    product_type: Optional[str] = None  # e.g., "iPhone15,2"
    product_version: Optional[str] = None  # e.g., "17.4.1"
    build_version: Optional[str] = None
    device_name: Optional[str] = None
    model_number: Optional[str] = None  # e.g., "MQ9F2LL/A"
    hardware_model: Optional[str] = None  # e.g., "D94AP"
    hardware_platform: Optional[str] = None  # e.g., "t8150"
    activation_state: Optional[str] = None
    region_info: Optional[str] = None
    imei: Optional[str] = None
    meid: Optional[str] = None
    cpu_architecture: Optional[str] = None
    device_class: Optional[str] = None
    colors: Optional[list] = None
    chip: Optional[str] = None
    ios_version: Optional[str] = None
    board_id: Optional[str] = None
    
    def __post_init__(self):
        # Alias ios_version to product_version for compatibility
        if self.ios_version is not None and self.product_version is None:
            self.product_version = self.ios_version
        elif self.product_version is not None and self.ios_version is None:
            self.ios_version = self.product_version


@dataclass
class DeviceStatus:
    """Device operational status."""
    activation_state: Optional[str] = None
    password_protected: Optional[bool] = None
    is_supervised: Optional[bool] = None
    configuration_source: Optional[int] = None
    cloud_configuration_present: bool = False
    profiles_count: int = 0
    profiles: list = None


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
    udid: str = ""
    identity: Optional["DeviceIdentity"] = None
    status: Optional["DeviceStatus"] = None
    resources: Optional["DeviceResources"] = None
    chip: Optional[str] = None
    ios_version: Optional[str] = None
    board_id: Optional[str] = None
    hardware_platform: Optional[str] = None
    errors: dict = field(default_factory=dict)
    unavailable: list = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "identity": {
                "udid": self.udid,
                "serial_number": self.identity.serial_number if self.identity else None,
                "product_type": self.identity.product_type if self.identity else None,
                "product_version": self.identity.product_version if self.identity else None,
                "build_version": self.identity.build_version if self.identity else None,
                "device_name": self.identity.device_name if self.identity else None,
                "model_number": self.identity.model_number if self.identity else None,
                "hardware_model": self.identity.hardware_model if self.identity else None,
                "hardware_platform": self.identity.hardware_platform if self.identity else None,
                "activation_state": self.identity.activation_state if self.identity else None,
                "region_info": self.identity.region_info if self.identity else None,
                "imei": self.identity.imei if self.identity else None,
                "meid": self.identity.meid if self.identity else None,
                "cpu_architecture": self.identity.cpu_architecture if self.identity else None,
                "device_class": self.identity.device_class if self.identity else None,
                "colors": self.identity.colors if self.identity else None,
            },
            "status": {
                "activation_state": self.status.activation_state if self.status else None,
                "password_protected": self.status.password_protected if self.status else None,
                "is_supervised": self.status.is_supervised if self.status else None,
                "configuration_source": self.status.configuration_source if self.status else None,
                "cloud_configuration_present": self.status.cloud_configuration_present if self.status else False,
                "profiles_count": self.status.profiles_count if self.status else 0,
                "profiles": self.status.profiles if self.status else [],
            },
            "resources": {
                "total_disk_capacity": self.resources.total_disk_capacity if self.resources else None,
                "total_data_capacity": self.resources.total_data_capacity if self.resources else None,
                "data_available": self.resources.data_available if self.resources else None,
                "total_system_capacity": self.resources.total_system_capacity if self.resources else None,
                "battery_cycle_count": self.resources.battery_cycle_count if self.resources else None,
                "battery_design_capacity": self.resources.battery_design_capacity if self.resources else None,
                "battery_full_charge_capacity": self.resources.battery_full_charge_capacity if self.resources else None,
                "apps_count": self.resources.apps_count if self.resources else None,
                "apps_static_bytes": self.resources.apps_static_bytes if self.resources else None,
                "apps_dynamic_bytes": self.resources.apps_dynamic_bytes if self.resources else None,
            },
            "metadata": {
                "chip": self.chip,
                "ios_version": self.ios_version,
                "board_id": self.board_id,
                "hardware_platform": self.hardware_platform,
            },
            "errors": self.errors,
            "unavailable": self.unavailable,
        }


class ChipDetector:
    """Chip detection from board ID or hardware platform."""
    
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
        "unknown": None,
    }

    @classmethod
    def detect_chip(cls, board_id: Optional[str], hardware_platform: Optional[str]) -> Optional[str]:
        """Detect chip from board ID or hardware platform."""
        if board_id and board_id in cls.BOARD_ID_TO_CHIP:
            return cls.BOARD_ID_TO_CHIP[board_id]
        if hardware_platform and hardware_platform.lower() in cls.HARDWARE_PLATFORM_TO_CHIP:
            return cls.HARDWARE_PLATFORM_TO_CHIP[hardware_platform.lower()]
        return None

    @classmethod
    def get_chip_generation(cls, chip: Optional[str]) -> int:
        """Extract numeric generation from chip string."""
        if not chip:
            return 0
        import re
        match = re.match(r"A(\d+)", chip, re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.match(r"M(\d+)", chip, re.IGNORECASE)
        if match:
            return 100 + int(match.group(1))  # M1=101, M2=102, etc.
        return 0


class DeviceClassifier:
    """Classify device type from product type."""
    
    @staticmethod
    def classify(product_type: Optional[str]) -> str:
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


class DeviceDetector:
    """
    Compliant device detector using only public pymobiledevice3 lockdown APIs.
    No exploits, no private APIs, no MDM bypass capabilities.
    """
    
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
    
    async def detect(self, udid: str) -> "DeviceReport":
        """
        Detect device information using only public lockdown APIs.
        Returns a complete DeviceReport.
        """
        if not self._pymobiledevice3_available:
            return self._mock_report(udid)
        
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            ld = await create_using_usbmux(serial=udid)
            vals = ld.all_values or {}
            
            # Extract identity
            identity = DeviceIdentity(
                udid=udid,
                serial_number=vals.get("SerialNumber"),
                product_type=vals.get("ProductType"),
                product_version=vals.get("ProductVersion"),
                build_version=vals.get("BuildVersion"),
                device_name=vals.get("DeviceName"),
                model_number=vals.get("ModelNumber"),
                hardware_model=vals.get("HardwareModel"),
                hardware_platform=vals.get("HardwarePlatform"),
                activation_state=vals.get("ActivationState"),
                region_info=vals.get("RegionInfo"),
                imei=vals.get("InternationalMobileEquipmentIdentity"),
                cpu_architecture=vals.get("CPUArchitecture"),
                device_class=vals.get("DeviceClass"),
            )
            
            # Detect chip
            hw_model = vals.get("HardwareModel")
            hw_platform = vals.get("HardwarePlatform")
            chip = ChipDetector.detect_chip(hw_model, vals.get("HardwarePlatform"))
            
            # Status
            status = DeviceStatus(
                activation_state=vals.get("ActivationState"),
                password_protected=vals.get("PasswordProtected"),
            )
            
            # Try to get cloud configuration and profiles
            try:
                from pymobiledevice3.services.mobile_config import MobileConfigService
                async with MobileConfigService(ld) as mc:
                    try:
                        cc = await mc.get_cloud_configuration()
                        if isinstance(cc, dict):
                            status.is_supervised = cc.get("IsSupervised")
                            status.configuration_source = cc.get("ConfigurationSource")
                            status.cloud_configuration_present = bool(cc)
                    except Exception:
                        pass
                    try:
                        pl = await mc.get_profile_list()
                        if isinstance(pl, dict):
                            manifest = pl.get("ProfileManifest") or {}
                            meta = pl.get("ProfileMetadata") or {}
                            profiles = []
                            for ident, entry in manifest.items():
                                if isinstance(entry, dict):
                                    desc = entry.get("Description")
                                    if desc is None and isinstance(meta.get(ident), dict):
                                        desc = meta[ident].get("PayloadDisplayName")
                                    profiles.append({
                                        "identifier": ident,
                                        "description": desc,
                                        "active": entry.get("IsActive"),
                                    })
                            status.profiles_count = len(profiles)
                            status.profiles = profiles
                    except Exception:
                        pass
            except Exception:
                pass
            
            # Resources
            resources = DeviceResources()
            try:
                du = await ld.get_value(domain="com.apple.disk_usage")
                if isinstance(du, dict):
                    keymap = {
                        "TotalDiskCapacity": "total_disk_capacity",
                        "TotalDataCapacity": "total_data_capacity",
                        "TotalDataAvailable": "data_available",
                        "TotalSystemCapacity": "total_system_capacity",
                    }
                    for src, dst in keymap.items():
                        if isinstance(du.get(src), int):
                            setattr(resources, dst, du[src])
            except Exception:
                pass
            
            # Battery
            try:
                from pymobiledevice3.services.diagnostics import DiagnosticsService
                async with DiagnosticsService(ld) as diag:
                    allr = await diag.action("All")
                gg = allr.get("GasGauge") if isinstance(allr, dict) else None
                if isinstance(gg, dict) and gg.get("Status") == "Success":
                    resources.battery_cycle_count = gg.get("CycleCount")
                    resources.battery_design_capacity = gg.get("DesignCapacity")
                    resources.battery_full_charge_capacity = gg.get("FullChargeCapacity")
            except Exception:
                pass
            
            # Apps
            try:
                from pymobiledevice3.services.installation_proxy import InstallationProxyService
                apps = await InstallationProxyService(ld).get_apps(
                    application_type="Any", calculate_sizes=True
                )
                resources.apps_count = len(apps)
                resources.apps_static_bytes = sum(
                    (a.get("StaticDiskUsage") or 0) for a in apps.values()
                )
                resources.apps_dynamic_bytes = sum(
                    (a.get("DynamicDiskUsage") or 0) for a in apps.values()
                )
            except Exception:
                pass
            
            # Chip detection
            hw_model = vals.get("HardwareModel")
            hw_platform = vals.get("HardwarePlatform")
            chip = None
            if hw_model and hw_model in self.BOARD_ID_TO_CHIP:
                chip = self.BOARD_ID_TO_CHIP[hw_model]
            elif hw_platform and hw_platform.lower() in self.HARDWARE_PLATFORM_TO_CHIP:
                chip = self.HARDWARE_PLATFORM_TO_CHIP[hw_platform.lower()]
            
            return DeviceReport(
                identity=DeviceIdentity(
                    udid=vals.get("UniqueDeviceID", ""),
                    serial_number=vals.get("SerialNumber"),
                    product_type=vals.get("ProductType"),
                    product_version=vals.get("ProductVersion"),
                    build_version=vals.get("BuildVersion"),
                    device_name=vals.get("DeviceName"),
                    model_number=vals.get("ModelNumber"),
                    hardware_model=vals.get("HardwareModel"),
                    hardware_platform=vals.get("HardwarePlatform"),
                    activation_state=vals.get("ActivationState"),
                    region_info=vals.get("RegionInfo"),
                    imei=vals.get("InternationalMobileEquipmentIdentity"),
                    cpu_architecture=vals.get("CPUArchitecture"),
                    device_class=vals.get("DeviceClass"),
                ),
                status=DeviceStatus(
                    activation_state=vals.get("ActivationState"),
                    password_protected=vals.get("PasswordProtected"),
                ),
                resources=DeviceResources(),
                chip=chip,
                ios_version=vals.get("ProductVersion"),
                board_id=vals.get("HardwareModel"),
                hardware_platform=vals.get("HardwarePlatform"),
            )
            
        except Exception as e:
            return DeviceReport(
                identity=DeviceIdentity(udid=udid),
                status=DeviceStatus(),
                resources=DeviceResources(),
                errors={"detection": str(e)},
            )
    
    def _mock_report(self, udid: str) -> "DeviceReport":
        """Mock report for testing without device."""
        return DeviceReport(
            udid=udid,
            identity=DeviceIdentity(udid=udid, product_type="iPhone15,2", product_version="17.4.1"),
            status=DeviceStatus(),
            resources=DeviceResources(),
            chip="A16",
            ios_version="17.4.1",
            board_id="D831AP",
        )


# Compatibility aliases for existing code
DeviceInfo = DeviceIdentity
RestoreStrategy = str
StrategyResult = dict

def decide_strategy(info) -> dict:
    """Compatibility stub - returns unsupported for all devices in compliant mode."""
    return {
        "strategy": "unsupported",
        "reason": "Compliant mode: no exploit-based restore strategies available",
        "supported": False,
        "details": {}
    }

def get_device_info_from_pymobiledevice3(device) -> DeviceIdentity:
    """Compatibility stub."""
    return DeviceIdentity(udid=str(device))


# Module-level constants for compatibility
BOARD_ID_TO_CHIP = ChipDetector.BOARD_ID_TO_CHIP
HARDWARE_PLATFORM_TO_CHIP = ChipDetector.HARDWARE_PLATFORM_TO_CHIP

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
    return ChipDetector.detect_chip(board_id, None)

def get_chip_generation(chip: str) -> int:
    return ChipDetector.get_chip_generation(chip)

def get_device_info_from_pymobiledevice3(device) -> DeviceIdentity:
    return DeviceIdentity(udid=str(device))