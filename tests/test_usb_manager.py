"""
Tests for usb_manager module.
"""

import asyncio

import pytest
from fleetctl.usb_manager import (
    USBDeviceManager,
    BulkOperationManager,
    DeviceFilter,
    DeviceConnection,
    DeviceConnectionState,
    create_device_manager,
)


class TestDeviceConnection:
    """Tests for DeviceConnection dataclass."""
    
    def test_default_connection(self):
        conn = DeviceConnection(udid="test-udid")
        assert conn.udid == "test-udid"
        assert conn.state == DeviceConnectionState.CONNECTED
        assert conn.info is None
        assert conn.error is None
    
    def test_connection_with_info(self):
        info = {"product_type": "iPhone15,2", "product_version": "17.4.1"}
        conn = DeviceConnection(udid="test-udid", info=info)
        assert conn.info == info


class TestDeviceConnectionState:
    """Tests for DeviceConnectionState enum."""
    
    def test_states(self):
        assert DeviceConnectionState.CONNECTED == "connected"
        assert DeviceConnectionState.DISCONNECTED == "disconnected"
        assert DeviceConnectionState.CONNECTING == "connecting"
        assert DeviceConnectionState.ERROR == "error"


class TestUSBDeviceManager:
    """Tests for USBDeviceManager class."""
    
    @pytest.fixture
    def manager(self):
        return USBDeviceManager()
    
    def test_manager_initialization(self, manager):
        assert manager is not None
        assert hasattr(manager, '_pymobiledevice3_available')
        assert hasattr(manager, '_devices')
        assert hasattr(manager, '_callbacks')
    
    def test_manager_available_property(self, manager):
        # available mirrors whether the hard dependency is importable
        import importlib.util
        expected = importlib.util.find_spec("pymobiledevice3") is not None
        assert manager.available is expected
    
    def test_add_remove_callback(self, manager):
        callback_called = []
        
        def callback(udid, state):
            callback_called.append((udid, state))
        
        manager.add_callback(callback)
        assert callback in manager._callbacks
        
        manager.remove_callback(callback)
        assert callback not in manager._callbacks
    
    def test_get_device(self, manager):
        # Device not connected
        assert manager.get_device("test-udid") is None
        
        # Add device manually
        manager._add_device("test-udid")
        device = manager.get_device("test-udid")
        assert device is not None
        assert device.udid == "test-udid"
    
    def test_get_all_devices(self, manager):
        manager._add_device("udid-1")
        manager._add_device("udid-2")
        
        devices = manager.get_all_devices()
        assert len(devices) == 2
    
    def test_get_connected_udids(self, manager):
        manager._add_device("udid-1")
        manager._add_device("udid-2")
        
        udids = manager.get_connected_udids()
        assert "udid-1" in udids
        assert "udid-2" in udids
        assert len(udids) == 2
    
    def test_is_connected(self, manager):
        assert manager.is_connected("test-udid") is False
        
        manager._add_device("test-udid")
        assert manager.is_connected("test-udid") is True
    
    def test_get_device_count(self, manager):
        assert manager.get_device_count() == 0
        
        manager._add_device("udid-1")
        assert manager.get_device_count() == 1
        
        manager._add_device("udid-2")
        assert manager.get_device_count() == 2
    
    def test_clear(self, manager):
        manager._add_device("udid-1")
        manager._add_device("udid-2")
        
        manager.clear()
        
        assert manager.get_device_count() == 0


