# fleetctl 用户手册

> **版本**：v0.4.0 | **更新**：2026-09-28

---

## 1. 简介

**fleetctl** 是一个跨平台、合规的 iOS 设备管理工具包，专为企业级设备管理、批量操作、合规审计场景设计。

### 核心特性

- ✅ **合规优先**：仅使用 Apple 公开 API（pymobiledevice3），无漏洞利用、无私有 entitlement、无越狱依赖
- ✅ **跨平台**：macOS / Windows / Linux 全平台支持
- ✅ **批量操作**：并发/串行批量检测、擦除、预检，支持断点续传
- ✅ **专业报告**：HTML/PDF/JSON/CSV 多格式，含水印、目录、页码、证书
- ✅ **安全确认**：破坏性操作强制交互式二次确认（输入 WIPE + 倒计时）

---

## 2. 安装

### 系统要求

- Python 3.11+
- libimobiledevice (macOS: `brew install libimobiledevice`，Linux: `apt install libimobiledevice-utils`)
- Windows: 需安装 Apple Mobile Device Support (随 iTunes 安装)

### 安装方式

```bash
# 从 PyPI 安装（推荐）
pip install fleetctl

# 或从源码安装
git clone https://github.com/fleetctl/fleetctl.git
cd fleetctl
pip install -e .
```

### 验证安装

```bash
fleetctl --help
fleetctl list
```

---

## 3. 快速开始

### 3.1 连接设备

1. 用 USB 数据线连接 iPhone/iPad 到电脑
2. 设备上点击"信任此电脑"，输入锁屏密码
3. 运行 `fleetctl list` 验证连接

```bash
$ fleetctl list
00008101-000C6598363A001E  iPhone  iPhone13,3  26.5.2
```

### 3.2 设备信息检测

```bash
# 单台设备详细信息（无需配对/解锁/激活）
fleetctl detect 00008101-000C6598363A001E

# JSON 格式输出
fleetctl detect 00008101-000C6598363A001E --json
```

### 3.3 三步预检（precheck）

```bash
# 单台设备预检
fleetctl precheck --udid 00008101-000C6598363A001E

# 批量预检（带进度条、断点续传）
fleetctl bulk precheck --progress --resume
```

---

## 4. 命令参考

### 4.1 detect - 设备信息检测

```bash
fleetctl detect <UDID> [--json]
```

**特点**：无需配对、无需解锁、无需激活，仅读 lockdown 基础字段（同 `ideviceinfo`）

### 4.2 list - 列出连接设备

```bash
fleetctl list [--json]
```

### 4.3 precheck - 三步手工门验证

```bash
# 只读预检（单台 / 全部）
fleetctl precheck [--udid UDID] [--json]

# 输出可审计报告（JSON / HTML）
fleetctl precheck --report audit.json --report-format json --company "ACME"
fleetctl precheck --report audit.html --report-format html --title "巡检报告"

# 交互式引导：若 Step 2 未通过，打印擦除指引并等待进入 Setup Assistant
fleetctl precheck --confirm --wait 300
```

**三步检查**（只读，绝不修改设备）：
1. 擦除可用性 - 检查 ActivationState、锁屏密码、监管状态
2. 离线 Setup Assistant - 检查能否离线进入 Wi-Fi 选择前界面
3. USB 配对 - 验证 USB 连接和配对信任关系

**选项**：
- `--confirm` - 启用交互式引导流程（Step 2 未通过时打印手动擦除指引，并提示输入 `READY`）
- `--wait SECONDS` - 配合 `--confirm`：轮询等待设备进入离线 Setup Assistant 状态，最长 SECONDS 秒
- `--report PATH` / `--report-format {json,html}` - 输出审计报告
- `--title` / `--company` - 报告标题与公司名

> `fleetctl` **不执行擦除**。抹机是设备上的手动操作（设置 → 通用 → 传输或还原 iPhone → 抹掉所有内容和设置）；本命令只做只读判定与引导。

