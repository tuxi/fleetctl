# fleetctl 合规白皮书

> **版本**：v0.4.0 | **更新**：2026-09-28
> **适用对象**：企业 IT 管理员、合规官、安全审计人员、采购决策者

---

## 1. 执行摘要

**fleetctl** 是一款面向企业级 iOS 设备管理的合规工具包。本白皮书说明 fleetctl 的合规架构、技术边界、审计能力，以及为什么它可以在受监管的企业环境中安全使用。

**核心结论**：
- fleetctl 仅使用 Apple 官方公开 API，**不含任何漏洞利用**
- 所有破坏性操作需**显式交互确认**
- 提供**不可否认的审计证据**（擦除证书、操作日志）
- 完全符合 NIST SP 800-88 媒体清理标准

---

## 2. 技术合规边界

### 2.1 使用的公开 API

fleetctl 通过 `pymobiledevice3` 封装以下 Apple 公开服务：

| 服务 | 用途 | Apple 文档 |
|------|------|-----------|
| `lockdown` | 设备信息、配对、激活状态 | 公开协议 |
| `mobileconfig` | 云配置（MDM Enrollment）、描述文件 | Apple 公开 |
| `diagnostics` | 电池健康、硬件诊断 | Apple 公开 |
| `installation_proxy` | 已安装应用列表 | Apple 公开 |

### 2.2 明确不包含的能力

| 红线 | 说明 | fleetctl 状态 |
|------|------|--------------|
| ❌ 漏洞利用 | 内核/用户态 exploit | **无** |
| ❌ 私有 entitlement | `com.apple.private.*` | **无** |
| ❌ 越狱依赖 | palera1n / Dopamine / TrollStore | **无** |
| ❌ 灰产签名 | 泄漏证书 / 滥用企业证书 | **无** |
| ❌ 激活锁绕过 | iCloud Bypass / Activation Lock Bypass | **无** |
| ❌ 数据窃取 | 越权读取用户数据 | **无** |

### 2.3 能力边界

fleetctl **能**：
- ✅ 读取设备基础信息（序列号、机型、iOS 版本、激活状态）
- ✅ 检测擦除条件、预检三步手工门
- ✅ 合规擦除设备（等价于"抹掉所有内容和设置"）
- ✅ 生成报告、审计证据

fleetctl **不能**：
- ❌ 解除 Activation Lock（需 Apple ID）
- ❌ 绕过锁屏密码
- ❌ 读取已加密的用户数据
- ❌ 在设备未配对/未解锁时读取业务数据

---

## 3. 合规架构

### 3.1 分层设计

```
┌─────────────────────────────────────────────────┐
│  CLI 层 (main.py)                                │
│  - 交互式确认、参数校验、输出格式化                   │
├─────────────────────────────────────────────────┤
│  业务层                                          │
│  - device_detector / device_info / wipe_manager  │
│  - report_generator / usb_manager / config_writer│
├─────────────────────────────────────────────────┤
│  合规网关层                                       │
│  - 仅调用白名单 API                              │
│  - 破坏性操作强制确认                             │
│  - 审计日志记录                                  │
├─────────────────────────────────────────────────┤
│  Apple 公开 API (pymobiledevice3)                │
│  - lockdown / mobileconfig / diagnostics         │
└─────────────────────────────────────────────────┘
```

### 3.2 安全控制

| 控制项 | 实现 |
|--------|------|
| **最小权限** | 仅读必要字段，不做越权访问 |
| **显式确认** | 破坏性操作需命令行 `--confirm` + 交互式输入 `WIPE` + 3 秒倒计时 |
| **审计日志** | 所有操作含时间戳、UDID、操作类型、结果 |
| **不可否认** | 擦除生成 NIST 800-88 证书（含 SHA-256 哈希） |
| **失败安全** | API 不可用时返回错误结构，不静默失败 |

---

## 4. 审计与证据

### 4.1 擦除证书（NIST 800-88）

每次擦除可生成 JSON 证书：

```json
{
  "certificate_version": "1.0",
  "standard": "NIST SP 800-88 Rev. 1",
  "wipe_method": "full",
  "device": {
    "udid": "00008101-...",
    "serial_number": "DNPF40YQ0D9C",
    "product_type": "iPhone13,3"
  },
  "timestamps": {
    "started_at": "2026-09-28T06:00:00Z",
    "completed_at": "2026-09-28T06:05:00Z"
  },
  "result": "success",
  "verifier": "fleetctl",
  "certificate_id": "<32-byte hex>",
  "hash_algorithm": "SHA-256"
}
```

### 4.2 操作报告

```bash
fleetctl report --input results.json --format pdf --output audit.pdf
```

报告包含：设备清单、操作结果、成功率、错误分类、时间戳。

### 4.3 批量结果导出

```python
from fleetctl.usb_manager import BulkOperationManager

# JSON / CSV 导出，含汇总统计
csv_content = BulkOperationManager.export_results(results, "csv")
```

---

