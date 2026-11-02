# ADR-010：实验性 Desktop live 适配器

> Status: DECISION
> Date: 2026-11-01
> Scope: 本 fork 的独立实验；不修改上游生产 MCP 合同。

用户要求将外部发送的提示和回复即时显示在已打开的 ZCode GUI 会话中。
Observed：Windows ZCode 3.17.1 中，独立 app-server 与 Desktop 的内存会话投影不同；
仅更新任务索引或向独立 server resume 不能证明 GUI 实时更新。

本 fork 采用显式选择的、可回滚的本地 Desktop 补丁，借用已有 workspace host 的
Electron MessagePort。绑定一个 workspace/session，不启动第二个 app-server，
不编辑聊天数据库，不接管手机 remote terminal owner。仅暴露 loopback bearer 认证
的有限 HTTP 命令。发送文本使用 GUI 使用的 conversation command；读取使用有限行查询。
不把隐藏 reasoning 或任意事件 metadata 转发给调用端。

此实验位于 `experimental/desktop-live/`，不接入公共 MCP schema、Manager 的任务状态、
锁、恢复或发布流程。它不会提供与生产 Bridge 等价的并发、取消、审批或清理保证。
调用者必须单独协调同一目录的写入者，保留既有执行模式，不自动提高权限。

安装器仅接受已观测原始 ASAR 的 SHA256，生成本地备份后才替换，拒绝运行中的 ZCode，
也拒绝覆盖应用更新。不分发 ZCode 的 archive、提取源码、会话、provider 配置或凭据；
不修改 Electron fuse 或完整性保护。应用更新需要重新检查版本符号。

已验证：原型在真实 GUI 中无需导航/刷新即可显示提示、Working 和最终回复；外部可读取
相同完整可见回复。公开版进一步加入私有目录设置与输出过滤；mock/ASAR 测试覆盖相应边界。
未验证：其他 build、平台、手机端实际观看、长时间无人值守、多写入者及新版本安装 UI。
