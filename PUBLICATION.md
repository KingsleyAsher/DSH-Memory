# Publication boundaries / 公开内容边界

Only the plugin source, Python core, selected synthetic tests, release tooling, documentation, license and generated distribution files are published. The research workspace is not copied wholesale.

公开内容仅包含插件源码、Python 核心、选定的合成测试、发布工具、文档、许可证和生成的安装包。没有上传完整研究工作区。

Excluded: runtime databases, private memories, chats, knowledge documents, credentials, local configuration, logs, screenshots, developer machine paths, private bridges, model weights and research-run outputs. Public GitHub owner/repository names are intentional attribution. Synthetic test identifiers and example project paths are not personal data.

排除运行数据库、私人记忆、聊天、知识库文档、凭据、本机配置、日志、截图、开发机路径、私有桥接文件、模型权重及研究运行产物。公开 GitHub 用户名和仓库名属于署名信息；测试中的虚构项目路径不是本机数据。

The release tool checks both source text and archive members against explicit exclusions and common secret patterns. It is a bounded automated check, not a guarantee that every possible secret format can be detected. Optional core embeddings require explicit configuration; the plugin worker disables them. No developer credential fallback is distributed.

发布脚本检查公开源码与包内成员的排除规则及常见密钥形式；这是有边界的自动检查，不声称能够识别所有秘密格式。核心的可选向量能力必须显式配置，插件工作进程默认关闭该能力，不分发开发者凭据回退通道。
