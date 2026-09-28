"""
Shared pytest fixtures for the fleetctl test suite.
"""

import plistlib
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_backup():
    """Create a temporary backup directory with a minimal valid structure.

    Shared across test classes so both TestBackupParser and the
    module-level convenience-function tests can use it.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        backup_path = Path(tmpdir) / "test_backup"
        backup_path.mkdir()

        # Minimal Manifest.plist
        manifest_data = {
            "Version": 3,
            "IsEncrypted": False,
            "LockdowndVersion": 5,
            "WasPasscodeSet": True,
            "DeviceName": "Test iPhone",
            "ProductType": "iPhone15,2",
            "ProductVersion": "17.4.1",
            "BuildVersion": "21E236",
            "SerialNumber": "ABC123456789",
            "UniqueDeviceID": "00008101-00012345ABCDEF",
            "Applications": {
                "com.apple.mobilephone": {
                    "ApplicationName": "Phone",
                    "ApplicationVersion": "1.0",
                    "BundleVersion": "1.0",
                    "Container": "Data/Containers/Bundle/Application/...",
                    "Files": {
                        "file1": {"Size": 1024},
                        "file2": {"Size": 2048},
                    },
                }
            },
        }
        with open(backup_path / "Manifest.plist", "wb") as f:
            plistlib.dump(manifest_data, f)

        # Info.plist
        info_data = {
            "Device Name": "Test iPhone",
            "Product Type": "iPhone15,2",
            "Product Version": "17.4.1",
            "Build Version": "21E236",
            "Serial Number": "ABC123456789",
            "Target Identifier": "test_backup",
            "Last Backup Date": "2024-01-15T10:30:00Z",
        }
        with open(backup_path / "Info.plist", "wb") as f:
            plistlib.dump(info_data, f)

        # Status.plist
        status_data = {
            "SnapshotState": "finished",
            "IsFullBackup": True,
            "Date": "2024-01-15T10:30:00Z",
        }
        with open(backup_path / "Status.plist", "wb") as f:
            plistlib.dump(status_data, f)

        yield backup_path
