"""web_cmd 配置解析测试。"""

from pathlib import Path

from team_memory.commands.web_cmd import format_port_in_use_message, resolve_web_bind


def test_resolve_web_bind_from_env(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".team-memory.yml").write_text("tool: team-memory\n", encoding="utf-8")
    (root / ".env").write_text(
        "\n".join(
            [
                "WEB_HOST=0.0.0.0",
                "WEB_PORT=8765",
                "WEB_PUBLIC_URL=https://git.example.com:8765",
            ]
        ),
        encoding="utf-8",
    )

    host, port, url = resolve_web_bind(root)
    assert host == "0.0.0.0"
    assert port == 8765
    assert url == "https://git.example.com:8765"


def test_resolve_web_bind_cli_overrides_env(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".team-memory.yml").write_text("tool: team-memory\n", encoding="utf-8")
    (root / ".env").write_text("WEB_PORT=8765\n", encoding="utf-8")

    host, port, url = resolve_web_bind(root, host="127.0.0.1", port=9000)
    assert host == "127.0.0.1"
    assert port == 9000
    assert url == "http://127.0.0.1:9000"


def test_format_port_in_use_message():
    msg = format_port_in_use_message(8765, "https://git.example.com:8765")
    assert "8765" in msg
    assert "https://git.example.com:8765" in msg
