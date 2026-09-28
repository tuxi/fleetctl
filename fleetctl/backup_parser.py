"""
Compliant iOS backup parser for fleetctl.
Read-only backup parsing - no modification, no restore, no exploits.
"""

from __future__ import annotations

import plistlib
import sqlite3
import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, BinaryIO
from contextlib import closing


@dataclass
class BackupManifest:
    """Parsed Manifest.plist from iOS backup."""
    version: int = 0
    is_encrypted: bool = False
    lockdownd_version: int = 0
    was_passcode_set: bool = False
    device_name: Optional[str] = None
    product_type: Optional[str] = None
    product_version: Optional[str] = None
    build_version: Optional[str] = None
    serial_number: Optional[str] = None
    unique_device_id: Optional[str] = None
    icloud_account_id: Optional[str] = None
    applications: Dict[str, Any] = field(default_factory=dict)
    key_bag: Optional[bytes] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BackupInfo:
    """Parsed Info.plist from iOS backup."""
    device_name: Optional[str] = None
    product_type: Optional[str] = None
    product_version: Optional[str] = None
    build_version: Optional[str] = None
    serial_number: Optional[str] = None
    target_identifier: Optional[str] = None
    icloud_account_id: Optional[str] = None
    last_backup_date: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BackupStatus:
    """Parsed Status.plist from iOS backup."""
    snapshot_state: Optional[str] = None
    is_full_backup: bool = False
    date: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AppInfo:
    """Application information from backup."""
    bundle_id: str
    app_name: Optional[str] = None
    version: Optional[str] = None
    bundle_version: Optional[str] = None
    container_path: Optional[str] = None
    data_size: int = 0
    documents_size: int = 0
    library_size: int = 0
    total_size: int = 0
    is_encrypted: bool = False
    icon_path: Optional[str] = None


@dataclass
class BackupSummary:
    """Complete backup summary."""
    backup_path: Path
    manifest: "BackupManifest"
    info: "BackupInfo"
    status: "BackupStatus"
    apps: List["AppInfo"]
    total_files: int
    total_size: int
    is_encrypted: bool
    errors: List[str] = field(default_factory=list)


