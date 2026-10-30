import argparse
import json
from pathlib import Path
from .auth import Accounts


def main():
    p = argparse.ArgumentParser(description='Authenticated read-only Feishu + Agent memory viewer')
    p.add_argument('command', choices=['init-accounts', 'serve'])
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--credentials', type=Path)
    p.add_argument('--members', nargs='+', required=False)
    p.add_argument('--port', type=int, default=8793)
    args = p.parse_args()
    if args.config.is_symlink() or args.config.stat().st_mode & 0o077:
        raise SystemExit('Use a private regular configuration file (chmod 600)')
    config = json.loads(args.config.read_text())
    if args.command == 'init-accounts':
        if not args.credentials:
            raise SystemExit('--credentials private output file required')
        if not args.members:
            raise SystemExit('--members required; no default accounts')
        names = Accounts(config['auth_db']).create(args.members, args.credentials)
        print(json.dumps({'created': names, 'passwords_printed': False, 'expires': 'never'}))
    else:
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(config), host='127.0.0.1', port=args.port, access_log=False, forwarded_allow_ips='127.0.0.1')


if __name__ == '__main__':
    main()