class TestBulkOperationManager:
    """Tests for BulkOperationManager class."""
    
    @pytest.fixture
    def device_manager(self):
        return USBDeviceManager()
    
    @pytest.fixture
    def bulk_manager(self, device_manager):
        return BulkOperationManager(device_manager)
    
    @pytest.mark.asyncio
    async def test_run_on_all_success(self, bulk_manager):
        async def operation(udid):
            return f"result-{udid}"
        
        # Mock connected devices
        bulk_manager.device_manager._add_device("udid-1")
        bulk_manager.device_manager._add_device("udid-2")
        
        results = await bulk_manager.run_on_all(operation)
        
        assert "udid-1" in results
        assert "udid-2" in results
        assert results["udid-1"]["success"] is True
        assert results["udid-1"]["result"] == "result-udid-1"
        assert results["udid-2"]["success"] is True
        assert results["udid-2"]["result"] == "result-udid-2"
    
    @pytest.mark.asyncio
    async def test_run_on_all_with_error(self, bulk_manager):
        async def operation(udid):
            if udid == "udid-1":
                return "success"
            raise ValueError("Operation failed")
        
        bulk_manager.device_manager._add_device("udid-1")
        bulk_manager.device_manager._add_device("udid-2")
        
        results = await bulk_manager.run_on_all(operation)
        
        assert results["udid-1"]["success"] is True
        assert results["udid-2"]["success"] is False
        assert "Operation failed" in results["udid-2"]["error"]
    
    @pytest.mark.asyncio
    async def test_run_on_all_with_progress(self, bulk_manager):
        progress_calls = []
        
        def progress_callback(udid, completed, total):
            progress_calls.append((udid, completed, total))
        
        async def operation(udid):
            return f"result-{udid}"
        
        bulk_manager.device_manager._add_device("udid-1")
        bulk_manager.device_manager._add_device("udid-2")
        
        await bulk_manager.run_on_all(operation, progress_callback=progress_callback)
        
        assert len(progress_calls) == 2
        assert progress_calls[0][1] == 1  # completed
        assert progress_calls[0][2] == 2  # total
        assert progress_calls[1][1] == 2
        assert progress_calls[1][2] == 2
    
    @pytest.mark.asyncio
    async def test_run_on_all_cancel(self, bulk_manager):
        async def operation(udid):
            await asyncio.sleep(0.1)
            return "done"
        
        bulk_manager.device_manager._add_device("udid-1")
        bulk_manager.device_manager._add_device("udid-2")
        
        # Cancel immediately
        bulk_manager.cancel()
        
        results = await bulk_manager.run_on_all(operation)
        
        # Should be cancelled, no results
        assert len(results) == 0
    
    @pytest.mark.asyncio
    async def test_run_sequential(self, bulk_manager):
        async def operation(udid):
            return f"result-{udid}"
        
        bulk_manager.device_manager._add_device("udid-1")
        bulk_manager.device_manager._add_device("udid-2")
        
        results = await bulk_manager.run_sequential(operation)
        
        assert results["udid-1"]["success"] is True
        assert results["udid-2"]["success"] is True