class BackupParser:
    """
    Compliant iOS backup parser.
    Read-only parsing - no modification, no restore, no exploits.
    """
    
    MAX_PLIST_SIZE = 16 * 1024 * 1024  # 16 MB
    
    def __init__(self, backup_path: Path):
        self.backup_path = Path(backup_path).resolve()
        self.errors: List[str] = []
    
    def parse(self) -> "BackupSummary":
        """Parse complete backup and return summary."""
        if not self.backup_path.exists():
            self.errors.append(f"Backup path does not exist: {self.backup_path}")
            return self._empty_summary()
        
        if not self.backup_path.is_dir():
            self.errors.append(f"Backup path is not a directory: {self.backup_path}")
            return self._empty_summary()
        
        # Parse core plists
        manifest = self._parse_manifest()
        info = self._parse_info()
        status = self._parse_status()
        
        # Parse apps
        apps = self._parse_apps(manifest)
        
        # Calculate totals
        total_files = self._count_files()
        total_size = self._calculate_size()
        
        return BackupSummary(
            backup_path=self.backup_path,
            manifest=manifest,
            info=info,
            status=status,
            apps=apps,
            total_files=total_files,
            total_size=total_size,
            is_encrypted=manifest.is_encrypted,
            errors=self.errors,
        )
    
    def _empty_summary(self) -> "BackupSummary":
        return BackupSummary(
            backup_path=self.backup_path,
            manifest=BackupManifest(),
            info=BackupInfo(),
            status=BackupStatus(),
            apps=[],
            total_files=0,
            total_size=0,
            is_encrypted=False,
            errors=self.errors,
        )
    
    def _load_plist(self, filename: str) -> Optional[Dict[str, Any]]:
        """Safely load a plist file with size limits."""
        path = self.backup_path / filename
        if not path.exists():
            return None
        
        try:
            if path.stat().st_size > self.MAX_PLIST_SIZE:
                self.errors.append(f"{filename} exceeds size limit")
                return None
            
            with open(path, "rb") as f:
                return plistlib.load(f)
        except Exception as e:
            self.errors.append(f"Failed to parse {filename}: {e}")
            return None
    
    def _parse_manifest(self) -> "BackupManifest":
        data = self._load_plist("Manifest.plist")
        if not data:
            return BackupManifest()
        
        manifest = BackupManifest(raw=data)
        manifest.version = data.get("Version", 0)
        manifest.is_encrypted = data.get("IsEncrypted", False)
        manifest.lockdownd_version = data.get("LockdowndVersion", 0)
        manifest.was_passcode_set = data.get("WasPasscodeSet", False)
        manifest.device_name = data.get("DeviceName")
        manifest.product_type = data.get("ProductType")
        manifest.product_version = data.get("ProductVersion")
        manifest.build_version = data.get("BuildVersion")
        manifest.serial_number = data.get("SerialNumber")
        manifest.unique_device_id = data.get("UniqueDeviceID")
        manifest.icloud_account_id = data.get("iCloudAccountID")
        manifest.applications = data.get("Applications", {})
        manifest.key_bag = data.get("BackupKeyBag")
        return manifest
    
    def _parse_info(self) -> "BackupInfo":
        data = self._load_plist("Info.plist")
        if not data:
            return BackupInfo()
        
        info = BackupInfo(raw=data)
        info.device_name = data.get("Device Name")
        info.product_type = data.get("Product Type")
        info.product_version = data.get("Product Version")
        info.build_version = data.get("Build Version")
        info.serial_number = data.get("Serial Number")
        info.target_identifier = data.get("Target Identifier")
        info.icloud_account_id = data.get("iCloud Account ID")
        info.last_backup_date = data.get("Last Backup Date")
        return info
    
    def _parse_status(self) -> "BackupStatus":
        data = self._load_plist("Status.plist")
        if not data:
            return BackupStatus()
        
        status = BackupStatus(raw=data)
        status.snapshot_state = data.get("SnapshotState")
        status.is_full_backup = data.get("IsFullBackup", False)
        status.date = data.get("Date")
        return status
    
    def _parse_apps(self, manifest: "BackupManifest") -> List["AppInfo"]:
        apps = []
        for bundle_id, app_data in manifest.applications.items():
            if not isinstance(app_data, dict):
                continue
            
            app = AppInfo(
                bundle_id=bundle_id,
                app_name=app_data.get("ApplicationName"),
                version=app_data.get("ApplicationVersion"),
                bundle_version=app_data.get("BundleVersion"),
                container_path=app_data.get("Container"),
                is_encrypted=manifest.is_encrypted,
            )
            
            # Calculate sizes from file list
            if "Files" in app_data:
                total = 0
                for file_info in app_data["Files"].values():
                    if isinstance(file_info, dict):
                        total += file_info.get("Size", 0)
                app.total_size = total
            
            apps.append(app)
        
        return apps
    
    def _count_files(self) -> int:
        """Count total files in backup."""
        count = 0
        try:
            for root, dirs, files in os.walk(self.backup_path):
                count += len(files)
        except Exception:
            pass
        return count
    
    def _calculate_size(self) -> int:
        """Calculate total backup size in bytes."""
        total = 0
        try:
            for root, dirs, files in os.walk(self.backup_path):
                for f in files:
                    path = Path(root) / f
                    try:
                        total += path.stat().st_size
                    except Exception:
                        pass
        except Exception:
            pass
        return total
    
    def export_file(self, file_id: str, output_path: Path) -> bool:
        """
        Export a single file from backup by file ID.
        Read-only export - no modification.
        """
        # This would require parsing Manifest.db to find the file
        # For now, return False - implement if needed
        return False
    
    def get_file_list(self) -> List[Dict[str, Any]]:
        """Get list of all files in backup with metadata."""
        result = []
        try:
            for root, dirs, filenames in os.walk(self.backup_path):
                for f in filenames:
                    path = Path(root) / f
                    try:
                        stat = path.stat()
                        rel_path = path.relative_to(self.backup_path)
                        result.append({
                            "path": str(rel_path),
                            "size": stat.st_size,
                            "mtime": stat.st_mtime,
                        })
                    except Exception:
                        pass
        except Exception:
            pass
        return result


class ManifestDBParser:
    """Parse Manifest.db (SQLite) for detailed file metadata."""
    
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None
    
    def __enter__(self):
        if self.db_path.exists():
            self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            self.conn.row_factory = sqlite3.Row
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()
    
    def get_all_files(self) -> List[Dict[str, Any]]:
        """Get all files from Manifest.db."""
        if not self.conn:
            return []
        
        try:
            cursor = self.conn.execute("""
                SELECT fileID, domain, relativePath, flags, mode, inode, 
                       userID, groupID, mtime, ctime, atime, size
                FROM Files
                ORDER BY domain, relativePath
            """)
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []
    
    def get_files_by_domain(self, domain: str) -> List[Dict[str, Any]]:
        """Get files for a specific domain."""
        if not self.conn:
            return []
        
        try:
            cursor = self.conn.execute("""
                SELECT fileID, domain, relativePath, flags, mode, inode,
                       userID, groupID, mtime, ctime, atime, size
                FROM Files
                WHERE domain = ?
                ORDER BY relativePath
            """, (domain,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []
    
    def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file metadata by fileID."""
        if not self.conn:
            return None
        
        try:
            cursor = self.conn.execute(
                "SELECT * FROM Files WHERE fileID = ?", (file_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception:
            return None


def parse_backup(backup_path: Path) -> BackupSummary:
    """Convenience function to parse a backup."""
    parser = BackupParser(backup_path)
    return parser.parse()


def open_manifest_db(backup_path: Path) -> Optional[ManifestDBParser]:
    """Open Manifest.db for reading."""
    db_path = Path(backup_path) / "Manifest.db"
    if db_path.exists():
        return ManifestDBParser(db_path)
    return None