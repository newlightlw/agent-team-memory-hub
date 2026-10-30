# 成员接入（v0.5.0-candidate.1候选）

先由管理员邀请你的GitHub账号加入团队私有记忆库并授予Write权限。接受邀请，准备Python3.11+、Git、GitHub CLI、已登录可用的Codex CLI或Claude Code。网页账号由管理员另行私下交付，不能代替GitHub授权。

使用独立候选标签，在自己的电脑执行（仅新实例试用）：

```sh
gh auth login
gh auth setup-git
bash -c 'set -e; TEAM_MEMORY_BOOTSTRAP=$(mktemp -d); cleanup(){ rm -rf "$TEAM_MEMORY_BOOTSTRAP"; }; trap cleanup EXIT; git clone --quiet --depth 1 --branch v0.5.0-candidate.1 https://github.com/newlightlw/agent-team-memory-hub.git "$TEAM_MEMORY_BOOTSTRAP/tool"; bash "$TEAM_MEMORY_BOOTSTRAP/tool/scripts/install.sh" "$@"' -- --repo YOUR_ORG/team-shared-memory --author alice --tools codex --enable-upload
```

替换`YOUR_ORG/team-shared-memory`与本人代号`alice`。Claude Code用`--tools claude`，多个客户端用`--tools codex,claude`。不指定`--enable-upload`则只读查询，不暴露主动上传工具。不能指向公开工具源码仓库。

若候选标签尚不可用，停止安装并核对GitHub发布状态；不要改装main，也不要改装旧项目。

安装会建立独立虚拟环境与只读缓存，添加`team_memory_hub` MCP和归档Skill，备份已有配置。不会安装Coding工具，不覆盖其他MCP，也不自动采集聊天。若原技能已定制，保留原件并提示人工合并。新版本安装目录独立，旧v0.4.2标签与目录保留；切换MCP后重新加载。

完全退出并重新打开客户端，开新会话后先说：

> 请检查team_memory_hub是否可用，并查询团队记忆。先不要上传，返回来源与版本。

完成实际工作后：

> 帮我归档下这次部署排障，保留目的、关键过程、结果、核心思想、以后可应用的点和未解决问题，上传到团队记忆。缺少依据写未提及。

只有返回`uploaded=true`及真实链接/版本才算成功；GitHub私有链接需要你自己的权限。云端网页通常在下一轮镜像同步后显示，不承诺即时。失败保留本机outbox，同一内容重试沿用request_id，不能反复生成新ID造成重复。

用户撤回Git当前文件不清除Git历史和其他人的克隆。模型整理会使用自己的额度，资料会发送给自己选择的模型服务。主动归档是本人署名记录，不代表其他成员确认。

## 可交给Coding Agent的安装指令

```text
请阅读固定版本的docs/MEMBER_QUICKSTART.md，帮我安装团队记忆。
数据仓库：YOUR_ORG/team-shared-memory
本人代号：alice
客户端：codex（或claude）
启用上传：--enable-upload
先检查Git、Python3.11+、gh及本人仓库写权限。保留现有配置和定制技能；
需要本人GitHub登录时提示我完成，不读取或输出凭证。
仅使用已发布固定版本；标签不存在时停止，不擅自改装main。
安装后验证工具可用，先不上传聊天，提示我重载客户端，再做本人指定的脱敏归档验收。
```

管理员教程：[SELF_HOSTING.md](SELF_HOSTING.md)。Windows未列为已验证的一键环境；首版不承诺所有兼容MCP客户端均已真实模型验收。
