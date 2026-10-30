"""Render reviewable systemd/Nginx deployment; never changes the host itself."""

import getpass
import re
import shlex
import sys
from pathlib import Path
from urllib.parse import urlsplit


def render(root, output, *, archive_port=8791, viewer_port=8793):
    from .admin import read_instance

    root, info, _ = read_instance(root)
    output = Path(output).expanduser().absolute()
    if output.exists():
        raise ValueError("fresh deployment output required")
    user = getpass.getuser()
    if user == "root" or not re.fullmatch(r"[a-z_][a-z0-9_-]*", user):
        raise ValueError("render as a dedicated non-root application account")
    for p in (root, output, Path(sys.executable)):
        if not re.fullmatch(r"/[\w./-]+", str(p)):
            raise ValueError(
                "deployment paths must not contain spaces or shell metacharacters"
            )
    domain = urlsplit(info["public_url"]).hostname
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}", domain or ""):
        raise ValueError("valid DNS hostname required")
    output.mkdir(parents=True, mode=0o700)
    prefix = "team-memory-hub-" + domain.replace(".", "-")
    # Independent loopback ports, explicitly chosen and checked before rendering.
    import socket

    if archive_port == viewer_port or not all(
        1024 <= port <= 65535 for port in (archive_port, viewer_port)
    ):
        raise ValueError("two distinct unprivileged ports required")
    for port in (archive_port, viewer_port):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise ValueError(
                    "required loopback port in use; existing services preserved"
                ) from None

    def unit(name, command, kind="simple"):
        return f"""[Unit]
Description=Team Memory {name}
After=network-online.target
Wants=network-online.target
[Service]
Type={kind}
User={user}
UMask=0077
WorkingDirectory={root}
ExecStart={command}
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={root}
Restart={"on-failure" if kind == "simple" else "no"}
[Install]
WantedBy=multi-user.target
"""

    (output / (prefix + "-archive.service")).write_text(
        unit(
            "archive",
            f"{sys.executable} -m team_share.collaboration serve --config {root}/config.json --port {archive_port}",
        )
    )
    (output / (prefix + "-viewer.service")).write_text(
        unit(
            "viewer",
            f"{sys.executable} -m team_share.viewer serve --config {root}/viewer.json --port {viewer_port}",
        )
    )
    (output / (prefix + "-git.service")).write_text(
        unit(
            "readonly mirror",
            f"{sys.executable} -m team_share.mirror --instance {root}",
            "oneshot",
        )
    )
    (output / (prefix + "-git.timer")).write_text(
        f"[Unit]\nDescription=Team Memory mirror timer\n[Timer]\nOnBootSec=15\nOnUnitActiveSec=60\nUnit={prefix}-git.service\n[Install]\nWantedBy=timers.target\n"
    )
    acme = "/var/lib/" + prefix + "/acme"
    http = f"""server {{
 listen 80; listen [::]:80;
 server_name {domain};
 access_log off;
 location ^~ /.well-known/acme-challenge/ {{ root {acme}; }}
 location / {{ return 301 https://$host$request_uri; }}
}}
"""
    https = f"""server {{
 listen 443 ssl; listen [::]:443 ssl;
 server_name {domain};
 ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
 ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
 ssl_protocols TLSv1.2 TLSv1.3;
 access_log off;
 client_max_body_size 256k;
 location /team/ {{
   proxy_pass http://127.0.0.1:{archive_port}/;
   proxy_set_header Host $host;
   proxy_set_header X-Forwarded-For $remote_addr;
   proxy_set_header X-Forwarded-Proto https;
 }}
 location / {{
   proxy_pass http://127.0.0.1:{viewer_port};
   proxy_set_header Host $host;
   proxy_set_header X-Forwarded-For $remote_addr;
   proxy_set_header X-Forwarded-Proto https;
 }}
}}
"""
    (output / "http.conf").write_text("# team-memory-hub-managed\n" + http)
    (output / "https.conf").write_text("# team-memory-hub-managed\n" + http + https)
    apply = f"""#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || {{ echo 'Run with sudo after reviewing generated files'; exit 1; }}
source_dir={shlex.quote(str(output))}
site=/etc/nginx/sites-available/{prefix}
link=/etc/nginx/sites-enabled/{prefix}
[[ ! -e "$site" && ! -e "$link" ]] || {{ echo 'Existing site preserved; use documented upgrade procedure'; exit 1; }}
for file in "$source_dir"/{prefix}-*.service "$source_dir"/{prefix}-*.timer; do
 [[ ! -e /etc/systemd/system/$(basename "$file") ]] || {{ echo 'Existing unit preserved'; exit 1; }}
done
# No package installation or DNS changes are hidden in this script.
for command in nginx certbot systemctl curl; do command -v "$command" >/dev/null; done
# Refuse a hostname already declared by any existing vhost, even under another filename.
if nginx -T 2>/dev/null | python3 -c 'import re,sys; d=sys.argv[1]; groups=re.findall(r"server_name\\s+([^;]+);",sys.stdin.read()); sys.exit(0 if any(d in group.split() for group in groups) else 1)' {domain}; then
 echo 'Hostname already present in Nginx; existing sites preserved'; exit 1
fi
mkdir -p {acme}
rollback() {{
 rm -f "$link" "$site"
 nginx -t && systemctl reload nginx || true
 for suffix in archive.service viewer.service git.timer git.service; do
  systemctl disable --now {prefix}-$suffix >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/{prefix}-$suffix
 done
 systemctl daemon-reload
}}
trap rollback ERR
install -m 644 "$source_dir/http.conf" "$site"
ln -s "$site" "$link"
nginx -t
systemctl reload nginx
certbot certonly --webroot -w {acme} -d {domain} --non-interactive --agree-tos --register-unsafely-without-email --keep-until-expiring
install -m 644 "$source_dir/https.conf" "$site"
nginx -t
for file in "$source_dir"/{prefix}-*.service "$source_dir"/{prefix}-*.timer; do install -m 644 "$file" /etc/systemd/system/; done
systemctl daemon-reload
systemctl enable --now {prefix}-archive.service {prefix}-viewer.service {prefix}-git.timer
systemctl reload nginx
[[ $(curl --silent --show-error --output /dev/null --write-out '%{{http_code}}' https://{domain}/api/memories) == 401 ]]
[[ $(curl --silent --show-error --output /dev/null --write-out '%{{http_code}}' https://{domain}/team/api/me) == 401 ]]
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
printf '%s\\n' '#!/bin/sh' 'nginx -t && systemctl reload nginx' > /etc/letsencrypt/renewal-hooks/deploy/{prefix}.sh
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/{prefix}.sh
trap - ERR
echo 'PASS: HTTPS and anonymous access protection; real Feishu/member/model acceptance NOT_RUN'
"""
    (output / "activate.sh").write_text(apply)
    (output / "activate.sh").chmod(0o700)
    return {
        "rendered": str(output),
        "applied": False,
        "root_step": str(output / "activate.sh"),
        "ports": [archive_port, viewer_port],
        "existing_sites_changed": False,
    }