### 4.4 wipe - 合规擦除

```bash
# 单台擦除（需交互式确认）
fleetctl wipe <UDID> --confirm

# 擦除并写出证书（JSON 或 PDF）
fleetctl wipe <UDID> --confirm --certificate cert.pdf --certificate-format pdf --company "ACME"

# 批量擦除（串行、进度条、断点续传），每台一份证书
fleetctl bulk wipe --progress --resume --confirm --certificate-dir ./certs --certificate-format pdf
```

**⚠️ 警告**：擦除不可逆，数据永久销毁（NIST 800-88 Purge），Activation Lock 保留。

**安全确认**：单台与批量擦除都必须 `--confirm`，随后在终端**手动输入 `WIPE`**（全大写）并等待 3 秒倒计时，才会真正执行。

**擦除证书**（NIST SP 800-88 Rev. 1）：
- `--certificate PATH` / `--certificate-format {json,pdf}` - 单台证书输出路径与格式
- `--certificate-dir DIR` - 批量模式：每台设备写 `<UDID>.<fmt>`
- `--company` - PDF 证书上显示的组织名
- 证书含：证书 ID、设备信息、擦除方法、时间戳、结果、验证者、SHA-256 完整性哈希
- PDF 版为正式排版（标题、分区表格、结果横幅、完整性哈希、页脚声明）

### 4.5 report - 专业报告生成

```bash
# 从设备采集并生成
fleetctl report --udid <UDID> --format html --output report.html

# 从 JSON 文件生成
fleetctl report --input devices.json --format pdf --output report.pdf --title "设备巡检报告" --company "公司名"
```

**支持格式**：HTML（响应式、暗色模式、可展开详情）、PDF（水印、目录、页码、证书布局）、JSON（Schema 版本化）、CSV

### 4.6 filter - 设备过滤

```bash
fleetctl filter --input devices.json --chip A13 --supervised --min-free-gb 10
```

### 4.7 bulk - 批量操作

```bash
# 批量检测
fleetctl bulk detect --progress --resume --max-concurrent 4

# 批量预检
fleetctl bulk precheck --progress --resume

# 批量擦除（需确认）
fleetctl bulk wipe --progress --resume --confirm
```

**参数**：
- `--max-concurrent` - 最大并发数（默认 4）
- `--progress` - 显示 tqdm 进度条
- `--resume` - 从 checkpoint 断点续传
- `--json` - JSON 输出

### 4.8 parse-backup - 备份解析

```bash
fleetctl parse-backup /path/to/backup --json
```

### 4.9 monitor - 监控设备连接

```bash
fleetctl monitor
```

---

## 5. 高级用法

### 5.1 断点续传

```bash
# 首次运行（创建 checkpoint）
fleetctl bulk detect --progress --resume

# 中断后恢复（跳过已完成设备）
fleetctl bulk detect --progress --resume
```

Checkpoint 文件默认位置：`~/.fleetctl/checkpoints/<operation>.json`

### 5.2 结果导出

```bash
# JSON 导出
fleetctl bulk detect --json > results.json

# CSV 导出
python -c "
from fleetctl.usb_manager import BulkOperationManager
import json
with open('results.json') as f:
    results = json.load(f)
print(BulkOperationManager.export_results(results, 'csv'))
"
```

### 5.3 自适应并发（实验性）

```python
from fleetctl.usb_manager import BulkOperationManager, USBDeviceManager

manager = USBDeviceManager()
bulk = BulkOperationManager(manager)

# 自动根据 P95 延迟调整并发
results = await bulk.run_on_all_adaptive(
    operation,
    initial_concurrent=4,
    min_concurrent=1,
    max_concurrent=16,
    target_latency=5.0,
)
```

---

## 6. 报告详解

### 6.1 HTML 报告特性

- 响应式布局（移动端/桌面端自适应）
- 暗色模式支持（`prefers-color-scheme`）
- 可展开设备详情行
- 分布图表（机型/iOS版本/芯片分布）
- 打印样式优化（隐藏交互元素、页眉页脚）

