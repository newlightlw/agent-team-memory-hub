"""支持 python -m team_memory 调用(跨平台, 不依赖 PATH 里的 team-memory 可执行)。

Windows 上 pip install 后 team-memory.exe 可能在 Scripts/ 未进 PATH,
用 `python -m team_memory <命令>` 最稳。
"""

from team_memory.cli import app

if __name__ == "__main__":
    app()
