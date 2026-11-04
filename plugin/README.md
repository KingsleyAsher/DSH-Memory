# DSH Memory 1.0.3

面向 DeepSeek Harness 的长期记忆插件。将值得复用的偏好、约束和项目事实保存为带来源的记录，在后续对话中按需召回，并支持更正、撤回、人工管理与可选知识库联动。

[English](README.md) · [简体中文](README.zh-CN.md)

## 产品与项目资料

- [项目与演进记录](PROJECT-RECORD.zh-CN.md)：设计目标、架构、阶段演进与后续方向。
- [使用说明](GUIDE.zh-CN.md)：安装、配置、记忆范围、知识库联动及排障。
- [发布说明](RELEASE.zh-CN.md)：1.0.3 的交付范围、兼容要求和验证边界。
- [版本记录](CHANGELOG.md)：公开版本的变化。

## 当前版本

当前公开版本为 **1.0.3**，插件包名为 `@local/dsh-memory`。基于此前的本地测试版整理发布，保留存储路径与预设内部标识，以延续已有数据和引用。正式版本号不代表模型提炼零错误或任意宿主版本兼容。

## 下载

- [Gitee 国内下载](https://gitee.com/KingsleyAsher/DSH-Memory/raw/main/dist/local-dsh-memory-1.0.3.tgz)
- [GitCode 国内下载](https://api.gitcode.com/api/v5/repos/KingsleyAsher/DSH-Memory/raw/dist/local-dsh-memory-1.0.3.tgz?ref=main)

插件并发检查 Gitee、GitCode 和 GitHub，按最新版本选择并优先使用国内源；镜像可能延迟，下载失败自动切换。

- [1.0.3 Release 与安装包](https://github.com/KingsleyAsher/DSH-Memory/releases/tag/v1.0.3)
- [直接下载安装包](https://github.com/KingsleyAsher/DSH-Memory/releases/download/v1.0.3/local-dsh-memory-1.0.3.tgz)
- [仓库内安装包](dist/local-dsh-memory-1.0.3.tgz) · [SHA-256 校验](dist/SHA256SUMS)

## 插件能做什么

- **主动保存**：主模型使用 `memory_submit` 提交记忆；程序检查来源、作用域和状态变更。明确的记忆请求另有确定性捕获路径。
- **按需召回**：在会话步骤前查询当前项目及全局记录，以有预算的证据补充上下文，不固定注入全部记忆。
- **同次压缩**：对支持的官方 Basic 压缩引擎，在原有压缩调用中同时生成摘要与记忆，不新增全文提炼模型调用。自定义压缩引擎需要自己的适配器。
- **管理与复核**：提供记忆列表、关系视图、手动新增和删除，以及低置信度候选的接受、编辑后接受或拒绝。关系连线不等于事实相互证明。
- **作用域**：全局记忆跨项目保留；项目记忆跟随窗口项目生命周期，切换或清理项目会删除该范围的记录。详见使用说明。
- **可选共享**：其他兼容组件存在并连接时共享；未安装时独立运行。知识库来源记录只读，原文和权限由知识库维护。

## 安装

当前声明兼容 DSH **0.2.1-rc.5**、Cordis **~4.0.5**。需要 Python **3.11+** 和 NumPy；验证环境使用 Node 24。先为插件使用的 Python 安装依赖：

```sh
python -m pip install numpy
```

在 DSH 插件管理器中添加以下安装源，或选择下载后的本地 `.tgz` 文件：

```text
https://raw.githubusercontent.com/KingsleyAsher/DSH-Memory/main/dist/local-dsh-memory-1.0.3.tgz
```

启用后打开左侧“记忆”（窄窗口可能收入“更多”）或会话中的记忆视图。宿主要求重新加载时，完全退出含托盘进程后重启。现有预设在创建或恢复智能体时接入记忆能力；也保留独立“DSH 记忆”预设。

## 数据与隐私

运行数据保存在用户自己的本地 SQLite 存储中。插件复用当前会话的主模型，因此送入会话的记忆证据遵循该模型的处理位置；选择云端模型时，这些证据会随上下文发送给该提供方。插件不启动独立提炼模型、不自动下载模型、不启用后台云端向量请求。

公开源码和安装包不包含开发者的记忆、聊天、知识库正文、账户凭据、本机路径、日志或研究运行数据。发布扫描说明见 [PUBLICATION.md](PUBLICATION.md)。

## 验证与限制

本版本提供合成数据的作用域、待确认候选及显式记忆测试，包文件清单与摘要也可核验。此前联动验证使用隔离工作进程和合成知识库，不代表真实个人资料或长期模型准确率测试。1.0.3 发布检查结果见 [发布清单](release-manifest.json)。

图像、音频和附件原文提取不在本插件内。自定义压缩引擎、复杂跨项目指代和任意长上下文质量尚无普遍保证。宿主关闭后只保留待办，不会继续后台推理。更新遵循[版本与更新规则](VERSIONING.zh-CN.md)：所有较新版本自动安装，包括跨主版本和预览版，状态仅在页内显示，无更新弹窗。此版本不提供跨设备同步。

## 源码与构建

```sh
python scripts/build_release.py
python -m unittest discover -s tests -p "test_*.py"
```

`plugin/src/` 为 DSH 接入和界面，`memory_core/` 为持久化、来源检查与召回核心。构建脚本将二者组装为插件包，不读取任何运行数据。项目沿用仓库的 [MIT 许可证](LICENSE)。
