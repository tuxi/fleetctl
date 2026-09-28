"""
Compliant configuration writer for fleetctl.
Writes device configurations using only public MobileConfig APIs.
No exploits, no private entitlements, no MDM bypass.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum, IntEnum

logger = logging.getLogger(__name__)


class ConfigurationSource(IntEnum):
    """Configuration source types."""
    USER = 0
    DEVICE = 1
    MDM = 2
    ENTERPRISE = 3


@dataclass
class CloudConfiguration:
    """Cloud configuration payload."""
    allow_pairing: bool = True
    cloud_configuration_ui_complete: bool = True
    configuration_was_applied: bool = True
    is_mdm_unremovable: bool = False
    is_mandatory: bool = False
    is_multi_user: bool = False
    is_supervised: bool = False
    organization_name: Optional[str] = None
    post_setup_profile_was_installed: bool = True
    skip_setup: List[str] = field(default_factory=list)
    # Additional fields can be added as needed


@dataclass
class ConfigurationResult:
    """Result of configuration operation."""
    success: bool
    message: str
    error_code: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class ConfigWriter:
    """
    Compliant configuration writer using public MobileConfigService APIs.
    Only writes configurations that are allowed by public APIs.
    No private entitlements, no exploits.
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
    
    async def write_cloud_configuration(
        self,
        udid: str,
        config: CloudConfiguration
    ) -> "ConfigurationResult":
        """
        Write cloud configuration to device.
        Uses public MobileConfigService.set_cloud_configuration API.
        Requires device to be in a state where cloud config can be written
        (typically during Setup Assistant, before activation).
        """
        if not self._pymobiledevice3_available:
            return ConfigurationResult(
                success=False,
                message="pymobiledevice3 not available",
                error_code="PYMOBILEDEVICE3_UNAVAILABLE"
            )
        
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_config import MobileConfigService
            
            lockdown = await create_using_usbmux(serial=udid)
            
            async with MobileConfigService(lockdown) as mc:
                # Build configuration dict
                config_dict = {
                    "AllowPairing": config.allow_pairing,
                    "CloudConfigurationUIComplete": config.cloud_configuration_ui_complete,
                    "ConfigurationWasApplied": config.configuration_was_applied,
                    "IsMDMUnremovable": config.is_mdm_unremovable,
                    "IsMandatory": config.is_mandatory,
                    "IsMultiUser": config.is_multi_user,
                    "IsSupervised": config.is_supervised,
                    "PostSetupProfileWasInstalled": config.post_setup_profile_was_installed,
                }
                
                if config.organization_name:
                    config_dict["OrganizationName"] = config.organization_name
                
                if config.skip_setup:
                    config_dict["SkipSetup"] = config.skip_setup
                
                # Write configuration
                await mc.set_cloud_configuration(config_dict)
                
                return ConfigurationResult(
                    success=True,
                    message="Cloud configuration written successfully",
                    details={"config": config_dict}
                )
                
        except Exception as e:
            logger.exception(f"Failed to write cloud configuration for {udid}")
            error_msg = str(e)
            
            # Check for known error codes
            if "14002" in error_msg or "already present" in error_msg.lower():
                return ConfigurationResult(
                    success=False,
                    message="Cloud configuration already present on device",
                    error_code="CLOUD_CONFIG_ALREADY_PRESENT",
                    details={"error": error_msg}
                )
            
            return ConfigurationResult(
                success=False,
                message=f"Failed to write cloud configuration: {error_msg}",
                error_code="WRITE_FAILED",
                details={"error": error_msg}
            )
    
    async def read_cloud_configuration(self, udid: str) -> Dict[str, Any]:
        """Read current cloud configuration from device."""
        if not self._pymobiledevice3_available:
            return {"error": "pymobiledevice3 not available"}
        
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_config import MobileConfigService
            
            lockdown = await create_using_usbmux(serial=udid)
            
            async with MobileConfigService(lockdown) as mc:
                config = await mc.get_cloud_configuration()
                return config or {}
                
        except Exception as e:
            logger.error(f"Failed to read cloud configuration for {udid}: {e}")
            return {"error": str(e)}
    
    async def get_profile_list(self, udid: str) -> Dict[str, Any]:
        """Get list of installed configuration profiles."""
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_config import MobileConfigService
            
            lockdown = await create_using_usbmux(serial=udid)
            
            async with MobileConfigService(lockdown) as mc:
                profile_list = await mc.get_profile_list()
                return profile_list or {}
                
        except Exception as e:
            logger.error(f"Failed to get profile list for {udid}: {e}")
            return {"error": str(e)}
    
    async def install_profile(self, udid: str, profile_data: bytes) -> Dict[str, Any]:
        """
        Install a configuration profile.
        Requires user confirmation on device (no silent install without private entitlements).
        """
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_config import MobileConfigService
            
            lockdown = await create_using_usbmux(serial=udid)
            
            async with MobileConfigService(lockdown) as mc:
                await mc.install_profile(profile_data)
                return {"success": True, "message": "Profile installed successfully"}
                
        except Exception as e:
            logger.error(f"Failed to install profile on {udid}: {e}")
            return {"success": False, "error": str(e)}
    
    async def remove_profile(self, udid: str, identifier: str) -> Dict[str, Any]:
        """Remove a configuration profile by identifier."""
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_config import MobileConfigService
            
            lockdown = await create_using_usbmux(serial=udid)
            
            async with MobileConfigService(lockdown) as mc:
                await mc.remove_profile(identifier)
                return {"success": True, "message": f"Profile {identifier} removed"}
                
        except Exception as e:
            logger.error(f"Failed to remove profile {identifier} from {udid}: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_device_profiles(self, udid: str) -> List[Dict[str, Any]]:
        """Get list of installed profiles with details."""
        try:
            profile_list = await self.get_profile_list(udid)
            
            if "error" in profile_list:
                return []
            
            profiles = []
            manifest = profile_list.get("ProfileManifest", {})
            metadata = profile_list.get("ProfileMetadata", {})
            
            for ident, entry in manifest.items():
                if isinstance(entry, dict):
                    desc = entry.get("Description")
                    if desc is None and isinstance(metadata.get(ident), dict):
                        desc = metadata[ident].get("PayloadDisplayName")
                    
                    profiles.append({
                        "identifier": ident,
                        "description": desc,
                        "active": entry.get("IsActive"),
                        "payload_type": metadata.get(ident, {}).get("PayloadType") if isinstance(metadata.get(ident), dict) else None,
                    })
            
            return profiles
        except Exception as e:
            logger.error(f"Failed to get device profiles: {e}")
            return []


# Predefined skip setup options for common use cases
class SkipSetupOptions:
    """Common SkipSetup option combinations."""
    
    ALL = [
        "Location",
        "Restore",
        "SIMSetup",
        "Android",
        "AppleID",
        "IntendedUser",
        "TOS",
        "Siri",
        "ScreenTime",
        "Diagnostics",
        "SoftwareUpdate",
        "Passcode",
        "Biometric",
        "Appearance",
        "TrueTone",
        "HomeGesture",
        "FaceID",
        "TouchID",
        "Payment",
        "Analytics",
        "AppAnalytics",
        "SiriAnalytics",
    ]
    
    MINIMAL = [
        "Location",
        "Restore",
        "SIMSetup",
        "AppleID",
        "TOS",
        "Passcode",
    ]
    
    ENTERPRISE = [
        "Location",
        "Restore",
        "SIMSetup",
        "Android",
        "AppleID",
        "IntendedUser",
        "TOS",
        "Siri",
        "ScreenTime",
        "Diagnostics",
        "SoftwareUpdate",
        "Passcode",
        "Biometric",
    ]
    
    @classmethod
    def custom(cls, *options: str) -> List[str]:
        """Create custom skip setup list."""
        return list(options)


def create_enterprise_config(
    organization_name: str,
    skip_setup: Optional[List[str]] = None,
    supervised: bool = True,
    allow_pairing: bool = True,
) -> "CloudConfiguration":
    """Create a standard enterprise cloud configuration."""
    return CloudConfiguration(
        allow_pairing=allow_pairing,
        cloud_configuration_ui_complete=True,
        configuration_was_applied=True,
        is_mdm_unremovable=False,
        is_mandatory=True,
        is_multi_user=False,
        is_supervised=supervised,
        organization_name=organization_name,
        post_setup_profile_was_installed=True,
        skip_setup=skip_setup or SkipSetupOptions.ENTERPRISE,
    )


def create_skip_setup_config(
    skip_setup: List[str],
    supervised: bool = False,
) -> "CloudConfiguration":
    """Create a minimal skip-setup configuration."""
    return CloudConfiguration(
        allow_pairing=True,
        cloud_configuration_ui_complete=True,
        configuration_was_applied=True,
        is_mdm_unremovable=False,
        is_mandatory=False,
        is_multi_user=False,
        is_supervised=supervised,
        post_setup_profile_was_installed=True,
        skip_setup=skip_setup,
    )