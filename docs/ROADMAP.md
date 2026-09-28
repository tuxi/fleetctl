# fleetctl 开发路线图

> 版本：v0.2.0 | 状态：MVP 完成，进入迭代优化阶段 | 更新：2026-09-26

---

## 🎯 总体目标

构建**合规、跨平台、可商业化**的 iOS 设备管理工具包。

**核心原则**：
- ✅ 仅使用公开 API（pymobiledevice3 lockdown/mobileconfig/diagnostics）
- ❌ 无漏洞利用、无私有 entitlement、无越狱依赖
- 🔒 破坏性操作需显式 `--confirm`
- 📋 所有操作需用户明确授权

---

## 📋 里程碑规划

| 里程碑 | 版本 | 目标 | 状态 |
|--------|------|------|------|
| M1 | v0.1.0 | MVP 完成：基础 CLI、设备检测、备份解析、报告生成 | ✅ 完成 |
| M2 | v0.2.0 | **precheck 自动化**（三步手工门全自动化） | ✅ 完成 |
| M3 | v0.3.0 | 报告专业化 + 批量操作增强 | ✅ 完成 |
| M4 | v0.4.0 | 文档完善 + 打包分发 + CI/CD | 🔄 进行中 |
| M5 | v1.0.0 | 正式发布：商业化就绪 | ⏳ 规划中 |
| M6 | v0.5.0 | **macOS 支持（本机 Agent，只读 MVP）** | 🔄 进行中 |

---

## 🎯 当前冲刺：M4 - 文档 + 打包 + CI/CD（v0.4.0）

### 核心目标
完成文档体系、多平台打包、CI/CD 流水线，达到可分发、可维护、可商业化的工程标准。

### 任务分解

| 任务 | 状态 | 验收标准 |
|------|------|----------|
| **T4.1 用户手册** | ⏳ 待开始 | docs/user-guide.md 完整，含安装/配置/CLI 参考/故障排查 |
| **T4.2 API 文档** | ⏳ 待开始 | docs/api.md 完整，含所有公共类/方法/参数/返回值/示例 |
| **T4.3 合规白皮书** | ⏳ 待开始 | docs/compliance.md 完整，含合规架构/红线/审计/认证 |
| **T4.4 macOS .dmg 打包** | ⏳ 待开始 | `make dmg` 产出可签名 .dmg，含 fleetctl 二进制 |
| **T4.5 Windows .msi 打包** | ⏳ 待开始 | `make msi` 产出 .msi，含 fleetctl.exe |
| **T4.6 Linux .AppImage 打包** | ⏳ 待开始 | `make appimage` 产出 .AppImage |
| **T4.7 CI/CD 流水线** | ⏳ 待开始 | GitHub Actions: lint/type-check/test/build/release 全自动 |
| **T4.8 发布自动化** | ⏳ 待开始 | `git tag v0.4.0` 触发自动构建/签名/上传 Release |

---

## 📋 后续里程碑任务清单

### M5: v1.0.0 - 商业化就绪

### M6: v0.5.0 - macOS 支持（本机 Agent，只读 MVP）

Mac 不支持像 iPhone 那样通过 USB 管理（普通运行的 Mac 不暴露 lockdown 服务）。方案：在 Mac 本机运行 `fleetctl`，仅调用公开 macOS CLI。

| 任务 | 状态 | 验收标准 |
|------|------|----------|
| 命令执行层 + 平台守卫 | ✅ | 可注入 runner；非 macOS 明确报错 |
| Mac 盘点采集 | ✅ | 型号/序列号/芯片/macOS/SIP/Gatekeeper/FileVault/MDM/描述文件/磁盘/电池 |
| Mac 只读预检 | ✅ | SIP / FileVault / Secure Boot / MDM 注册；文本 + JSON/HTML 审计报告 |
| CLI `mac detect\|precheck\|report` | ✅ | 复用 `report_generator`（json/csv/html/pdf） |
| 测试 | ✅ | 全部 mock runner，无真实子进程 |
| **写操作（后续）** | ⏳ | 装/卸描述文件、开 FileVault、擦除 —— 需显式确认，另立阶段 |

**合规**：仅公开 CLI；只读；无 sudo；无 MDM/激活锁绕过。

---

## 🔒 合规红线（不可触碰）

| 红线 | 说明 |
|------|------|
| ❌ 无漏洞利用 | 严禁任何内核/用户态漏洞利用代码 |
| ❌ 无私有 entitlement | 严禁 `com.apple.private.*` 等私有权限 |
| ❌ 无越狱依赖 | 严禁依赖 palera1n/Dopamine/TrollStore 等越狱工具 |
| ❌ 无灰产签名 | 严禁使用泄漏的 Apple 内部证书/企业证书 |
| ✅ 仅公开 API | 仅使用 pymobiledevice3 公开的 lockdown/mobileconfig/diagnostics API |
| ✅ 显式确认 | 所有破坏性操作需 `--confirm` 显式确认 |
| ✅ 审计日志 | 所有操作记录审计日志，含时间/操作/用户/结果 |

---

## 📋 验收流程规范

> **核心原则：做一个，验一个，通过才能做下一个**

| 步骤 | 动作 | 责任人 |
|------|------|--------|
| 1 | 开发完成自测 | 开发者 |
| 2 | 运行全量测试 `pytest -q` | 开发者 |
| 3 | 提交 PR / 提交 commit | 开发者 |
| 4 | CI 自动跑测 + lint + type-check | CI 系统 |
| 5 | **人工验收**（你确认功能符合预期） | **你** |
| 6 | 合并 / 发布 | 开发者 |

> ⚠️ **未经你验收通过，不得开始下一个任务**

---

## 📅 时间箱建议

| 里程碑 | 预计工时 | 关键风险 |
|--------|----------|----------|
| M2 (precheck 自动化) | 1-2 周 | Step 2 自动化判定条件不确定 |
| M3 (报告+批量) | 2-3 周 | PDF 生成依赖 weasyprint 系统依赖复杂 |
| M4 (文档+打包+CI) | 2-3 周 | 多平台打包依赖复杂 |
| M5 (商业化) | 4-6 周 | 许可证/激活码涉及加密/安全审计 |

---

## 📌 当前行动项

| # | 任务 | 状态 | 责任人 | 截止 |
|-----|------|------|--------|------|
| 1 | 用户手册 | ⏳ 待开始 | fleetctl | — |
| 2 | API 文档 | ⏳ 待开始 | fleetctl | — |
| 3 | 合规白皮书 | ⏳ 待开始 | fleetctl | — |
| 4 | macOS .dmg 打包 | ⏳ 待开始 | fleetctl | — |
| 5 | Windows .msi 打包 | ⏳ 待开始 | fleetctl | — |
| 6 | Linux .AppImage 打包 | ⏳ 待开始 | fleetctl | — |
| 7 | CI/CD 流水线 | ⏳ 待开始 | fleetctl | — |
| 8 | 发布自动化 | ⏳ 待开始 | fleetctl | — |

---

> **下一步动作**：请提供 `spec/11` §6.1 中 Step 2 的原文（或判定条件描述），我据此实现自动化判定逻辑。