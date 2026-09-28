"""
Compliant device wipe manager for fleetctl.
Implements NIST 800-88 compliant device erasure.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class WipeMethod(str, Enum):
    """Wipe method types."""
    QUICK = "quick"           # Quick erase (logical)
    FULL = "full"             # Full erase (cryptographic)
    NIST_800_88_CLEAR = "nist_clear"      # NIST 800-88 Clear
    NIST_800_88_PURGE = "nist_purge"      # NIST 800-88 Purge (cryptographic erase)
    NIST_800_88_DESTROY = "nist_destroy"  # NIST 800-88 Destroy (physical)


class WipeStatus(Enum):
    """Wipe operation status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WipeOptions:
    """Options for device wipe operation."""
    method: str = "full"
    preserve_data_plan: bool = False
    disallow_proximity_setup: bool = False
    verify_after: bool = True
    generate_certificate: bool = True
    certificate_fields: Dict[str, str] = field(default_factory=dict)


@dataclass
class WipeResult:
    """Result of wipe operation."""
    success: bool
    method: str
    udid: str
    message: str
    error_code: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    certificate: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: float = 0.0


class WipeCertificate:
    """Generates NIST 800-88 compliant wipe certificates."""
    
    @staticmethod
    def generate(
        udid: str,
        serial_number: str,
        product_type: str,
        product_version: str,
        method: str,
        started_at: str,
        completed_at: str,
        success: bool,
        verifier: str = "fleetctl",
        additional_fields: Dict[str, str] = None
    ) -> str:
        """Generate a wipe certificate in JSON format."""
        import json
        
        certificate = {
            "certificate_version": "1.0",
            "standard": "NIST SP 800-88 Rev. 1",
            "wipe_method": method,
            "device": {
                "udid": udid,
                "serial_number": serial_number,
                "product_type": product_type,
                "ios_version": None,  # Will be filled by caller
            },
            "timestamps": {
                "started_at": started_at,
                "completed_at": completed_at,
            },
            "result": "success" if success else "failed",
            "verifier": verifier,
            "certificate_id": secrets.token_hex(16),
            "hash_algorithm": "SHA-256",
        }
        
        if additional_fields:
            certificate["additional_fields"] = additional_fields
        
        return json.dumps(certificate, indent=2)
    
    @staticmethod
    def generate_hash(data: str) -> str:
        """Generate SHA-256 hash of certificate data."""
        return hashlib.sha256(data.encode()).hexdigest()


