# 私有化部署管理员教程（v0.5.0-candidate.1候选）

状态：独立项目的公开候选，**未完成真实双人复刻验收，不是生产迁移版本**。本文固定到候选标签v0.5.0-candidate.1，仅用于新实例或隔离试用。旧项目v0.4.2不受影响，不要把已有生产切到本项目。

## 1. 准备与数据流

标准目标：Ubuntu 24.04、非root应用账号、Python3.11+、Git、Nginx、certbot、GitHub CLI `gh`，一个指向服务器的域名，TCP80/443可达。成员端首批范围为macOS/Linux，2—10人。硬件最低配置尚无独立Ubuntu实测，不承诺“任意小服务器都能跑”。

管理员需要：自己GitHub账号下的私有数据仓库管理权、飞书自建应用发布权、服务器sudo权限。成员使用自己的GitHub账号和Codex CLI或Claude Code登录，不共享管理员token。飞书实名认证不代替应用发布及敏感消息权限审批；同租户和外部群按控制台与官方条件分别配置。

数据路径：

```text
指定飞书群 → 自有服务器SQLite原始归档
                     ↓ reader认证的archive-feed
指定成员电脑 → Codex/Claude模型整理 → 团队GitHub私有库
                     ↓                 ↓
                   六字段摘要     服务器只读Git镜像 → HTTPS登录网页
成员Coding工具 → 明确指定事项 → 六字段主动归档 ──────────┘
```

GitHub和模型服务属于第三方：自托管不代表完全离线。电脑休眠、额度不足时，服务器仍收飞书消息，摘要等待恢复。只配置**一台**摘要电脑，切换时先停旧worker；本版无跨机选主。所有有效成员可读整个团队资料；不是多租户SaaS或细粒度权限系统。

## 2. 准备专用账号和安装

管理员先用系统工具创建专用非root账号，例如`memory`，让该账号可使用自己的主目录；安装必要系统包：

```sh
sudo apt update
sudo apt install python3-venv git nginx certbot curl openssh-client
# 按GitHub CLI官方安装指引安装gh。切换到应用账号后登录自己的GitHub。
```

把`memory.example.com`的A/AAAA记录指向目标主机；没有IPv6入口时不要保留错误AAAA。已有网站保留。应用仅监听loopback；不对公网开放8791/8793。

以下从非root应用账号执行。候选标签发布后：

```sh
git clone --branch v0.5.0-candidate.1 --depth 1 https://github.com/newlightlw/agent-team-memory-hub.git "$HOME/agent-team-memory-v0.5.0-candidate.1"
cd "$HOME/agent-team-memory-v0.5.0-candidate.1"
bash scripts/install-server.sh "$HOME/.local/share/team-memory-hub-server/v0.5.0-candidate.1"
```

预期最后输出`PASS: isolated server software installed`，只证明软件安装，不证明飞书、域名或成员可用。不使用sudo运行Python服务；不要复用正在运行的虚拟环境。

为方便后续命令，可在本次终端定义：

```sh
TM_ADMIN="$HOME/.local/share/team-memory-hub-server/v0.5.0-candidate.1/venv/bin/team-memory-hub-admin"
TM_INSTANCE="$HOME/.local/share/team-memory-hub-instance"
"$TM_ADMIN" wizard "$TM_INSTANCE"
```

向导填写自己的HTTPS origin、私有数据仓库`OWNER/REPO`和2—10个不同小写英文代号。目录必须全新。生成文件权限600、目录700；账号密码只在`credentials/<member>/web.json`领取，不打印。新密码至少16位，账号不设到期时间，会话14天到期。

也可非交互初始化：

```sh
"$TM_ADMIN" init "$TM_INSTANCE" --url https://memory.example.com --repo YOUR_ORG/team-shared-memory --members alice bob
```

初始化不创建远端、不发送消息。`config.json`控制飞书身份；`viewer.json`控制网页；`instance.json`保存部署元信息。不要把该目录放进源码库。

## 3. 连接私有Git仓库

应用账号执行：

```sh
gh auth login
gh auth setup-git
"$TM_ADMIN" connect-git "$TM_INSTANCE" --create
```

已有私有库则去掉`--create`。命令验证私有性和管理员权限，空库只写记忆标记文件，然后生成该库只读deploy key；GitHub host keys从官方TLS meta接口取得，SSH严格校验。

预期`private_repo_verified=true`和`readonly_key_registered=true`。如果生成key后注册失败，已有key会保留；本人核对仓库Settings → Deploy keys，补录`.pub`文件并确认只读，再获取可信known-hosts，不能靠删除目录盲目重跑。不要使用个人可写GitHub凭证代替镜像key。

