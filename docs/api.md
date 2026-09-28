# fleetctl API 参考

> **版本**：v0.4.0 | **更新**：2026-09-28

本文档描述 `fleetctl` Python 包的所有公共 API。所有 API 均只使用 Apple 公开接口（pymobiledevice3 lockdown / mobileconfig / diagnostics），无私有 entitlement。

---

## 目录

- [设备检测 (device_detector)](#设备检测-device_detector)
- [设备信息采集 (device_info)](#设备信息采集-device_info)
- [USB/批量管理 (usb_manager)](#usb批量管理-usb_manager)
- [预检 (precheck)](#预检-precheck)
- [擦除管理 (wipe_manager)](#擦除管理-wipe_manager)
- [配置写入 (config_writer)](#配置写入-config_writer)
- [报告生成 (report_generator)](#报告生成-report_generator)
- [备份解析 (backup_parser)](#备份解析-backup_parser)
- [macOS 本机管理 (macos)](#macos-本机管理-macos)
- [CLI 入口 (main)](#cli-入口-main)

---

## 设备检测 (device_detector)

### `DeviceDetector`

合规设备检测器，仅使用公开 lockdown API。

```python
from fleetctl.device_detector import DeviceDetector

detector = DeviceDetector()
report = await detector.detect("00008101-...")
```

| 成员 | 说明 |
|------|------|
| `available: bool` | pymobiledevice3 是否可用 |
| `async detect(udid: str) -> DeviceReport` | 检测设备信息 |

### `DeviceReport` (dataclass)

| 字段 | 类型 | 说明 |
|------|------|------|
| `udid` | `str` | 设备唯一标识 |
| `identity` | `DeviceIdentity` | 身份信息 |
| `status` | `DeviceStatus` | 状态信息 |
| `resources` | `DeviceResources` | 硬件资源 |
| `chip` | `Optional[str]` | 芯片（如 A13） |
| `ios_version` | `Optional[str]` | iOS 版本 |
| `errors` | `dict` | 采集错误 |
| `unavailable` | `list` | 不可用字段列表 |
| `to_dict() -> dict` | - | 转字典 |

### `ChipDetector`

```python
ChipDetector.detect_chip(board_id, hardware_platform) -> Optional[str]
ChipDetector.get_chip_generation(chip) -> int   # A13 -> 13, M1 -> 101
```

### 模块级函数

```python
parse_ios_version("17.4.1") -> (17, 4, 1)
get_chip_from_board_id("D53pAP") -> "A13"
get_chip_generation("A13") -> 13
```

---

## 设备信息采集 (device_info)

### `DeviceInfoCollector`

```python
from fleetctl.device_info import DeviceInfoCollector

collector = DeviceInfoCollector()
report = await collector.collect("00008101-...")
```

| 成员 | 说明 |
|------|------|
| `available: bool` | pymobiledevice3 是否可用 |
| `async collect(udid) -> DeviceReport` | 采集信息（**无需配对/解锁/激活**，仅读 lockdown 基础字段） |
| `async check_setup_assistant_offline_state(udid) -> dict` | 三步门 Step 2 自动判定 |
| `detect_chip(board_id, hw_platform) -> Optional[str]` | 静态芯片检测 |
| `get_chip_generation(chip) -> int` | 静态代际提取 |
| `classify_device(product_type) -> str` | 静态设备分类 |

#### `check_setup_assistant_offline_state` 返回值

```python
{
    "ready": bool,          # 全部条件满足才为 True
    "reason": str,          # ready=False 时的原因
    "details": {            # 各判定点
        "activation_state": str,
        "is_unactivated": bool,
        "sim_supported": bool,
        "sim_slot_status": str,
        "iccid_present": bool,
        "has_sim": bool,
        "wifi_address": str,
        "wifi_connected": bool,
        "cloud_config_present": bool,
        "cloud_config_ui_complete": bool,
    }
}
```

**reason 取值**：`already_activated` / `not_in_setup_assistant` / `sim_present` / `wifi_connected` / `cloud_config_pushed` / `offline_setup_assistant_ready` / `pymobiledevice3_unavailable` / `check_failed: <err>`

### `DeviceReport` (device_info 版本)

扁平结构（与 device_detector 版本不同），字段包括 `udid`、`serial_number`、`product_type`、`product_version`、`build_version`、`device_name`、`model_number`、`hardware_model`、`hardware_platform`、`activation_state`、`region_info`、`imei`、`cpu_architecture`、`device_class`、`chip`、`ios_version`、`board_id`、`errors`、`unavailable`、`timestamp`，以及 `to_dict()`。

---

## USB/批量管理 (usb_manager)

### `USBDeviceManager`

```python
from fleetctl.usb_manager import USBDeviceManager

manager = USBDeviceManager()
devices = await manager.enumerate()   # List[dict]
```

| 成员 | 说明 |
|------|------|
| `available: bool` | pymobiledevice3 是否可用 |
| `async enumerate() -> List[dict]` | 枚举设备（含 lockdown 详情） |
| `get_device(udid) -> Optional[DeviceConnection]` | 按 UDID 取连接 |
| `get_all_devices() -> List[DeviceConnection]` | 全部连接 |
| `get_connected_udids() -> List[str]` | 全部 UDID |
| `is_connected(udid) -> bool` | 是否连接 |
| `get_device_count() -> int` | 连接数 |
| `clear()` | 清空 |
| `add_callback(cb)` / `remove_callback(cb)` | 连接事件回调 |
| `async start_monitoring(interval=2.0)` | 开始监控 |
| `async stop_monitoring()` | 停止监控 |
| `async get_device_info(udid) -> Optional[dict]` | 详情 |

### `DeviceConnectionState` (str Enum)

`CONNECTED` / `DISCONNECTED` / `CONNECTING` / `ERROR`

### `BulkOperationManager`

```python
from fleetctl.usb_manager import BulkOperationManager

bulk = BulkOperationManager(manager)
bulk.set_checkpoint_file(Path("checkpoint.json"))

results = await bulk.run_on_all(operation, udids=None, max_concurrent=4, use_tqdm=True, resume=True)
```

| 方法 | 说明 |
|------|------|
| `run_on_all(operation, udids, max_concurrent, progress_callback, use_tqdm, tqdm_desc, resume)` | 并发执行 |
| `run_sequential(operation, udids, progress_callback, use_tqdm, tqdm_desc, resume)` | 串行执行 |
| `run_on_all_adaptive(operation, udids, initial_concurrent, min_concurrent, max_concurrent, target_latency, adjustment_interval, ...)` | 自适应并发 |
| `cancel()` | 取消当前操作 |
| `set_checkpoint_file(path)` | 设置 checkpoint 文件 |
| `get_completed_udids() -> List[str]` | 已完成 UDID（从 checkpoint） |
| `get_checkpoint_results() -> dict` | 已完成结果（从 checkpoint） |
| `clear_checkpoint()` | 清除 checkpoint |
| `generate_summary(results) -> dict` (static) | 结果聚合统计 |
| `export_results(results, format="json") -> str` (static) | 导出 json/csv |
| `calculate_optimal_concurrency(response_times, min_concurrent, max_concurrent, target_latency) -> int` (static) | 计算最优并发 |

**`generate_summary` 返回值**：

```python
{
    "summary": {
        "total_devices": int,
        "successful": int,
        "failed": int,
        "success_rate": float,   # 百分比
    },
    "errors": { "<error message>": count },
    "details": { "<udid>": {"success": bool, "result"|"error": ...} },
}
```

### `DeviceFilter`

```python
DeviceFilter.by_product_type(devices, "iPhone13,3")
DeviceFilter.by_ios_version(devices, min_version="17.0", max_version="18.9")
DeviceFilter.by_chip(devices, "A13")           # 兼容顶层 chip 与 metadata.chip
DeviceFilter.supervised_only(devices)
DeviceFilter.unsupervised_only(devices)
DeviceFilter.with_errors(devices)
DeviceFilter.without_errors(devices)
DeviceFilter.by_storage(devices, min_free_gb=10, max_used_percent=80)
```

### `async create_device_manager() -> USBDeviceManager`

创建并启动监控的管理器。

---

## 预检 (precheck)

只读三步手工门预检（spec/11 §6.1）。**不修改设备、不执行擦除、不做任何 enrollment 或 Remote Management 绕过。**

```python
from fleetctl.precheck import run_precheck_steps, generate_precheck_report
from fleetctl.device_info import DeviceInfoCollector

collector = DeviceInfoCollector()
result = await run_precheck_steps("00008101-...", collector, device_info={"device_name": "iPhone"})
print(result["overall_passed"])
```

| 函数 | 说明 |
|------|------|
| `async check_erase_availability(udid) -> dict` | Step 1：擦除可用性 |
| `async check_usb_pairing(udid) -> dict` | Step 3：USB 配对 |
| `async run_precheck_steps(udid, collector, device_info=None, check_step1=None, check_step3=None, on_step=None) -> dict` | 跑完 1/2/3（Step 2 用 `collector.check_setup_assistant_offline_state`）；`on_step(name, result)` 回调用于进度 |
| `format_precheck_text(result) -> str` | 人类可读文本 |
| `generate_precheck_report(prechecks, format="json", title=..., company_name=None) -> bytes` | 审计报告（json/html） |
| `ERASE_GUIDANCE` / `WAIT_ACK_PROMPT` / `PRECHECK_SCHEMA_VERSION` | 常量 |

**`run_precheck_steps` 返回**：

```python
{
    "udid": str,
    "device_name": str | None,
    "product_type": str | None,
    "product_version": str | None,
    "steps": {
        "erase_available": {"passed": bool, "status": str, "details": ...},
        "setup_assistant_offline": {"passed": bool, "status": str, "details": dict},
        "usb_pairing": {"passed": bool, "status": str, "details": ...},
    },
    "overall_passed": bool,
    "checked_at": str,   # ISO-8601 Z
}
```

CLI（`fleetctl precheck`）：`--udid` / `--json` / `--confirm` / `--wait SECONDS` / `--report PATH` / `--report-format {json,html}` / `--title` / `--company`。

---

## 擦除管理 (wipe_manager)

### `WipeManager`

```python
from fleetctl.wipe_manager import WipeManager, WipeOptions

manager = WipeManager()
result = await manager.wipe_device("00008101-...", WipeOptions(method="full"))
```

| 成员 | 说明 |
|------|------|
| `available: bool` | pymobiledevice3 是否可用 |
| `async wipe_device(udid, options, progress_callback) -> WipeResult` | 擦除（`MobileConfigService.erase_device`） |
| `async verify_wipe(udid) -> dict` | 验证擦除状态 |
| `async get_wipe_status(udid) -> dict` | 获取擦除状态 |

### `WipeOptions` (dataclass)

| 字段 | 默认 | 说明 |
|------|------|------|
| `method` | `"full"` | 擦除方法 |
| `preserve_data_plan` | `False` | 保留 eSIM |
| `disallow_proximity_setup` | `False` | 禁止 proximity setup |
| `verify_after` | `True` | 擦除后验证 |
| `generate_certificate` | `True` | 生成 NIST 证书 |
| `certificate_fields` | `{}` | 证书附加字段 |

### `WipeMethod` (str Enum)

`QUICK="quick"` / `FULL="full"` / `NIST_800_88_CLEAR="nist_clear"` / `NIST_800_88_PURGE="nist_purge"` / `NIST_800_88_DESTROY="nist_destroy"`

### `WipeCertificate`

```python
# Structured certificate
cert = WipeCertificate.build_certificate(
    udid=..., serial_number=..., product_type=..., product_version=...,
    method="full", started_at=..., completed_at=..., success=True, verifier="fleetctl",
)

# JSON string (backward-compatible)
WipeCertificate.generate(...) -> str

# PDF bytes (requires reportlab)
WipeCertificate.generate_pdf(cert, title="Certificate of Data Erasure", organization="ACME") -> bytes

# Write to file: fmt = "json" | "pdf"
WipeCertificate.write(cert, "cert.pdf", "pdf", organization="ACME") -> Path

WipeCertificate.generate_hash(data) -> str  # SHA-256 hex
```

`build_certificate` 返回的 dict 含：`certificate_version`、`standard`、`wipe_method`、`device`（udid/serial_number/product_type/ios_version）、`timestamps`、`result`、`verifier`、`certificate_id`、`hash_algorithm`。

CLI：`wipe --certificate PATH --certificate-format {json,pdf} --company NAME`；`bulk wipe --certificate-dir DIR --certificate-format {json,pdf}`。

### 便捷函数

```python
await quick_wipe(udid) -> dict
await full_wipe_with_certificate(udid, verifier="fleetctl") -> dict
```

---

## 配置写入 (config_writer)

### `ConfigWriter`

```python
from fleetctl.config_writer import ConfigWriter, CloudConfiguration, SkipSetupOptions

writer = ConfigWriter()
config = CloudConfiguration(is_supervised=True, skip_setup=SkipSetupOptions.MINIMAL)
result = await writer.write_cloud_configuration("00008101-...", config)
```

| 方法 | 说明 |
|------|------|
| `async write_cloud_configuration(udid, config) -> ConfigurationResult` | 写云配置（`set_cloud_configuration`） |
| `async read_cloud_configuration(udid) -> dict` | 读云配置 |
| `async get_profile_list(udid) -> dict` | 配置描述文件列表 |
| `async install_profile(udid, profile_data)` | 安装描述文件 |
| `async remove_profile(udid, identifier)` | 移除描述文件 |
| `async get_device_profiles(udid) -> List[dict]` | 描述文件详情 |

### `SkipSetupOptions`

- `ALL` / `MINIMAL` / `ENTERPRISE` - 预定义跳过选项列表
- `custom(*options) -> List[str]` - 自定义

### `ConfigurationSource` (IntEnum)

`USER=0` / `DEVICE=1` / `MDM=2` / `ENTERPRISE=3`

---

## 报告生成 (report_generator)

### `ReportConfig` (dataclass)

`title` / `include_timestamp` / `include_errors` / `include_unavailable` / `company_name` / `logo_path`

### `ReportGeneratorFactory`

```python
from fleetctl.report_generator import ReportGeneratorFactory

content = ReportGeneratorFactory.generate_report(devices, format="html", config=None, output_path=None)
formats = ReportGeneratorFactory.get_supported_formats()  # ['json','csv','html','pdf']
```

### 各生成器

| 类 | 扩展名 | 说明 |
|----|--------|------|
| `JSONReportGenerator` | json | 含 `schema_version`，`get_schema()` 返回 Draft-07 Schema |
| `CSVReportGenerator` | csv | 扁平化嵌套字段 |
| `HTMLReportGenerator` | html | 响应式、暗色模式、可展开详情、分布图表 |
| `PDFReportGenerator` | pdf | 水印、目录、页码、封面（reportlab 后端） |

### 便捷函数

```python
generate_device_report(devices, format="html", title="...", company_name=None, output_path=None) -> bytes
```

---

## 备份解析 (backup_parser)

### `BackupParser`

```python
from fleetctl.backup_parser import parse_backup, BackupParser

summary = parse_backup(Path("/path/to/backup"))
```

| 方法 | 说明 |
|------|------|
| `parse() -> BackupSummary` | 解析完整备份 |
| `get_file_list() -> List[dict]` | 文件列表（path/size/mtime） |

### `BackupSummary`

`backup_path` / `manifest` / `info` / `status` / `apps` / `total_files` / `total_size` / `is_encrypted` / `errors`

### `ManifestDBParser`

```python
with ManifestDBParser(db_path) as parser:
    files = parser.get_all_files()
    files = parser.get_files_by_domain("HomeDomain")
```

### `open_manifest_db(backup_path) -> Optional[ManifestDBParser]`

---

## macOS 本机管理 (macos)

在 Mac 本机运行，仅调用公开 macOS CLI（system_profiler / sw_vers / csrutil / spctl / fdesetup / profiles / diskutil / pmset）。**只读**：无写入、无 sudo、无 MDM 绕过。

```python
from fleetctl.macos import MacInfoCollector, run_mac_precheck, generate_mac_precheck_report

collector = MacInfoCollector()          # 可注入 runner / platform_name 以便测试
info = collector.collect()              # 报告兼容的 device dict
result = run_mac_precheck(collector)    # 只读就绪检查
report = generate_mac_precheck_report([result], format="html")
```

| 成员 | 说明 |
|------|------|
| `MacInfoCollector(runner=None, platform_name=None)` | 采集器；`runner` 可注入（测试用） |
| `MacInfoCollector.available: bool` | 是否在 macOS 上 |
| `MacInfoCollector.collect() -> dict` | 采集，返回 `identity`/`status`/`resources`/`metadata` 结构（可直接喂给 `report_generator`） |
| `CommandRunner(timeout=30.0)` | 命令执行器；`run(args) -> str`（失败返回空串） |
| `is_macos(platform_name=None) -> bool` | 平台判断 |
| `run_mac_precheck(collector=None) -> dict` | 只读检查：`sip` / `filevault` / `secure_boot` / `mdm_enrollment` |
| `format_mac_precheck_text(result) -> str` | 人类可读文本 |
| `generate_mac_precheck_report(results, format="json", title=..., company_name=None) -> bytes` | 审计报告（json/html） |
| `MAC_CHECK_LABELS` / `MACOS_SCHEMA_VERSION` | 常量 |

**`collect()` 返回的 `status` 额外字段**：`sip`、`gatekeeper`、`filevault`、`mdm_enrolled`、`dep_enrolled`、`activation_lock`；`metadata` 含 `platform="macos"`、`chip`、`os_version`、`memory`。

CLI：`fleetctl mac detect|precheck|report`。

---

## CLI 入口 (main)

```python
from fleetctl.main import main
main()   # 或 pyproject.toml 中 [project.scripts] fleetctl = "fleetctl.main:main"
```

### 子命令

| 命令 | 说明 |
|------|------|
| `detect <UDID> [--json]` | 设备信息检测 |
| `list [--json]` | 列出连接设备 |
| `precheck [--udid UDID] [--json]` | 三步手工门验证 |
| `wipe <UDID> ... --confirm` | 单台擦除（交互式确认） |
| `report [--input FILE] [--format] [--output]` | 报告生成 |
| `filter [--input FILE] ...` | 设备过滤 |
| `bulk {detect,wipe,precheck} [--progress] [--resume] [--confirm]` | 批量操作 |
| `parse-backup <PATH> [--json]` | 备份解析 |
| `monitor` | 监控设备连接 |

---

## 异常处理

所有 API 在 pymobiledevice3 不可用时返回错误结构而非抛异常（`available` 为 False 时返回 mock 或空结果）。底层异常会被捕获并记录到 `errors` 字段。

```python
report = await collector.collect(udid)
if report.errors:
    print("采集错误:", report.errors)
```

---

## 合规说明

本 API 仅封装以下 Apple 公开服务：

- `lockdown` - 设备信息查询、配对
- `mobileconfig` - 云配置、描述文件
- `diagnostics` - 电池/硬件信息
- `installation_proxy` - 已安装应用

**不包含**：内核漏洞利用、私有 entitlement（`com.apple.private.*`）、越狱依赖。
