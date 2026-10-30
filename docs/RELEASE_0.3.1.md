# v0.3.1：Git 通道安装补丁

v0.3.0 的成员共享实现、72 项测试及四组 macOS/Linux CI 已通过。在实际成员安装时，本机 raw.githubusercontent.com 的 TLS 下载失败，而 GitHub Git HTTPS 与私有库读写可用。

本补丁增加不依赖 raw 域名的 Git 一键入口；从仓库显式运行 `scripts/install.sh` 时使用相邻 Python 安装器，下载流入口则以60秒超时从固定版本克隆安装器。不会执行当前目录里无关的 install.py。安装目录、MCP 保护、私有缓存、审核边界不变。

保留 v0.3.0 原标签，不移动已发布版本。最新安装指令见 [GitHub 共享指南](GITHUB_SHARING.md)。新增两项无账号启动测试，当前共74项测试；模板分发继续通过独立 wheel 环境验收。
