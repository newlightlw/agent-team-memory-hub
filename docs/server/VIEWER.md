> 历史模块说明；完整产品部署与当前能力以[管理员教程](../SELF_HOSTING.md)和[发布验收](../RELEASE_ACCEPTANCE.md)为准。

# 登录后的团队记忆查看页

这是项目二的只读入口，源码在 `team_share/viewer/`；不创建新的独立产品或共享数据库。界面合并飞书服务的当前原始消息与 GitHub 私有库的整理结果，支持全文搜索、来源/作者筛选、六项摘要、原文折叠、来源版本和最近七天记录分布。没有自助注册、发布、删除或团队确认按钮。

## 数据与信任边界

- 飞书 SQLite 以 `mode=ro` 打开；只读已归档的飞书 share，排除查询命令与机器人回复。
- Git 数据从确定的提交读取，排除私人、非 active、符号链接和超大文件。
- 飞书整理副本按原记录 ID 合并；来源撤回则隐藏副本，修订号不一致则先展示当前原文，等摘要追上再合并。列表最多缓存5秒，详情重新核对。
- Agent 记录来自配置的私有仓库 main，验收分支不会进入正式查看页。没有真实 Agent 记录时显示空状态，不填充合成内容。
- 账号仅能读取此团队的共享材料。网页账号不等同于 GitHub 账号，跳转 GitHub 仍需其自己的访问权限。

## 安装与配置

Python 3.11+，独立环境安装项目即可。运行依赖沿用项目锁文件，无新增前端框架、CDN 或分析服务。构建 wheel 时包含完整静态文件。

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements/runtime.lock
.venv/bin/pip install --no-deps .
```

私有配置（chmod 600，禁止入 Git）：

```json
{
  "public_url": "https://memory.example.com",
  "secure_cookie": true,
  "auth_db": "/private/viewer/auth.sqlite3",
  "feishu_db": "/private/team-data/collaboration.sqlite3",
  "git_root": "/private/viewer/git-cache",
  "repo": "YOUR_ORG/team-shared-memory"
}
```

初始化首批账号一次（必须显式指定成员，新口令至少16位）：

```sh
.venv/bin/python -m team_share.viewer init-accounts --config /private/config.json --credentials /private/initial-accounts.json --members alice bob
.venv/bin/python -m team_share.viewer serve --config /private/config.json --port 8793
```

生成两个各自独立、含大小写与数字的16位随机密码，只写入指定私有文件，不打印密码；数据库仅保存 scrypt 加盐哈希。已有账号/领取文件会拒绝覆盖，重新部署不会换密码。账号不设置到期时间；登录会话14天后需重新登录，可随时退出并在服务端撤销。

生产仅监听 `127.0.0.1`，由 Nginx HTTPS 代理。`public_url` 必须与浏览器访问的 Origin 完全相同，不能附路径。开发本机可用 `secure_cookie=false` 与 loopback HTTP，生产保持 true。浏览器只保存 HttpOnly / Secure / SameSite=Strict Cookie，不在 localStorage 保存口令或令牌。

## 私有 Git 镜像

使用**只读 deploy key**，不要复制个人 GitHub token 或飞书 publisher 凭证。`deploy/viewer/sync-git.sh` 每次只接受 fast-forward，异常保留旧快照，成功才更新 last-sync。脚本参数由环境 `TEAM_VIEWER_DATA`、`TEAM_VIEWER_KEYS`、`TEAM_VIEWER_REPO` 提供。GitHub host key 从其 TLS 认证的官方 meta API 获取，启用严格 host 校验；不要盲信 ssh-keyscan。服务通过 systemd user timer 每分钟刷新。

网页服务在云端持续运行，读取飞书原文不依赖 Mac 在线。GitHub 整理内容仍受原有上传流水线的在线和模型额度影响；界面标注 Git 最近同步时间，获取异常时明确显示来源警告。

## 域名与 HTTPS

确认 A/AAAA 指向预期主机，再由具备 root 权限的运维执行：

```sh
sudo bash deploy/viewer/activate-domain.sh memory.example.com
```

脚本只创建本查看页的 managed vhost、ACME webroot、证书和续期 reload hook；拒绝覆盖未托管的同名配置，保留旧 vhost 备份，出错回滚。HTTP 重定向 HTTPS；初次证书签发前不提供 HTTP 密码登录。完成后匿名 `/api/memories` 必须返回401。

既有 Nginx 和证书属于 root，普通 SSH 用户不能修改；此限制是操作系统权限，不是内容审核或额外的发布审批。应用和 Git 镜像用普通用户服务运行，不要求应用进程获得 root。

## 验收与回滚

- 测试：匿名列表/详情拒绝、两账号登录、Cookie、安全头、Origin/CSRF、服务端退出撤销、重启会话保持、暴力尝试限速、密码不明文入数据库、来源合并、修订与撤回。
- 网页：使用合成资料在真实浏览器验证登录、筛选、全文搜索、详情与退出；合成资料不导入生产。
- 生产：分别用两真实账号验收；账号密码只在私有文件中读取，不放到命令行、日志、源码或公开截图。
- 域名验收单独记录；服务器 loopback 通过不能当作公网 HTTPS 已通过。

停止自己的 viewer 服务和 Git timer 即可回滚查看功能；不修改/停止原飞书归档服务，不改写 Git 记忆。恢复 Nginx 时只恢复对应 managed vhost。保留 `auth_db` 即保留既有账号与登录会话；不要用新演示数据库替换生产数据库。

Git 当前文件隐藏不等于彻底抹除远端历史、克隆或备份。网页不暴露旧 Git 提交正文检索接口。