## 5. NIST SP 800-88 合规性

### 5.1 擦除级别对应

| NIST 定义 | fleetctl 实现 |
|-----------|--------------|
| **Clear** | iOS 无对应（不支持覆盖写） |
| **Purge** | ✅ `MobileConfigService.erase_device` - 加密擦除（销毁类密钥） |
| **Destroy** | 物理销毁（超出软件范围） |

iOS 设备的 `erase_device` 销毁加密密钥，等效于 NIST 800-88 **Purge** 级别——对现代加密存储而言是最高软件可达到的合规擦除。

### 5.2 合规声明

> fleetctl 的擦除操作通过销毁 iOS 硬件加密密钥实现数据不可恢复，符合 NIST SP 800-88 Rev. 1 对 Purge 级别的要求。

---

## 6. 数据保护

### 6.1 fleetctl 处理的数据

| 数据类型 | 处理方式 | 存储 |
|----------|----------|------|
| 设备身份信息 | 读取、临时内存 | 不持久化（除非生成报告） |
| 设备详情 | 只读 | 用户指定路径 |
| 擦除证书 | 生成 | 用户指定路径 |
| Checkpoint | 断点续传状态 | `~/.fleetctl/checkpoints/` |

### 6.2 数据不上传

fleetctl **不包含任何遥测/上传功能**。所有数据留在本地，除非用户显式导出。

### 6.3 用户数据

fleetctl **不读取**用户数据分区内容（照片、消息、应用数据）。`detect` 仅读 lockdown 基础字段。

---

## 7. 使用场景

### 7.1 推荐场景

| 场景 | 说明 |
|------|------|
| 设备退役/回收 | 批量擦除 + NIST 证书 |
| 资产盘点 | 批量读取设备信息 |
| 合规审计 | 生成审计报告 |
| 实验室重置 | 批量恢复出厂 |
| MDM 替代/补充 | 无人值守批量操作 |

### 7.2 不适用场景

| 场景 | 原因 |
|------|------|
| 激活锁绕过 | 技术/法律不允许 |
| 数据取证 | 需专用取证工具 |
| 越狱 | 违反合规红线 |
| 非授权访问 | 违反法律法规 |

---

## 8. 法律与伦理

### 8.1 合法使用前提

使用 fleetctl 擦除设备前，用户须确保：

1. **设备所有权** - 拥有设备或获得所有者明确授权
2. **数据备份** - 已备份重要数据（擦除不可逆）
3. **合规授权** - 企业设备需 IT 部门授权
4. **告知义务** - 设备使用者已知悉数据将被清除

### 8.2 免责声明

> 用户应对使用 fleetctl 的行为负责。不当使用（如擦除他人设备）可能违反法律法规。fleetctl 旨在用于合法的设备管理场景。

---

## 9. 认证与标准（路线图）

| 标准 | 状态 |
|------|------|
| NIST SP 800-88 Rev. 1 (Purge) | ✅ 已实现 |
| ISO/IEC 27001 兼容 | ✅ 支持审计日志 |
| SOC 2 Type II | ⏳ 规划中 |
| GDPR 数据最小化 | ✅ 本地处理、无遥测 |
| 中国《数据安全法》 | ✅ 数据不跨境、本地存储 |

---

## 10. 常见合规问题

### Q: fleetctl 会绕过 Activation Lock 吗？
**A**: 不会。擦除后 Activation Lock 保留，需原 Apple ID 解锁。这是 Apple 安全设计，fleetctl 不（也无法）绕过。

### Q: fleetctl 会读取用户隐私数据吗？
**A**: 不会。fleetctl 仅读 device lockdown 基础字段（序列号、机型、iOS 版本等），不触碰用户数据分区。

### Q: 擦除后数据能恢复吗？
**A**: 不能。iOS 硬件加密擦除销毁类密钥，数据不可恢复（NIST Purge 级别）。

### Q: fleetctl 会上传数据到云端吗？
**A**: 不会。fleetctl 无任何遥测/上传功能，所有处理在本地完成。

### Q: 需要 Apple 开发者账号吗？
**A**: 不需要。fleetctl 使用公开 API，无需 Apple 签名或开发者证书。

---

## 11. 合规检查清单

企业部署前核对：

- [ ] 已阅读本白皮书并理解技术边界
- [ ] 确认设备所有权/授权
- [ ] 用户已知悉数据清除
- [ ] 已备份重要数据
- [ ] 配置审计日志存储路径
- [ ] 制定擦除审批流程
- [ ] 保存擦除证书（NIST 800-88）
- [ ] 定期审计 fleetctl 使用记录

---

## 12. 联系方式

- 合规咨询: compliance@fleetctl.io
- 安全报告: security@fleetctl.io
- GitHub: https://github.com/fleetctl/fleetctl

---

> **合规红线（不可触碰）**：fleetctl 永不引入漏洞利用、私有 entitlement、越狱依赖或灰产签名。任何违反此红线的贡献将被拒绝。
