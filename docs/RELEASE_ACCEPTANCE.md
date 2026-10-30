> Hub是独立public项目的候选源码，非旧项目升级版；[兼容分析](PRODUCTION_COMPATIBILITY.md)。继承的拆分前证据保存在validation/inherited-selfhost-candidate，本仓库新证据另列。

# v0.5.0-candidate.1 候选验收与发布门槛

日期：2026-10-30，北京时间。用户已明确：暂不具备独立飞书应用/群和第二位参与者，**先交付候选代码与教程**。不发布正式标签、不切换现有生产。

## 实现范围

已整合成员工具、team_share服务和登录网页；支持2—10人配置、管理员命令、成员停用、凭证轮换、网页密码重置、显式v1配置迁移、私有Git只读镜像、Codex/Claude摘要及唯一摘要电脑启动配置。部署向导生成可审阅的systemd/Nginx/HTTPS配置，实际启用需运维执行。

新实例无个人默认账号，随机口令至少16位。旧网页账号哈希可升级读取，不更换既有密码。公开源码不包含实例配置或认证文件。服务端与网页采用MIT，第三方声明单独保留。

## 已有证据

| 检查 | 状态与边界 |
|---|---|
| 自动化套件 | 148项通过；含原成员端和服务端测试、新增多人/撤销/备份/恢复/旧账号/摘要安全审计 |
| 新实例管理 | 2人和10人配置、增员、停用后的运行中API与网页拒绝、密码重置与凭证轮换通过 |
| 加密备份恢复 | 原始记录与账号恢复到新目录，清除旧会话并阻止重放历史消息，原实例保持不变 |
| Codex真实模型摘要 | PASS，仅合成来源；六字段结构校验及工具活动审计通过 |
| Claude Code真实模型摘要 | PASS，仅合成来源；只允许Schema输出工具，拒绝执行工具、MCP、插件、技能 |
| 真正stdio MCP→私有GitHub | PASS，独立测试库、两个人造署名，上传/同ID去重/查询/读回通过；不是两名真人，也不是模型自主触发MCP |
| 成员端干净wheel安装 | PASS，独立环境，模板/CLI验证，无个人账号 |
| 服务端干净wheel安装 | 以validation/hub-wheel.json为准；包含网页资源、无账号演示、初始化和账号备份恢复 |
| 部署脚本 | 生成配置的bash语法检查通过；未在Ubuntu真实执行Nginx/systemd/证书签发 |
| 来源与依赖 | 私有实例字面量/常见凭证扫描通过，实际依赖许可证元数据已列出；不等同于安全认证 |
| 生产保护 | 已安装成员端仍指向v0.4.2；现有HTTPS健康且匿名记忆API返回401；未执行生产部署修改 |

可重跑自动化与本地演示；真实模型测试和GitHub验证会消耗本人额度并写独立测试库，不纳入无凭证CI。`validation/`保留脱敏结果，无密码、token、原始模型日志或私人消息。

目前存在上游Starlette/httpx弃用提示；没有通过跳过测试或隐藏警告处理。未因本次整合顺手升级依赖。

## 正式发布前仍需完成

1. 在Ubuntu 24.04干净服务器执行实际部署；核查系统单位、Nginx语法、证书签发/续期、资源用量和停止回滚。
2. 独立飞书测试应用和群，由两名真实参与者完成发布、身份绑定、归档、跨人检索和原作者撤回；核对摘要与网页当前状态。
3. 成员分别在自己的Codex与Claude Code实际触发查询、主动归档与网页读回。CLI摘要可用、MCP传输可用不代替这个验收。
4. 真实电脑离线/额度失败恢复、重启续传，以及服务器/摘要电脑分别恢复的演练。
5. 将候选分支推送后运行托管CI，复核macOS/Linux与Python3.11/3.13矩阵；本地通过不写成托管CI通过。
6. 再次检查最终diff和打包内容，更新兼容矩阵与硬件实测记录后，才创建v0.5.0-candidate.1标签和正式发布说明。

双人共识卡片不是本轮共享主流程，默认关闭。若未来启用，仍需真实双人同版本确认验收；多人不自动取得共识。现有生产迁移单独安排。

## 复现验证命令

```sh
python -m pytest -q
python -m build --wheel --no-isolation
python scripts/verify-wheel.py dist/*.whl
python scripts/verify-selfhost-wheel.py dist/*.whl
python scripts/audit-distribution.py
bash -n scripts/install.sh scripts/install-server.sh deploy/viewer/activate-domain.sh deploy/viewer/sync-git.sh
```

可选真实GitHub验证：先本人创建专属私有测试库，检查脚本，再运行`python scripts/validate-selfhost-mcp.py --repo OWNER/PRIVATE_TEST_REPO --output /private/result.json`。脚本会写两条合成记录，不得对正式团队记忆库运行。
