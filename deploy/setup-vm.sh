#!/usr/bin/env bash
# One-time setup of the demo on a fresh Vultr Ubuntu 24.04 VM. Run as root, after deploy/push.sh has copied the
# repo to /opt/quiet-page. Idempotent: running it again only updates.
#
#   DOMAIN   public hostname for HTTPS (default: <ip>.sslip.io, which resolves to the VM's own IP)
#   The model key goes in /etc/quiet-page.env (created here with a placeholder, never in the repo).
set -euo pipefail

APP=/opt/quiet-page
IP=$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
DOMAIN=${DOMAIN:-${IP//./-}.sslip.io}

echo "== packages"
apt-get update -qq
apt-get install -y -qq docker.io python3-venv python3-pip curl gnupg debian-keyring debian-archive-keyring apt-transport-https ufw

echo "== gVisor (runsc) as a Docker runtime"
if ! command -v runsc >/dev/null; then
  curl -fsSL https://gvisor.dev/archive.key | gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" \
    > /etc/apt/sources.list.d/gvisor.list
  apt-get update -qq && apt-get install -y -qq runsc
fi
runsc install            # registers "runsc" in /etc/docker/daemon.json
systemctl restart docker
docker pull -q python:3.13-slim
docker run --rm --runtime=runsc python:3.13-slim python -c "print('gvisor ok')"

echo "== app user and virtualenv"
id quietpage >/dev/null 2>&1 || useradd --system --home "$APP" --shell /usr/sbin/nologin quietpage
usermod -aG docker quietpage   # the app starts sandbox containers; this VM runs nothing else
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
chown -R quietpage:quietpage "$APP"

if [ ! -f /etc/quiet-page.env ]; then
  cat > /etc/quiet-page.env <<ENV
DEMO_MODEL=vultr
VULTR_INFERENCE_API_KEY=REPLACE_ME
VULTR_MODEL=qwen3.8-flash-next
SANDBOX_RUNTIME=runsc
DEMO_RAIL=braintree
BRAINTREE_ENVIRONMENT=sandbox
BRAINTREE_MERCHANT_ID=REPLACE_ME
BRAINTREE_PUBLIC_KEY=REPLACE_ME
BRAINTREE_PRIVATE_KEY=REPLACE_ME
DEMO_RATE_LIMIT=6
DEMO_DAILY_RUNS=300
ENV
fi
chmod 600 /etc/quiet-page.env && chown root:root /etc/quiet-page.env

echo "== systemd service"
cat > /etc/systemd/system/quiet-page.service <<UNIT
[Unit]
Description=The Quiet Page demo
After=docker.service network-online.target
Requires=docker.service

[Service]
User=quietpage
WorkingDirectory=$APP
EnvironmentFile=/etc/quiet-page.env
ExecStart=$APP/.venv/bin/uvicorn web.app:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=false

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now quiet-page
systemctl restart quiet-page

echo "== Caddy (HTTPS) for $DOMAIN"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq && apt-get install -y -qq caddy
fi
cat > /etc/caddy/Caddyfile <<CADDY
$DOMAIN {
  encode gzip
  reverse_proxy 127.0.0.1:8000
}
CADDY
systemctl reload caddy || systemctl restart caddy

echo "== firewall"
ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ufw --force enable >/dev/null

echo
echo "Done. https://$DOMAIN"
grep -q REPLACE_ME /etc/quiet-page.env && echo "Put the Serverless Inference key and the Braintree sandbox keys in /etc/quiet-page.env, then: systemctl restart quiet-page"
