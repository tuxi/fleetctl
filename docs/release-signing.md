# 发布签名与公证

T5.4.1 的实现说明。所有签名步骤都是**环境变量门控**的：未配置证书时流水线照常产出未签名产物（用于本地开发和 fork PR），配置后自动签名、公证并校验。

---

## 各平台产物

| 平台 | 签名方式 | 产物 |
|------|----------|------|
| macOS | `codesign`（Developer ID Application + hardened runtime） | 签名的二进制和 `.dmg`，提交 Apple 公证并 staple |
| Windows | Authenticode（`signtool`） | 签名的 `.exe` 和 `.msi` |
| Linux | GPG detached signature | `*.AppImage` + `*.AppImage.asc` |

---

## GitHub Secrets

在仓库 `Settings → Secrets and variables → Actions` 配置：

| Secret | 必填 | 说明 |
|--------|------|------|
| `APPLE_CERT_P12_BASE64` | macOS 签名 | Developer ID Application 证书导出的 `.p12`，base64 编码 |
| `APPLE_CERT_PASSWORD` | macOS 签名 | `.p12` 导出密码 |
| `APPLE_SIGN_IDENTITY` | macOS 签名 | 例如 `Developer ID Application: Your Company (TEAMID)` |
| `APPLE_ID` | macOS 公证 | Apple ID |
| `APPLE_TEAM_ID` | macOS 公证 | 10 位 Team ID |
| `APPLE_APP_PASSWORD` | macOS 公证 | Apple ID 的 app-specific password |
| `WINDOWS_CERT_PFX_BASE64` | Windows 签名 | 代码签名证书 `.pfx`，base64 编码 |
| `WINDOWS_CERT_PASSWORD` | Windows 签名 | `.pfx` 密码（无密码可留空） |
| `LINUX_GPG_PRIVATE_KEY` | Linux 签名 | ASCII-armored 私钥，base64 编码 |
| `LINUX_GPG_KEY_ID` | Linux 签名 | 用于签名的 key id / 指纹 |
| `LINUX_GPG_PASSPHRASE` | 可选 | 私钥口令 |

> 证书和私钥一律不要提交到仓库；`.gitignore` 已忽略 `*.p12` / `*.pfx` / `*.asc`。

### 导出 macOS 证书

```bash
# 从登录钥匙串导出 Developer ID Application 身份为 .p12
security export -t identities -f pkcs12 -k ~/Library/Keychains/login.keychain-db \
  -o build/developer-id.p12

base64 -i build/developer-id.p12 | pbcopy   # 粘贴到 APPLE_CERT_P12_BASE64
```

### 生成 Apple app-specific password

访问 [appleid.apple.com](https://appleid.apple.com) → 登录与安全 → App 专用密码。

### 导出 GPG 私钥

```bash
gpg --export-secret-keys --armor "$LINUX_GPG_KEY_ID" | base64 | pbcopy
```

---

## 本地验证

```bash
# macOS：带签名和公证的完整流程
export FLEETCTL_SIGN_IDENTITY="Developer ID Application: Your Company (TEAMID)"
export APPLE_ID="you@example.com"
export APPLE_TEAM_ID="TEAMID"
export APPLE_APP_PASSWORD="abcd-efgh-ijkl-mnop"
make dmg

# 或使用已保存的 notarytool 凭据
xcrun notarytool store-credentials fleetctl-notary \
  --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD"
FLEETCTL_SIGN_IDENTITY="..." FLEETCTL_NOTARY_PROFILE=fleetctl-notary make dmg
```

验证产物：

```bash
codesign --verify --strict --verbose=2 dist/fleetctl
codesign --verify --strict --verbose=2 dist/*.dmg
xcrun stapler validate dist/*.dmg
spctl --assess --type open --context context:primary-signature -v dist/*.dmg
```

Windows（PowerShell）：

```powershell
$env:WINDOWS_CERT_PFX_BASE64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("build\codesign.pfx"))
$env:WINDOWS_CERT_PASSWORD = "..."
./scripts/package-windows.ps1 -Version 0.4.0
Get-AuthenticodeSignature dist\fleetctl.msi | Format-List Status, SignerCertificate
```

Linux：

```bash
export LINUX_GPG_PRIVATE_KEY="$(base64 -w0 ~/signing-key.asc)"
export LINUX_GPG_KEY_ID="ABCD1234"
make appimage
gpg --verify dist/*.AppImage.asc dist/*.AppImage
```

---

## 实现细节

- **签名顺序**（macOS）：先签二进制 → 打进 DMG → 再签 DMG → 公证 DMG → `stapler staple`。先打包后签名会导致哈希不匹配，公证必然失败。
- **hardened runtime**：公证强制要求。PyInstaller onefile 在运行时解压模块，需要 [`scripts/macos-entitlements.plist`](../scripts/macos-entitlements.plist) 中的 `allow-unsigned-executable-memory` 和 `disable-library-validation`。
- **公证结果判定**：脚本解析 `notarytool submit --output-format json` 的 `status`，只有 `Accepted` 才算通过（避免旧版 notarytool 在 `Invalid` 时仍返回 0）。
- **失败即失败**：配置了签名身份但签名、公证或校验任一步失败，脚本非零退出，CI 不会发布半成品。
- **未配置证书**：三个平台都打印提示并产出未签名产物；正式发布前请确认 Actions 日志中没有 `[i] ... unsigned`。