服务器初始化时的个人`gh`登录只用于创建库/注册key；后续镜像服务仅用deploy key。可在完成管理后退出服务器上的个人gh登录，不影响只读镜像。

在GitHub仓库Settings → Collaborators邀请每位成员并给Write权限，对方接受邀请。安装器不能代替此授权。

## 4. 飞书应用和身份

在飞书开发者后台创建自建应用，开启机器人。申请并发布当前所需权限：接收指定群消息、机器人发消息；若需全群归档，必须有`im:message.group_msg`，只有@消息权限时只承诺接收可达消息。

配置事件：`im.message.receive_v1`、`im.message.recalled_v1`；双人确认可选卡片事件`card.action.trigger`。新实例默认关闭确认，多人不启用。

回调地址为：

```text
https://memory.example.com/team/feishu/events
```

先在控制台准备App ID、密钥、Verification Token及Encrypt Key；将机器人加入指定群。每个人的open_id必须来自同一个应用，并由对应本人确认。

```sh
"$TM_ADMIN" configure-feishu "$TM_INSTANCE"
```

向导在本地交互终端隐藏输入密钥，不发送消息。新成员加入后重新绑定其身份。停用成员无需绑定新open_id；历史作者不更改。

回调地址验证需服务与HTTPS先启动；飞书控制台操作与下一节部署需要交替完成。`doctor`的字段齐备只说明配置完整，不能代表机器人已收到消息。正式发布应用、检查可用范围和添加机器人都需本人操作。

## 5. 生成部署配置并启用HTTPS

```sh
"$TM_ADMIN" render-deploy "$TM_INSTANCE" "$HOME/team-memory-deploy-v0.5.0-candidate.1"
```

预期`applied=false`。检查生成的systemd单位、HTTP/HTTPS配置和`activate.sh`后，由sudo运维执行：

```sh
sudo bash "$HOME/team-memory-deploy-v0.5.0-candidate.1/activate.sh"
"$TM_ADMIN" doctor "$TM_INSTANCE" --online
```

该脚本不安装系统包、不修改DNS。仅创建以本域名命名的新单位和站点；同名文件已存在就停止，不覆盖。出错撤销本次新站点/单位；已签发证书保留。其他应用不重启。证书续期使用certbot及部署reload hook；核查`systemctl status certbot.timer`。

默认端口冲突时，重新用全新输出目录生成，指定`--archive-port 18891 --viewer-port 18893`。不能重用已有进程占用的端口。

`doctor --online`验证真实TLS及匿名API返回401。打开网页用私下领取的账号登录。不要在截图、命令行或Git里展示密码。HTTP不接受登录；网页账号不等于GitHub访问权。

## 6. 成员与唯一摘要电脑

将`credentials/<member>/reader.json`只交给指定摘要运行者；普通Git归档不需要飞书publisher凭证。各成员按[成员教程](MEMBER_QUICKSTART.md)安装。

指定摘要电脑安装工具后：

```sh
"$HOME/.local/share/team-memory-hub/releases/v0.5.0-candidate.1/venv/bin/team-memory-hub-sync" configure \
 --config "$HOME/.config/team-memory-hub/feishu-sync.json" \
 --repo YOUR_ORG/team-shared-memory --team-id team-shared-memory \
 --reader /private/alice-reader.json --tool codex --binary /absolute/path/to/codex
```

Claude Code改成`--tool claude --binary /absolute/path/to/claude`。先检查兼容CLI安全选项；真正模型能力还需下一步实测。非兼容版本保持禁用。两者都禁用文件、Shell、网络检索及MCP执行工具与外部上下文；Claude仅保留结构化JSON输出工具；Claude保留本人本机认证，仅从用户settings读取白名单内的认证和模型服务环境值，不加载hooks或权限配置，Codex使用原有登录的临时私有副本并在结束后清理，不上传认证文件。

```sh
TM_PYTHON="$HOME/.local/share/team-memory-hub/releases/v0.5.0-candidate.1/venv/bin/python"
"$TM_PYTHON" -m team_memory.archive_sync --config "$HOME/.config/team-memory-hub/feishu-sync.json" --once
"$TM_PYTHON" -m team_memory.archive_setup check --config "$HOME/.config/team-memory-hub/feishu-sync.json"
```

`--once`需要真正模型额度，可能消耗token；成功返回上传条数。失败不推进已确认进度。首次会回填当前已有归档；图片/语音等只保留元数据，不声称已理解正文。

常驻前先确认没有其他摘要电脑：

```sh
"$TM_PYTHON" -m team_memory.archive_setup render-startup \
 --config "$HOME/.config/team-memory-hub/feishu-sync.json" "$HOME/.config/team-memory-hub/startup"
```

