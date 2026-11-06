# Changelog / 版本记录

## 1.0.8 — 2026-11-07

- 修复失败提交复用已锁定批次的问题；新批次重试并保留首次回答不可改写保护，补充路径字面量提示。
- 关系网标签固定位置，遮挡时虚化，移除文字避让和牵引线。
- 汇总本地 1.0.6/1.0.7：跨预设统一记忆所有者、纯净排除、微信会话作用域及模型推断风格项目存储；这些中间版本未单独公开发布。
- Fix corrected submission retries with fresh contracts; retain source validation and immutable old answers.
- Keep graph labels stationary relative to their nodes and blur occluded text.
- Consolidate cross-preset ownership, memory exclusion and optional isolated conversation/style storage.
- Synthetic validation only; installed-host upgrade and live graph appearance remain unverified.

## 1.0.5 — 2026-11-05

- 工具续步从会话历史取得真实用户任务并重新召回，防止空快照覆盖已保存约定；删除、撤回和任务切换仍生效。
- 明确当前适用的用户约定应落实到后续步骤，保持条件、权限及历史引文边界。
- 同步中英文文档、公开发布包及更新清单；保留自动更新与严格保存回执。
- Recall the current user task from session history during tool-only continuation, without accepting another plugin's user-role message as that task.
- Preserve withdrawal and scope checks; distinguish applicable user agreements from historical quotations.

## 1.0.4 — 2026-11-05

- 新增详情页：运行版本、手动检查更新、各更新源状态及 GitHub/Gitee/GitCode 仓库链接；保留自动检查和安装。
- 保存失败和部分保存明确返回工具错误；修复有唯一对应关系的原文句读差异和遗漏记录引用，保留原始响应。
- 所有 Agent 预设共享全局/项目记忆。项目切换不删除记录，同项目旧窗口记录兼容共享；页面默认全局记忆。
- Added plugin details and manual update checks without disabling automatic updates.
- Made unsuccessful writes explicit and preserved project memory across navigation with shared same-project scopes.

## 1.0.3 — 2026-11-04

- 新增 Gitee、GitCode 更新源，保持全版本自动更新与无弹窗。
- Added Gitee/GitCode sources with newest-version selection, regional preference, conflict checks and download fallback.

## 1.0.2 — 2026-11-04

- 所有较新正式版、预览版和跨主版本更新均自动安装，无需手动选择。
- All newer versions, including previews and major upgrades, install automatically.

## 1.0.1 — 2026-11-04

- 同步知识库的版本与更新规则；增加静默检查、同主版本正式更新自动安装和页内手动更新，无更新弹窗。
- Adopted knowledge-base version/update rules with silent checks, same-major stable auto-install and inline manual controls.

## 1.0.0 — 2026-11-04

- First complete public release based on the local beta implementation. / 基于本地测试版的首次完整公开发布。
- Evidence-backed capture, scoped recall, same-call compaction, manual management and candidate review. / 带来源的入档、范围召回、同次压缩、手动管理和候选复核。
- Optional knowledge-source snapshots and shared global records, with independent operation when peers are absent. / 可选知识库来源与全局记录共享，缺少其他组件时独立运行。
- Bilingual documentation, evolution records, reproducible packaging and release checksums. / 中英文文档、演进记录、可复现打包与校验摘要。
- Public files exclude private runtime data; legacy internal storage/preset IDs are retained. / 公开文件排除私人运行数据，保留原内部存储及预设标识。

Earlier beta labels describe local development stages, not additional public GitHub releases. See the project record for the engineering lineage.
