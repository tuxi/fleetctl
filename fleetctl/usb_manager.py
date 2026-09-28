"""
USB device manager for fleetctl.
Handles device enumeration, monitoring, and bulk operations.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Set
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class DeviceConnectionState(str, Enum):
    """Device connection state."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ERROR = "error"


@dataclass
class DeviceConnection:
    """Represents a connected device."""
    udid: str
    state: DeviceConnectionState = DeviceConnectionState.CONNECTED
    first_seen: datetime = field(default_factory=lambda: datetime.utcnow())
    last_seen: datetime = field(default_factory=lambda: datetime.utcnow())
    info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class USBDeviceManager:
    """
    Manages USB device connections and monitoring.
    Uses pymobiledevice3 for device communication.
    """
    
    def __init__(self):
        self._devices: Dict[str, DeviceConnection] = {}
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False
        self._callbacks: List[Callable[[str, DeviceConnectionState], None]] = []
        self._pymobiledevice3_available = False
        
        try:
            import pymobiledevice3
            self._pymobiledevice3_available = True
        except ImportError:
            pass
    
    @property
    def available(self) -> bool:
        return self._pymobiledevice3_available
    
    def add_callback(self, callback: Callable[[str, DeviceConnectionState], None]):
        """Add a callback for device connection state changes."""
        self._callbacks.append(callback)
    
    def remove_callback(self, callback: Callable[[str, DeviceConnectionState], None]):
        """Remove a callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    def _notify(self, udid: str, state: DeviceConnectionState):
        """Notify all callbacks of state change."""
        for callback in self._callbacks:
            try:
                callback(udid, state)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    async def start_monitoring(self, interval: float = 2.0):
        """Start monitoring for device connections."""
        if self._running:
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval))
        logger.info("USB device monitoring started")
    
    async def stop_monitoring(self):
        """Stop monitoring for device connections."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("USB device monitoring stopped")
    
    async def _monitor_loop(self, interval: float):
        """Monitor loop for device connections."""
        known_devices: Set[str] = set()
        
        while self._running:
            try:
                current_devices = await self.enumerate()
                current_udids = {d.udid for d in current_devices}
                
                # New devices
                for udid in current_udids - known_devices:
                    self._add_device(udid)
                    self._notify(udid, DeviceConnectionState.CONNECTED)
                
                # Disconnected devices
                for udid in known_devices - current_udids:
                    self._remove_device(udid)
                    self._notify(udid, DeviceConnectionState.DISCONNECTED)
                
                # Update existing
                for device in current_devices:
                    if device.udid in self._devices:
                        self._devices[device.udid].last_seen = datetime.utcnow()
                        self._devices[device.udid].info = device.info
                
                known_devices = current_udids
                
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
            
            await asyncio.sleep(interval)
    
    def _add_device(self, udid: str):
        """Add a new device."""
        self._devices[udid] = DeviceConnection(udid=udid)
    
    def _remove_device(self, udid: str):
        """Remove a device."""
        if udid in self._devices:
            self._devices[udid].state = DeviceConnectionState.DISCONNECTED
            del self._devices[udid]
    
    async def enumerate(self) -> List[Dict[str, Any]]:
        """Enumerate all connected devices."""
        if not self._pymobiledevice3_available:
            return []
        
        try:
            from pymobiledevice3.usbmux import list_devices
            from pymobiledevice3.lockdown import create_using_usbmux
            mux_devices = await list_devices()
            
            result = []
            for mux_device in mux_devices:
                udid = mux_device.serial
                device_info = {
                    "udid": udid,
                    "connection_type": mux_device.connection_type,
                }
                
                # Try to get detailed info via lockdown
                try:
                    lockdown = await create_using_usbmux(serial=udid)
                    vals = lockdown.all_values or {}
                    device_info.update({
                        "product_type": vals.get("ProductType"),
                        "product_version": vals.get("ProductVersion"),
                        "build_version": vals.get("BuildVersion"),
                        "device_name": vals.get("DeviceName"),
                        "device_class": vals.get("DeviceClass"),
                    })
                except Exception as e:
                    logger.debug(f"Could not get detailed info for {udid}: {e}")
                
                result.append(device_info)
            return result
        except Exception as e:
            logger.error(f"Device enumeration failed: {e}")
            return []
    
    def get_device(self, udid: str) -> Optional[DeviceConnection]:
        """Get device connection by UDID."""
        return self._devices.get(udid)
    
    def get_all_devices(self) -> List[DeviceConnection]:
        """Get all connected devices."""
        return list(self._devices.values())
    
    def get_connected_udids(self) -> List[str]:
        """Get list of connected UDIDs."""
        return list(self._devices.keys())
    
    def is_connected(self, udid: str) -> bool:
        """Check if device is connected."""
        return udid in self._devices
    
    async def get_device_info(self, udid: str) -> Optional[Dict[str, Any]]:
        """Get detailed device information."""
        if not self._pymobiledevice3_available:
            return None
        
        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            ld = await create_using_usbmux(serial=udid)
            vals = ld.all_values or {}
            
            return {
                "udid": udid,
                "serial_number": vals.get("SerialNumber"),
                "product_type": vals.get("ProductType"),
                "product_version": vals.get("ProductVersion"),
                "build_version": vals.get("BuildVersion"),
                "device_name": vals.get("DeviceName"),
                "model_number": vals.get("ModelNumber"),
                "hardware_model": vals.get("HardwareModel"),
                "hardware_platform": vals.get("HardwarePlatform"),
                "activation_state": vals.get("ActivationState"),
                "region_info": vals.get("RegionInfo"),
                "imei": vals.get("InternationalMobileEquipmentIdentity"),
                "cpu_architecture": vals.get("CPUArchitecture"),
                "device_class": vals.get("DeviceClass"),
                "activation_state": vals.get("ActivationState"),
                "serial_number": vals.get("SerialNumber"),
            }
        except Exception as e:
            logger.error(f"Failed to get device info for {udid}: {e}")
            return None
    
    def get_device_count(self) -> int:
        """Get number of connected devices."""
        return len(self._devices)
    
    def clear(self):
        """Clear all devices."""
        self._devices.clear()


