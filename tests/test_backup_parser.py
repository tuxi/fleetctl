"""
Tests for backup_parser module.
"""

import pytest
import tempfile
import plistlib
from pathlib import Path
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


class TestBackupParser:
    """Tests for BackupParser class."""
    
    @pytest.fixture
    def temp_backup(self):
        """Create a temporary backup directory with minimal structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_path = Path(tmpdir) / "test_backup"
            backup_path.mkdir()
            
            # Create minimal Manifest.plist
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
                        }
                    }
                }
            }
            manifest_path = backup_path / "Manifest.plist"
            with open(manifest_path, "wb") as f:
                plistlib.dump(manifest_data, f)
            
            # Create Info.plist
            info_data = {
                "Device Name": "Test iPhone",
                "Product Type": "iPhone15,2",
                "Product Version": "17.4.1",
                "Build Version": "21E236",
                "Serial Number": "ABC123456789",
                "Target Identifier": "test_backup",
                "Last Backup Date": "2024-01-15T10:30:00Z",
            }
            info_path = backup_path / "Info.plist"
            with open(info_path, "wb") as f:
                plistlib.dump(info_data, f)
            
            # Create Status.plist
            status_data = {
                "SnapshotState": "finished",
                "IsFullBackup": True,
                "Date": "2024-01-15T10:30:00Z",
            }
            status_path = backup_path / "Status.plist"
            with open(status_path, "wb") as f:
                plistlib.dump(status_data, f)
            
            yield Path(tmpdir) / "test_backup"
    
    def test_parse_manifest(self, temp_backup):
        parser = BackupParser(temp_backup)
        manifest = parser._parse_manifest()
        
        assert manifest.version == 3
        assert manifest.is_encrypted is False
        assert manifest.device_name == "Test iPhone"
        assert manifest.product_type == "iPhone15,2"
        assert manifest.product_version == "17.4.1"
        assert manifest.serial_number == "ABC123456789"
        assert manifest.unique_device_id == "00008101-00012345ABCDEF"
    
    def test_parse_info(self, temp_backup):
        parser = BackupParser(temp_backup)
        info = parser._parse_info()
        
        assert info.device_name == "Test iPhone"
        assert info.product_type == "iPhone15,2"
        assert info.product_version == "17.4.1"
        assert info.serial_number == "ABC123456789"
    
    def test_parse_status(self, temp_backup):
        parser = BackupParser(temp_backup)
        status = parser._parse_status()
        
        assert status.snapshot_state == "finished"
        assert status.is_full_backup is True
    
    def test_parse_apps(self, temp_backup):
        parser = BackupParser(temp_backup)
        manifest = parser._parse_manifest()
        apps = parser._parse_apps(manifest)
        
        assert len(apps) == 1
        app = apps[0]
        assert app.bundle_id == "com.apple.mobilephone"
        assert app.app_name == "Phone"
        assert app.total_size == 3072  # 1024 + 2048
    
    def test_parse_complete(self, temp_backup):
        parser = BackupParser(temp_backup)
        summary = parser.parse()
        
        assert isinstance(summary, BackupSummary)
        assert summary.manifest.product_type == "iPhone15,2"
        assert summary.info.device_name == "Test iPhone"
        assert summary.status.snapshot_state == "finished"
        assert len(summary.apps) == 1
        assert summary.total_files > 0
        assert summary.total_size > 0
        assert summary.is_encrypted is False
    
    def test_missing_backup(self):
        parser = BackupParser(Path("/nonexistent/path"))
        summary = parser.parse()
        
        assert len(summary.errors) > 0
        assert "does not exist" in summary.errors[0]
    
    def test_get_file_list(self, temp_backup):
        parser = BackupParser(temp_backup)
        files = parser.get_file_list()
        
        assert len(files) >= 3  # At least Manifest.plist, Info.plist, Status.plist
        for f in files:
            assert "path" in f
            assert "size" in f
            assert "mtime" in f


class TestManifestDBParser:
    """Tests for ManifestDBParser (requires actual Manifest.db)."""
    
    def test_open_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "Manifest.db"
            parser = ManifestDBParser(db_path)
            with parser as parser:
                assert parser.conn is None
                assert parser.get_all_files() == []


class TestParseBackupFunction:
    """Test the convenience parse_backup function."""
    
    def test_parse_backup_function(self, temp_backup):
        summary = parse_backup(temp_backup)
        assert isinstance(summary, BackupSummary)
        assert summary.manifest.product_type == "iPhone15,2"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])