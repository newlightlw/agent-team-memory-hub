# 与现有线上版本的兼容分析

结论：**部分读协议兼容，不是可原地覆盖的升级版本。** 因此自托管产品独立为`newlightlw/agent-team-memory-hub`，旧`newlightlw/agent-team-memory`及v0.4.2标签保持不变。

分析日期2026-10-30；只读核对了当前部署单位、配置结构及账号表字段，没有复制生产数据库、token、open_id、密码或个人配置。合成回放结果见`validation/compatibility-probe.json`。

| 层面 | 判断 | 依据与处理 |
|---|---|---|
| Git记忆Markdown、六字段归档 | 基本兼容 | 原格式、作者与来源语义保留；不因新项目自动复制现有团队数据 |
| MCP工具参数 | 保留 | search/get/list/archive的主要入参保留；Hub注册名称独立，防止切走旧客户端 |
| 旧服务配置→新代码 | 部分兼容读取 | 缺省config_version视为v1，旧成员字段可读取；这不代表整套部署可迁移 |
| 新配置→旧代码 | 不兼容 | v2及active等字段不能被旧成员/配置解析器读取；需升级前备份，不能仅回滚代码 |
| 管理目录布局 | 不兼容原地套用 | 线上服务与网页配置分散，新管理器需要统一instance.json/config.json/viewer.json及credentials目录 |
| 网页账号 | 旧密码可读，写入回滚不兼容 | 新版添加active列；旧程序的三列INSERT在新版表上失败。不能对生产库直接试跑新Accounts |
| 初始化命令 | 有变化 | 新网页初始化显式要求成员，取消固定个人账号，随机密码策略改变 |
| Codex摘要 | 版本要求更严格 | 必需安全标志先探测，不兼容CLI保持禁用，不能假定旧任意CLI均可运行 |
| 部署与运维 | 不能直接替换 | 独立虚拟环境、服务单位、端口、域名及回调；部署器遇到已有端口/站点停止 |

## 安装隔离

| 项目 | 旧稳定工具 | 新Hub |
|---|---|---|
| GitHub | agent-team-memory | agent-team-memory-hub |
| Python distribution | team-memory | agent-team-memory-hub |
| 默认release/cache | ~/.local/share/team-memory/ | ~/.local/share/team-memory-hub/ |
| 私有outbox/备份 | ~/.config/team-memory/ | ~/.config/team-memory-hub/ |
| MCP | team_memory_github | team_memory_hub |
| 安装器创建的全局包装命令 | team-memory-github | team-memory-hub |
| 归档技能 | team-memory-archive | team-memory-hub-archive |
| 摘要电脑启动任务 | local.team-memory.sync / team-memory-sync | local.team-memory-hub.sync / team-memory-hub-sync |

内部Python模块暂沿用team_memory/team_share。**必须使用独立虚拟环境，禁止在生产环境内pip覆盖或将两个distribution混装到一个环境。** 新MCP配置只操作Hub项，保留旧MCP和定制技能；若同时连接两套团队而用户未明确归档目标，先确认目标，不自动切换。

服务器端口默认仍为8791/8793；这只是新主机默认值，同机已有服务会被拒绝，不会自动停止。隔离试用时必须选择空闲端口、独立域名/配置/数据库，不能复用生产飞书回调。

## 当前生产与发布边界

本次不修改旧仓库main、旧标签、生产服务、域名、回调或成员本机配置。新仓库公开的是候选源码，不发布生产迁移指令，不以新代码测试通过声称旧系统已升级。

未来迁移需单独设计：备份原配置与SQLite，离线副本演练账号/作者/修订/撤回，安排维护窗口，显式切换与回滚。回滚使用升级前数据库和配置，不让旧代码直接写新版账号表。