class BulkOperationManager:
    """
    Manages bulk operations on multiple devices.
    """
    
    def __init__(self, device_manager: USBDeviceManager):
        self.device_manager = device_manager
        self._running = False
        self._cancelled = False
    
    @property
    def running(self) -> bool:
        return self._running
    
    def cancel(self):
        """Cancel current operation."""
        self._cancelled = True
    
    async def run_on_all(
        self,
        operation: Callable[[str], Any],
        udids: Optional[List[str]] = None,
        max_concurrent: int = 4,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> Dict[str, Any]:
        """
        Run an operation on multiple devices concurrently.
        
        Args:
            operation: Async function(udid) -> result
            udids: List of UDIDs to operate on (None = all connected)
            max_concurrent: Maximum concurrent operations
            progress_callback: Callback(udid, completed, total)
        
        Returns:
            Dict mapping UDID to result or error
        """
        if udids is None:
            udids = self.device_manager.get_connected_udids()
        
        if not udids:
            return {}
        
        self._running = True
        results = {}
        semaphore = asyncio.Semaphore(max_concurrent)
        completed = 0
        total = len(udids)
        
        async def run_one(udid: str):
            nonlocal completed
            if self._cancelled:
                return
            
            async with semaphore:
                if self._cancelled:
                    return
                
                try:
                    result = await operation(udid)
                    results[udid] = {"success": True, "result": result}
                except Exception as e:
                    results[udid] = {"success": False, "error": str(e)}
                finally:
                    completed += 1
                    if progress_callback:
                        progress_callback(udid, completed, len(udids))
        
        await asyncio.gather(*[run_one(udid) for udid in udids])
        self._running = False
        return results
    
    async def run_sequential(
        self,
        operation: Callable[[str], Any],
        udids: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> Dict[str, Any]:
        """Run operation sequentially on all devices."""
        if udids is None:
            udids = self.device_manager.get_connected_udids()
        
        results = {}
        total = len(udids)
        
        for i, udid in enumerate(udids):
            if self._cancelled:
                break
            
            try:
                result = await operation(udid)
                results[udid] = {"success": True, "result": result}
            except Exception as e:
                results[udid] = {"success": False, "error": str(e)}
            
            if progress_callback:
                progress_callback(udid, i + 1, total)
        
        return results


class DeviceFilter:
    """Filter devices by various criteria."""
    
    @staticmethod
    def by_product_type(devices: List[Dict], product_type: str) -> List[Dict]:
        """Filter by product type (e.g., 'iPhone15,2')."""
        return [d for d in devices if d.get("product_type") == product_type]
    
    @staticmethod
    def by_ios_version(devices: List[Dict], min_version: str = None, max_version: str = None) -> List[Dict]:
        """Filter by iOS version range."""
        def version_key(v: str) -> tuple:
            parts = (v or "0").split(".")
            return tuple(int(p) for p in parts[:3])
        
        min_v = version_key(min_version) if min_version else (0, 0, 0)
        max_v = version_key(max_version) if max_version else (999, 999, 999)
        
        result = []
        for d in devices:
            v = d.get("product_version") or d.get("product_version") or "0"
            v_key = version_key(v)
            if min_v <= v_key <= max_v:
                result.append(d)
        return result
    
    @staticmethod
    def by_chip(devices: List[Dict], chip: str) -> List[Dict]:
        """Filter by chip (e.g., 'A16', 'M1')."""
        return [d for d in devices if d.get("chip") == chip or d.get("metadata", {}).get("chip") == chip]
    
    @staticmethod
    def supervised_only(devices: List[Dict]) -> List[Dict]:
        """Filter supervised devices only."""
        return [d for d in devices if d.get("status", {}).get("is_supervised") is True]
    
    @staticmethod
    def unsupervised_only(devices: List[Dict]) -> List[Dict]:
        """Filter unsupervised devices only."""
        return [d for d in devices if d.get("status", {}).get("is_supervised") is False]
    
    @staticmethod
    def with_errors(devices: List[Dict]) -> List[Dict]:
        """Filter devices with errors."""
        return [d for d in devices if d.get("errors")]
    
    @staticmethod
    def without_errors(devices: List[Dict]) -> List[Dict]:
        """Filter devices without errors."""
        return [d for d in devices if not d.get("errors")]
    
    @staticmethod
    def by_storage(devices: List[Dict], min_free_gb: float = None, max_used_percent: float = None) -> List[Dict]:
        """Filter by storage criteria."""
        result = []
        for d in devices:
            resources = d.get("resources", {})
            total = resources.get("total_data_capacity", 0)
            available = d.get("resources", {}).get("data_available", 0)
            
            if total == 0:
                continue
            
            free_gb = (total - (total - available)) / (1024**3) if available else 0
            used_percent = (total - available) / total * 100 if total else 0
            
            if min_free_gb is not None and free_gb < min_free_gb:
                continue
            if max_used_percent is not None and used_percent > max_used_percent:
                continue
            
            result.append(d)
        return result


# Convenience function
async def create_device_manager() -> USBDeviceManager:
    """Create and start a USB device manager."""
    manager = USBDeviceManager()
    await manager.start_monitoring()
    return manager