class WipeManager:
    """
    Compliant device wipe manager.
    Uses public MobileConfigService.erase_device API.
    Supports NIST 800-88 compliant wipe certificates.
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
    
    async def wipe_device(
        self,
        udid: str,
        options: Optional["WipeOptions"] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> "WipeResult":
        """
        Wipe device using public MobileConfigService.erase_device API.
        This is the only compliant way to wipe a device remotely.
        """
        if not self._pymobiledevice3_available:
            return WipeResult(
                success=False,
                method="unknown",
                udid=udid,
                message="pymobiledevice3 not available",
                error_code="PYMOBILEDEVICE3_UNAVAILABLE"
            )
        
        options = options or WipeOptions()
        started_at = datetime.utcnow().isoformat() + "Z"
        start_time = asyncio.get_event_loop().time()
        
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            from pymobiledevice3.services.mobile_config import MobileConfigService
            
            # Get device info for certificate
            lockdown = await create_using_usbmux(serial=udid)
            vals = ld.all_values or {}
            
            serial_number = vals.get("SerialNumber", "Unknown")
            product_type = vals.get("ProductType", "Unknown")
            product_version = vals.get("ProductVersion", "Unknown")
            
            # Emit progress
            if progress_callback:
                progress_callback(10, "Initializing wipe...")
            
            # Determine wipe method
            method = options.method if options else "full"
            
            # For iOS, the only compliant remote wipe is via MobileConfigService.erase_device
            # This performs a full cryptographic erase (equivalent to NIST 800-88 Purge)
            async with MobileConfigService(ld) as mc:
                if progress_callback:
                    progress_callback(30, "Initiating device erase...")
                
                # The erase_device method performs a full cryptographic erase
                # preserve_data_plan: whether to preserve eSIM data plan
                # disallow_proximity_setup: whether to disable proximity setup after erase
                await mc.erase_device(
                    preserve_data_plan=options.preserve_data_plan if options else False,
                    disallow_proximity_setup=options.disallow_proximity_setup if options else False
                )
            
            if progress_callback:
                progress_callback(90, "Erase completed, waiting for reboot...")
            
            # Wait for device to reboot
            await self._wait_for_reboot(udid, timeout=120)
            
            completed_at = datetime.utcnow().isoformat() + "Z"
            duration = asyncio.get_event_loop().time() - start_time
            
            # Generate certificate
            certificate = None
            if options and options.generate_certificate:
                certificate = WipeCertificate.generate(
                    udid=udid,
                    serial_number=serial_number,
                    product_type=product_type,
                    product_version=product_version,
                    method=method,
                    started_at=started_at,
                    completed_at=completed_at,
                    success=True,
                    verifier="fleetctl",
                )
            
            return WipeResult(
                success=True,
                method=method,
                udid=udid,
                message="Device wiped successfully",
                details={
                    "serial_number": serial_number,
                    "product_type": product_type,
                    "wipe_method": method,
                },
                certificate=certificate,
                started_at=started_at,
                completed_at=completed_at,
                duration_seconds=duration,
            )
            
        except Exception as e:
            logger.exception(f"Wipe failed for {udid}")
            error_msg = str(e)
            
            return WipeResult(
                success=False,
                method=options.method if options else "unknown",
                udid=udid,
                message=f"Wipe failed: {error_msg}",
                error_code="WIPE_FAILED",
                details={"error": str(e)},
                started_at=datetime.utcnow().isoformat() + "Z",
                completed_at=datetime.utcnow().isoformat() + "Z",
            )
    
    async def _wait_for_reboot(self, udid: str, timeout: int = 120) -> bool:
        """Wait for device to reboot and become available again."""
        start = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start < timeout:
            try:
                from pymobiledevice3.usbmux import list_devices
                devices = await list_devices()
                for device in devices:
                    if device.serial == udid:
                        return True
            except Exception:
                pass
            
            await asyncio.sleep(2)
        
        return False
    
    async def verify_wipe(self, udid: str) -> Dict[str, Any]:
        """
        Verify that device has been wiped.
        Checks if device is in Setup Assistant state.
        """
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            ld = await create_using_usbmux(serial=udid)
            vals = ld.all_values or {}
            
            # Check if device is in Setup Assistant (activation state)
            activation_state = vals.get("ActivationState", "")
            is_activated = activation_state in ["Activated", "ActivatedUnlocked"]
            
            return {
                "wiped": not is_activated,
                "activation_state": activation_state,
                "device_name": vals.get("DeviceName"),
                "product_type": vals.get("ProductType"),
                "product_version": vals.get("ProductVersion"),
            }
        except Exception as e:
            return {"error": str(e), "wiped": False}
    
    async def get_wipe_status(self, udid: str) -> Dict[str, Any]:
        """Get current wipe status of device."""
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            ld = await create_using_usbmux(serial=udid)
            vals = ld.all_values or {}
            
            return {
                "udid": udid,
                "activation_state": vals.get("ActivationState"),
                "serial_number": vals.get("SerialNumber"),
                "product_type": vals.get("ProductType"),
                "product_version": vals.get("ProductVersion"),
                "wiped": vals.get("ActivationState") not in ["Activated", "ActivatedUnlocked"],
            }
        except Exception as e:
            return {"error": str(e)}


# Convenience functions
async def quick_wipe(udid: str) -> Dict[str, Any]:
    """Quick wipe with default options."""
    manager = WipeManager()
    result = await manager.wipe_device(udid)
    return {
        "success": result.success,
        "message": result.message,
        "certificate": result.certificate,
    }


async def full_wipe_with_certificate(
    udid: str,
    verifier: str = "fleetctl",
    additional_fields: Dict[str, str] = None
) -> Dict[str, Any]:
    """Full wipe with NIST 800-88 certificate."""
    options = WipeOptions(
        method="full",
        verify_after=True,
        generate_certificate=True,
        certificate_fields={"verifier": verifier} if verifier else {}
    )
    
    manager = WipeManager()
    result = await manager.wipe_device(udid, options)
    
    return {
        "success": result.success,
        "message": result.message,
        "certificate": result.certificate,
        "details": result.details,
    }