#!/usr/bin/env bash
# Installs only this viewer's Nginx virtual host and certificate. No app credentials.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo; Nginx and TLS are root-owned.' >&2; exit 1; }
domain=${1:?Provide your own public DNS hostname}
[[ "$domain" =~ ^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}$ ]] || exit 1
file="/etc/nginx/sites-available/$domain"
link="/etc/nginx/sites-enabled/$domain"
backup="/var/backups/team-memory-viewer/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup" /var/www/team-memory-acme/.well-known/acme-challenge
chmod 700 "$backup"
if [[ -e "$file" ]]; then
  grep -q 'team-memory-viewer managed' "$file" || { echo 'Existing unmanaged vhost preserved.' >&2; exit 1; }
  cp -a "$file" "$backup/vhost"
fi
rollback() {
 if [[ -f "$backup/vhost" ]]; then cp -a "$backup/vhost" "$file"; else rm -f "$link" "$file"; fi
 nginx -t && systemctl reload nginx
 echo "Activation failed; restored previous vhost. Backup: $backup" >&2
}
trap rollback ERR
cat > "$file" <<EOF
# team-memory-viewer managed
server {
    listen 80;
    listen [::]:80;
    server_name $domain;
    location ^~ /.well-known/acme-challenge/ { root /var/www/team-memory-acme; }
    location / { return 301 https://\$host\$request_uri; }
}
EOF
ln -sfn "$file" "$link"
nginx -t
systemctl reload nginx
certbot certonly --webroot -w /var/www/team-memory-acme -d "$domain" --non-interactive --agree-tos --register-unsafely-without-email --keep-until-expiring
cat >> "$file" <<EOF
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name $domain;
    ssl_certificate /etc/letsencrypt/live/$domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$domain/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 16k;
    access_log off;
    location / {
        proxy_pass http://127.0.0.1:8793;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF
nginx -t
systemctl reload nginx
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
hook=/etc/letsencrypt/renewal-hooks/deploy/team-memory-viewer-reload.sh
if [[ -e "$hook" ]] && ! grep -q 'team-memory-viewer managed' "$hook"; then
    echo 'Existing unmanaged renewal hook preserved.' >&2
    exit 1
fi
cat > "$hook" <<'HOOK'
#!/bin/sh
# team-memory-viewer managed
/usr/sbin/nginx -t && /bin/systemctl reload nginx
HOOK
chmod 755 "$hook"
trap - ERR
code=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "https://$domain/api/memories")
[[ "$code" == 401 ]] || { echo "Expected protected API HTTP 401; got $code" >&2; exit 1; }
echo "PASS: https://$domain/ ; protected memories API returns 401."
echo "Vhost backup: $backup"
