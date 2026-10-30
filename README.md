# Agent Team Memory Hub — 可私有化部署的团队 Agent 共享记忆

面向2—10人团队：飞书归档、Coding Agent六字段主动归档、GitHub私有长期记忆，以及必须登录的可视化网页。使用团队自己的服务器、域名、飞书应用和模型账号，不依赖作者实例。

**候选版本 v0.5.0-candidate.1（Python包版本0.5.0rc1），尚未完成独立Ubuntu和真实双人飞书复刻验收。**

这是从[旧agent-team-memory](https://github.com/newlightlw/agent-team-memory)拆分的独立自托管项目。旧项目和v0.4.2安装入口继续维护，本项目不提供原地升级或自动生产迁移。新工具使用独立目录、MCP `team_memory_hub`、Skill `team-memory-hub-archive`及命令入口；[兼容分析](docs/PRODUCTION_COMPATIBILITY.md)说明差异与回滚边界。

| 入口 | 内容 |
|---|---|
| [管理员私有化部署](docs/SELF_HOSTING.md) | 系统准备、安装向导、飞书、HTTPS、成员管理、备份恢复 |
| [成员安装](docs/MEMBER_QUICKSTART.md) | Codex / Claude Code、自己的GitHub授权、查询和主动归档 |
| [安全与数据流](docs/SECURITY.md) | 哪些资料在哪处理、第三方服务、撤回与权限边界 |
| [发布验收](docs/RELEASE_ACCEPTANCE.md) | 已实现、自动化与真实验收分别记录 |
| [旧版自动归档](docs/AUTO_ARCHIVE.md) | v0.4.2固定版本说明 |

源码公开，实际团队记忆使用自己的私有数据仓库。摘要材料会发送给所选Coding工具的模型服务，自托管不等于完全离线。每个团队指定一台电脑整理飞书记忆；离线时云端继续归档，摘要等待补齐。

## 无账号演示

从本候选源码目录执行，不需要GitHub、飞书或模型账号：

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements/server.lock
.venv/bin/pip install --no-deps --no-build-isolation .
.venv/bin/python -m team_share.collaboration demo --smoke
```

预期`DEMO_ONLY`、`PASS`、真实成员确认数0。不会连接飞书、调用模型或写远端。网页及多人管理的隔离验证由测试覆盖，另需真实参与者验收。

## 能力与边界

- 现有`team_memory`成员端接口保留；`server`可选安装包含`team_share`服务和网页。
- Agent归档先整理目的、过程、结果、核心思想、应用、讨论六项，由明确指令授权上传；不自动复制全部聊天。
- 飞书原记录是来源状态的权威，Git保存版本化整理与Agent共享记录；普通归档不代表团队共识。
- 同一团队成员可读共享内容；双人确认仅为可选双人流程，多人实例不自动投票。
- 命令行管理初始化、增减成员、凭证轮换、网页账号和恢复。当前生产不会被安装器自动升级。

## 开发

```sh
python -m pip install --require-hashes -r requirements/server.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pip install pytest==9.2.0 build==1.6.1
python -m pytest -q
python -m build --wheel --no-isolation
python scripts/verify-wheel.py dist/*.whl
```

MIT许可；第三方依赖与来源见[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。此版本不加入检索算法升级、模型代理或遥测。

所有安装都使用独立虚拟环境。内部Python模块名暂沿用team_memory/team_share以保持数据协议；不要把两个项目pip安装到同一环境。


旧版接口与可选人工审核流程继续保留：[GitHub共享](docs/GITHUB_SHARING.md) · [自动归档v0.4.2](docs/AUTO_ARCHIVE.md)。