macOS：检查plist，复制到`~/Library/LaunchAgents/`后用`launchctl bootstrap gui/$(id -u) <plist绝对路径>`加载；Linux：检查私有EnvironmentFile后复制service到`~/.config/systemd/user/`，执行`systemctl --user daemon-reload`与`systemctl --user enable --now team-memory-hub-sync`。停止用对应的`launchctl bootout`或`systemctl --user disable --now`。

生成物保留当前必要代理/CA环境，可能含私密代理值，权限600，不提交Git。worker状态文件记录最近成功时间和失败类别，不写正文；本机配置、cursor/state及认证需自行私有备份，服务器备份不包含它们。

## 7. 日常管理

```sh
"$TM_ADMIN" member-add "$TM_INSTANCE" charlie
"$TM_ADMIN" configure-feishu "$TM_INSTANCE"
"$TM_ADMIN" member-disable "$TM_INSTANCE" charlie
"$TM_ADMIN" member-rotate "$TM_INSTANCE" alice
"$TM_ADMIN" account-reset "$TM_INSTANCE" alice
"$TM_ADMIN" doctor "$TM_INSTANCE" --online
```

停用会撤销reader/publisher、拒绝飞书身份并清除网页会话。仍需管理员撤销GitHub协作者权限；已有克隆无法收回。成员代号不复用，总登记上限10含停用记录。重置密码只写新的私有领取文件，不在终端打印；旧领取文件失效但需管理员自行销毁。轮换后重新交付本人新凭证。

## 8. 加密备份与新目录恢复

```sh
"$TM_ADMIN" backup "$TM_INSTANCE" "$HOME/private-backups/team-001.fernet" \
 --key-file "$HOME/private-recovery/team-001.key"
"$TM_ADMIN" restore "$HOME/private-backups/team-001.fernet" "$HOME/restored-team" \
 --key-file "$HOME/private-recovery/team-001.key"
```

备份包含SQLite一致快照、配置、网页账号和实例凭证；密钥与备份分开保存，建议离机保存密钥。只接受新路径，不覆盖现有实例。恢复会重定位配置路径、检查数据库、清除旧网页会话并阻止历史消息任务重发，不自动启动服务或改DNS。重新生成部署文件、重建只读Git镜像，确认后再切换。恢复仅用于管理员维护，不抹除GitHub历史。

备份是命令入口，本版不自动设定保留周期。管理员应设定私有定时备份及保留策略，定期做恢复演练。

## 9. 升级、回滚、卸载和排障

先备份，再安装到新的release目录。新配置为v2；旧v1可加载，显式`team-memory-hub-admin migrate /private/legacy-instance`先备份旧配置再迁移，不自动重启。旧生产不是统一instance布局时，不能直接套用管理命令；另做数据迁移演练。

升级时人工比较现有托管systemd/Nginx文件，再切换可执行路径；不要重新运行首次activate覆盖已有站点。失败先停止本版本服务，保留数据并使用升级前备份和原release恢复；新版写过的数据不能假定旧版无条件可读。

卸载：先停止本项目对应单位、摘要电脑worker，再只移除确认归属的Nginx站点/单位，检查`nginx -t`后reload。保留实例、私有库和备份，除非本人明确决定删除。成员端只移除本项目MCP项及未定制的技能；其他Coding配置保留。

排障：

- 私有库404/403：检查当前gh账号、邀请是否接受及写权限，不共享token。
- CLI安全选项不足：升级到兼容版并重新检查，不删掉安全参数绕过。
- 原文有、摘要没有：检查摘要电脑在线、额度、代理/CA和`.status.json`，不是重建数据库。
- 502：检查本域名单位及loopback端口；401未登录属预期，403登录需核对public_url与Origin。
- 飞书无消息：核查应用发布、权限、可用范围、群与身份；先让两位真人发脱敏消息。
- 撤回后Git仍有旧历史：这是Git保留边界，当前失效不等于历史彻底删除。

真实验收清单与当前状态见[发布验收](RELEASE_ACCEPTANCE.md)。

## 官方配置参考

- [GitHub CLI安装说明](https://github.com/cli/cli#installation)：系统安装及发行版说明，以官方当前内容为准。
- [飞书消息与事件权限](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1)：核对接收、撤回及机器人发送范围。
- [飞书应用类型](https://open.feishu.cn/document/home/app-types-introduction/robots-web-applications-and-mini-programs)：区分企业内自建应用与其他应用类型。
- [外部群机器人条件](https://open.feishu.cn/document/develop-robots/add-bot-to-external-group?lang=zh-CN)：不把个人实名等同于所有场景都已可用。

平台控制台和权限名称可能调整；教程步骤需结合实际应用可用范围验收，不能仅照抄权限截图。
