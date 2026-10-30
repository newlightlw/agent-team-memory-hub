"""Friendly entry points for optional self-hosted server dependencies."""


def require_server():
    try:
        import cryptography  # noqa: F401
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        raise SystemExit(
            'Server dependencies are not installed. Install agent-team-memory-hub[server] '
            'or follow docs/SELF_HOSTING.md; member-only tools remain available.'
        ) from None


def admin():
    require_server()
    from team_share.admin import main
    main()


def collaboration():
    require_server()
    from team_share.collaboration.__main__ import main
    main()
