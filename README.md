# fleetctl

> Cross-platform compliant device management toolkit

**fleetctl** 是一款跨平台、合规的 iOS 设备管理工具包，面向企业设备管理、批量操作、合规审计场景。

[![CI](https://github.com/fleetctl/fleetctl/actions/workflows/ci.yml/badge.svg)](https://github.com/fleetctl/fleetctl/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

---

## 核心特性

- ✅ **合规优先** - 仅用 Apple 公开 API（pymobiledevice3），无漏洞利用 / 无私有 entitlement / 无越狱依赖
- ✅ **跨平台** - macOS / Windows / Linux
- ✅ **批量操作** - 并发/串行批量检测、擦除、预检；进度条 + 断点续传 + 自适应并发
- ✅ **专业报告** - HTML（响应式/暗色模式）/ PDF（水印/目录/页码）/ JSON（Schema 版本化）/ CSV
- ✅ **安全确认** - 破坏性操作强制交互式二次确认（输入 `WIPE` + 3 秒倒计时）
- ✅ **无需授权读取** - `detect` 无需配对/解锁/激活（同 `ideviceinfo`）

---

## 安装

```bash
# 从 PyPI
pip install fleetctl

# 从源码（开发模式，含 dev + pdf 依赖）
git clone https://github.com/fleetctl/fleetctl.git
cd fleetctl
pip install -e ".[dev,pdf]"
```

**依赖**：Python 3.11+，libimobiledevice（macOS: `brew install libimobiledevice`）

---

## 快速开始

```bash
# 连接设备后列出设备
fleetctl list

# 设备信息检测（无需配对/解锁/激活）
fleetctl detect 00008101-000C6598363A001E

# 三步手工门预检
fleetctl precheck --udid 00008101-000C6598363A001E

# 批量预检（进度条 + 断点续传）
fleetctl bulk precheck --progress --resume

# 批量擦除（强制交互式确认）
fleetctl bulk wipe --progress --resume --confirm

# 生成 PDF 报告
fleetctl report --input devices.json --format pdf --output report.pdf
```

---

## 命令一览

| 命令 | 说明 |
|------|------|
| `detect <UDID>` | 设备信息检测（无需授权） |
| `list` | 列出连接设备 |
| `precheck` | 三步手工门验证 |
| `wipe <UDID> --confirm` | 合规擦除（NIST 800-88） |
| `report` | 报告生成（json/csv/html/pdf） |
| `filter` | 设备过滤 |
| `bulk {detect,wipe,precheck}` | 批量操作（进度条/断点续传/自适应并发） |
| `parse-backup <PATH>` | iOS 备份解析（只读） |
| `monitor` | 监控设备连接 |

完整文档见 [docs/user-guide.md](docs/user-guide.md)，API 参考见 [docs/api.md](docs/api.md)。

---

## 开发

```bash
make help          # 查看所有可用命令
make dev           # 安装开发依赖
make test          # 运行测试
make test-cov      # 测试 + 覆盖率
make lint          # ruff 检查
make type-check    # mypy 类型检查
make check         # 全部质量门禁（lint + type-check + test）
```

### 打包

```bash
make binary        # PyInstaller 单文件二进制
make dmg           # macOS .dmg（需在 macOS 上运行）
make msi           # Windows .msi（需在 Windows 上运行）
make appimage      # Linux .AppImage（需在 Linux 上运行）
make package       # 自动检测平台打包
make build         # Python sdist + wheel
```

### CI/CD

- `.github/workflows/ci.yml` - push/PR 触发：lint + type-check + test（3 OS × 2 Python）+ build
- `.github/workflows/release.yml` - `v*.*.*` tag 触发：多平台打包 + 自动发布 GitHub Release

---

## 合规

**红线（不可触碰）**：

- ❌ 无漏洞利用、无私有 entitlement、无越狱依赖、无灰产签名
- ✅ 仅用 Apple 公开 API（lockdown / mobileconfig / diagnostics）
- ✅ 破坏性操作强制交互确认
- ✅ 所有操作可审计（NIST 800-88 擦除证书）

详见 [docs/compliance.md](docs/compliance.md)。

---

## 许可证

MIT License - 详见 [LICENSE](LICENSE)

---

## 路线图

| 里程碑 | 版本 | 内容 | 状态 |
|--------|------|------|------|
| M1 | v0.1.0 | MVP：CLI、设备检测、备份解析、报告 | ✅ |
| M2 | v0.2.0 | precheck 三步手工门自动化 | ✅ |
| M3 | v0.3.0 | 报告专业化 + 批量操作增强 | ✅ |
| M4 | v0.4.0 | 文档 + 打包 + CI/CD | 🔄 |
| M5 | v1.0.0 | 商业化就绪 | ⏳ |

详见 [docs/ROADMAP.md](docs/ROADMAP.md)。