class TestDeviceFilter:
    """Tests for DeviceFilter class."""
    
    @pytest.fixture
    def sample_devices(self):
        return [
            {
                "product_type": "iPhone15,2",
                "product_version": "17.4.1",
                "chip": "A16",
                "status": {"is_supervised": True},
                "errors": {},
                "resources": {
                    "total_data_capacity": 128 * 1024**3,
                    "data_available": 64 * 1024**3,
                },
            },
            {
                "product_type": "iPad14,1",
                "product_version": "17.4.1",
                "chip": "M2",
                "status": {"is_supervised": False},
                "errors": {"disk_usage": "error"},
                "resources": {
                    "total_data_capacity": 256 * 1024**3,
                    "data_available": 128 * 1024**3,
                },
            },
            {
                "product_type": "iPhone14,2",
                "product_version": "16.6",
                "chip": "A15",
                "status": {"is_supervised": True},
                "errors": {},
                "resources": {
                    "total_data_capacity": 128 * 1024**3,
                    "data_available": 10 * 1024**3,
                },
            },
        ]
    
    def test_by_product_type(self, sample_devices):
        iphones = DeviceFilter.by_product_type(sample_devices, "iPhone15,2")
        assert len(iphones) == 1
        assert iphones[0]["product_type"] == "iPhone15,2"
    
    def test_by_ios_version(self, sample_devices):
        # iOS 17+
        ios17_plus = DeviceFilter.by_ios_version(sample_devices, min_version="17.0")
        assert len(ios17_plus) == 2
        
        # iOS 16 only
        ios16 = DeviceFilter.by_ios_version(sample_devices, max_version="16.9")
        assert len(ios16) == 1
        assert ios16[0]["product_version"] == "16.6"
    
    def test_by_chip(self, sample_devices):
        a16_devices = DeviceFilter.by_chip(sample_devices, "A16")
        assert len(a16_devices) == 1
        assert a16_devices[0]["chip"] == "A16"
        
        m2_devices = DeviceFilter.by_chip(sample_devices, "M2")
        assert len(m2_devices) == 1
        assert m2_devices[0]["chip"] == "M2"
    
    def test_supervised_only(self, sample_devices):
        supervised = DeviceFilter.supervised_only(sample_devices)
        assert len(supervised) == 2
        for d in supervised:
            assert d["status"]["is_supervised"] is True
    
    def test_unsupervised_only(self, sample_devices):
        unsupervised = DeviceFilter.unsupervised_only(sample_devices)
        assert len(unsupervised) == 1
        assert unsupervised[0]["status"]["is_supervised"] is False
    
    def test_with_errors(self, sample_devices):
        with_errors = DeviceFilter.with_errors(sample_devices)
        assert len(with_errors) == 1
        assert "disk_usage" in with_errors[0]["errors"]
    
    def test_without_errors(self, sample_devices):
        without_errors = DeviceFilter.without_errors(sample_devices)
        assert len(without_errors) == 2
        for d in without_errors:
            assert not d.get("errors")
    
    def test_by_storage(self, sample_devices):
        # Min free 50GB
        filtered = DeviceFilter.by_storage(sample_devices, min_free_gb=50)
        assert len(filtered) == 2  # First two have >50GB free
        
        # Max used 50%
        filtered = DeviceFilter.by_storage(sample_devices, max_used_percent=50)
        assert len(filtered) == 2  # First two have <=50% used


class TestCreateDeviceManager:
    """Tests for create_device_manager convenience function."""
    
    @pytest.mark.asyncio
    async def test_create_device_manager(self):
        manager = await create_device_manager()
        assert isinstance(manager, USBDeviceManager)
        await manager.stop_monitoring()


class TestAdaptiveConcurrency:
    """Tests for adaptive concurrency control."""

    @pytest.fixture
    def bulk_manager(self):
        return BulkOperationManager(USBDeviceManager())

    async def test_run_on_all_adaptive_success(self, bulk_manager):
        async def operation(udid):
            await asyncio.sleep(0.01)
            return f"r-{udid}"

        for i in range(3):
            bulk_manager.device_manager._add_device(f"udid-{i}")

        results = await bulk_manager.run_on_all_adaptive(
            operation, initial_concurrent=2, adjustment_interval=1
        )
        assert len(results) == 3
        assert all(r["success"] for r in results.values())

    async def test_adaptive_respects_limit(self, bulk_manager):
        active = 0
        peak = 0

        async def operation(udid):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return "ok"

        for i in range(6):
            bulk_manager.device_manager._add_device(f"udid-{i}")

        await bulk_manager.run_on_all_adaptive(
            operation,
            initial_concurrent=2,
            min_concurrent=1,
            max_concurrent=2,
            adjustment_interval=100,  # disable adjustment for determinism
        )
        assert peak <= 2

    async def test_adaptive_adjustment_path_runs(self, bulk_manager):
        async def operation(udid):
            await asyncio.sleep(0.005)
            return "ok"

        for i in range(4):
            bulk_manager.device_manager._add_device(f"udid-{i}")

        results = await bulk_manager.run_on_all_adaptive(
            operation,
            initial_concurrent=2,
            min_concurrent=1,
            max_concurrent=4,
            target_latency=0.001,  # force a downward adjustment
            adjustment_interval=1,
        )
        assert len(results) == 4

    def test_calculate_optimal_concurrency(self):
        assert BulkOperationManager.calculate_optimal_concurrency([], 1, 8) == 8
        assert BulkOperationManager.calculate_optimal_concurrency([0.1, 0.2, 0.1], 1, 8, 5.0) >= 1
        # High latency should not exceed the cap
        assert BulkOperationManager.calculate_optimal_concurrency([30.0] * 5, 1, 8, 1.0) <= 8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])