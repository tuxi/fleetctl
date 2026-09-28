"""
fleetctl python-core package.
Compliant device management core modules.
"""

from .device_detector import (
    DeviceDetector,
    DeviceReport,
    DeviceIdentity,
    DeviceStatus,
    DeviceResources,
    ChipDetector,
    DeviceClassifier,
    decide_strategy,
    get_device_info_from_pymobiledevice3,
    parse_ios_version,
    get_chip_from_board_id,
    get_chip_generation,
    BOARD_ID_TO_CHIP,
    HARDWARE_PLATFORM_TO_CHIP,
    RestoreStrategy,
    StrategyResult,
    DeviceInfo,
)

from .backup_parser import (
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

from .device_info import (
    DeviceInfoCollector,
    DeviceReport as DeviceInfoReport,
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

from .config_writer import (
    ConfigWriter,
    CloudConfiguration,
    ConfigurationResult,
    SkipSetupOptions,
    create_enterprise_config,
    create_skip_setup_config,
    ConfigurationSource,
)

from .wipe_manager import (
    WipeManager,
    WipeOptions,
    WipeResult,
    WipeMethod,
    WipeCertificate,
    quick_wipe,
    full_wipe_with_certificate,
)

from .report_generator import (
    ReportGenerator,
    JSONReportGenerator,
    CSVReportGenerator,
    HTMLReportGenerator,
    PDFReportGenerator,
    ReportGeneratorFactory,
    ReportConfig,
    generate_device_report,
)

from .usb_manager import (
    USBDeviceManager,
    BulkOperationManager,
    DeviceFilter,
    DeviceConnection,
    DeviceConnectionState,
    create_device_manager,
)

from .macos import (
    MacInfoCollector,
    CommandRunner,
    run_mac_precheck,
    format_mac_precheck_text,
    generate_mac_precheck_report,
    is_macos,
    MACOS_SCHEMA_VERSION,
)

__all__ = [
    # Device detection
    "DeviceDetector",
    "DeviceReport",
    "DeviceIdentity",
    "DeviceStatus",
    "DeviceResources",
    "ChipDetector",
    "DeviceClassifier",
    "decide_strategy",
    "get_device_info_from_pymobiledevice3",
    "parse_ios_version",
    "get_chip_from_board_id",
    "get_chip_generation",
    "BOARD_ID_TO_CHIP",
    "HARDWARE_PLATFORM_TO_CHIP",
    "RestoreStrategy",
    "StrategyResult",
    "DeviceInfo",
    
    # Backup parsing
    "BackupParser",
    "BackupSummary",
    "BackupManifest",
    "BackupInfo",
    "BackupStatus",
    "AppInfo",
    "ManifestDBParser",
    "parse_backup",
    "open_manifest_db",
    
    # Device info
    "DeviceInfoCollector",
    "DeviceReport as DeviceInfoReport",
    "DeviceIdentity",
    "DeviceStatus",
    "DeviceResources",
    "get_device_info_from_pymobiledevice3",
    "parse_ios_version",
    "get_chip_from_board_id",
    "get_chip_generation",
    
    # Config writer
    "ConfigWriter",
    "CloudConfiguration",
    "ConfigurationResult",
    "SkipSetupOptions",
    "create_enterprise_config",
    "create_skip_setup_config",
    "ConfigurationSource",
    
    # Wipe manager
    "WipeManager",
    "WipeOptions",
    "WipeResult",
    "WipeMethod",
    "WipeCertificate",
    "quick_wipe",
    "full_wipe_with_certificate",
    
    # Report generation
    "ReportGenerator",
    "JSONReportGenerator",
    "CSVReportGenerator",
    "HTMLReportGenerator",
    "PDFReportGenerator",
    "ReportGeneratorFactory",
    "ReportConfig",
    "generate_device_report",
    
    # USB manager
    "USBDeviceManager",
    "BulkOperationManager",
    "DeviceFilter",
    "DeviceConnection",
    "DeviceConnectionState",
    "create_device_manager",
    
    # macOS (local agent)
    "MacInfoCollector",
    "CommandRunner",
    "run_mac_precheck",
    "format_mac_precheck_text",
    "generate_mac_precheck_report",
    "is_macos",
    "MACOS_SCHEMA_VERSION",
]