### 6.2 PDF 报告特性

- 水印（fleetctl 斜向半透明）
- 目录（可点击跳转）
- 页码（Page X of Y）
- 封面页（标题、生成时间、设备数、公司名）
- 页眉/页脚（报告名、页码、机密标识）
- 水印文字（fleetctl 斜向半透明）

### 6.3 JSON Schema

```bash
# 获取 Schema
python -c "from fleetctl.report_generator import JSONReportGenerator; import json; print(json.dumps(JSONReportGenerator.get_schema(), indent=2))"
```

输出符合 JSON Schema Draft-07，包含版本控制、设备定义、元数据约束。

---

## 7. 故障排查

### 7.1 常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| `Device not found` | 设备未连接/未配对 | 检查数据线、点击"信任"、输入密码 |
| `PasswordProtected` | 设备有锁屏密码 | 解锁设备到主屏幕 |
| `Permission denied` | 无 USB 权限 | macOS: 系统设置 → 隐私与安全性 → 辅助功能；Linux: udev 规则 |
| `ModuleNotFoundError: pymobiledevice3` | 依赖缺失 | `pip install pymobiledevice3` |
| PDF 生成失败 | 缺少 weasyprint/reportlab | `pip install reportlab` 或 `pip install weasyprint` |

### 7.2 调试模式

```bash
# 启用详细日志
FLEETCTL_DEBUG=1 fleetctl detect <UDID>

# Python 代码中启用
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 7.3 常见错误代码

| 错误代码 | 含义 |
|----------|------|
| `PasswordProtected` | 设备有锁屏密码，需解锁 |
| `DeviceNotFoundError` | 设备未连接或 UDID 错误 |
| `PairingRequired` | 需要在设备上点击"信任" |
| `ActivationLock` | 激活锁开启，需 Apple ID 解锁 |

---

## 8. 最佳实践

### 8.1 批量设备管理流程

```bash
# 1. 连接所有设备
fleetctl list

# 2. 预检（验证擦除条件）
fleetctl bulk precheck --progress --resume

# 3. 批量擦除（需确认）
fleetctl bulk wipe --progress --resume --confirm

# 4. 生成擦除报告
fleetctl report --input wipe_results.json --format pdf --output wipe_report.pdf
```

### 8.2 合规审计清单

- [ ] 所有擦除操作有 `--confirm` 交互确认记录
- [ ] 生成擦除证书（NIST 800-88 格式）
- [ ] 保存操作审计日志（时间、操作、用户、设备、结果）
- [ ] 保存擦除报告（PDF/HTML/JSON）

---

## 9. 合规声明

> **fleetctl 严格遵守以下合规红线**：
> - ❌ 无漏洞利用、无私有 entitlement、无越狱依赖
> - ❌ 无灰产签名、无企业证书滥用
> - ✅ 仅使用 Apple 公开 API（lockdown/mobileconfig/diagnostics）
> - ✅ 破坏性操作强制交互式确认
> - ✅ 所有操作记录审计日志

---

## 10. 更新日志

### v0.4.0 (M4 - 进行中)
- 文档体系、多平台打包、CI/CD 流水线

### v0.3.0 (M3 - 完成)
- HTML 响应式报告、PDF 证书规范化、JSON Schema 版本化
- 批量操作进度条、断点续传、结果聚合、自适应并发
- wipe 交互式安全确认、detect 无授权读取

### v0.2.0 (M2 - 完成)
- precheck 三步手工门全自动化

### v0.1.0 (M1 - 完成)
- MVP：基础 CLI、设备检测、备份解析、报告生成

---

## 11. 许可证

MIT License - 详见 [LICENSE](LICENSE)

---

## 12. 支持与反馈

- GitHub Issues: https://github.com/fleetctl/fleetctl/issues
- 文档: https://github.com/fleetctl/fleetctl/docs
- 合规咨询: compliance@fleetctl.io