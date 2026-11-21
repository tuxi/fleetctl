# 桌面应用构建

桌面版 = Tauri 外壳 + 冻结的 Python 桥（sidecar）。桥负责设备通信，外壳只负责窗口与进程托管。

## 产物

| 平台 | 产物 | 构建位置 |
|---|---|---|
| macOS | `fleetctl.app` + `.dmg` | macOS 本机 |
| Windows | NSIS 安装包 `.exe` | **必须在 Windows 上** |

## 为什么不能交叉编译

两条硬约束：

1. **sidecar 是原生二进制**。PyInstaller 打出来的桥只能跑在构建它的系统上；Windows 版必须用 Windows 的 Python 重新冻结成 `.exe`。
2. **安装包工具链只在 Windows**。Tauri 打 Windows 安装包依赖 NSIS / WiX 与 MSVC 工具链，macOS 上无法生成。

## Windows 构建

### 前置条件

- Python 3.11+
- Rust stable（MSVC 工具链）
- Node 20+
- **Apple Mobile Device Support**（随 iTunes 安装）——`pymobiledevice3` 通过 Apple Mobile Device 服务访问 iPhone，缺了它设备列表永远是空的

### 本机构建

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-desktop-windows.ps1
```

产物：`src-tauri/target/release/bundle/nsis/`

### CI 构建

`.github/workflows/desktop-windows.yml`：

- 手动触发（Actions → Desktop (Windows) → Run workflow）
- 或推 `desktop-v*` 标签自动构建

产物以 GitHub Actions artifact `fleetctl-windows` 提供。

## macOS 构建（本机）

```bash
# 1. 冻结桥（注意 --add-data 用冒号分隔）
build/venv/bin/pyinstaller --clean --noconfirm --name fleetctl-bridge --onefile --console \
  --collect-all pymobiledevice3 --collect-all fleetctl \
  --add-data "prototype/models.json:." \
  --hidden-import pymobiledevice3.services.mobile_config \
  --hidden-import pymobiledevice3.services.diagnostics \
  --hidden-import pymobiledevice3.services.installation_proxy \
  prototype/server.py

cp dist/fleetctl-bridge src-tauri/binaries/fleetctl-bridge-aarch64-apple-darwin

# 2. 打包 .app
npx --yes @tauri-apps/cli@2 build --bundles app

# 3. 签名（证书中文名需用 SHA-1 哈希）
codesign --force --options runtime --timestamp \
  --entitlements scripts/macos-entitlements.plist \
  --sign <SHA1> "src-tauri/target/release/bundle/macos/fleetctl.app/Contents/MacOS/fleetctl-bridge"
codesign --force --options runtime --timestamp \
  --entitlements scripts/macos-entitlements.plist \
  --sign <SHA1> "src-tauri/target/release/bundle/macos/fleetctl.app"

# 4. DMG
hdiutil create -volname "fleetctl 0.5.0" \
  -srcfolder "src-tauri/target/release/bundle/macos/fleetctl.app" \
  -ov -format UDZO dist/fleetctl_0.5.0_aarch64.dmg
codesign --force --timestamp --sign <SHA1> dist/fleetctl_0.5.0_aarch64.dmg
```

`--add-data` 的分隔符在两个平台不同：macOS/Linux 用 `:`，Windows 用 `;`。

## 运行时差异

| 项目 | macOS | Windows |
|---|---|---|
| 数据目录 | `~/Library/Application Support/fleetctl/` | `%USERPROFILE%\.fleetctl\` |
| 数据库 | `fleetctl.db`（SQLite） | 同左 |
| 导出目录 | `~/Downloads` | `%USERPROFILE%\Downloads` |
| 设备驱动 | 系统自带 usbmuxd | 需 Apple Mobile Device Support |
| WebView | WKWebView | WebView2（Win10 可能需单独安装） |

桥只监听 `127.0.0.1`，不对外暴露端口。首次启动时 Windows 防火墙可能弹窗询问，允许本地访问即可。

## 已知限制

- 未做代码签名与公证，Windows SmartScreen 与 macOS Gatekeeper 都会提示未知开发者
- Windows 版尚未在真机上验证过（本轮只在 macOS 上完成构建与运行验证）
