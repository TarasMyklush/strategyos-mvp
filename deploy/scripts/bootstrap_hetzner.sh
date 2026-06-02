#!/usr/bin/env bash
set -euo pipefail

TARGET_HOST="${TARGET_HOST:?Set TARGET_HOST, for example root@1.2.3.4}"
TARGET_DIR="${TARGET_DIR:-/opt/strategyos}"
SSH_OPTS="${SSH_OPTS:-}"

ssh ${SSH_OPTS} "${TARGET_HOST}" "TARGET_DIR='${TARGET_DIR}' bash -s" <<'REMOTE'
set -euo pipefail

apt-get update
apt-get install -y ca-certificates curl gnupg rsync ufw

install -m 0755 -d /etc/apt/keyrings
if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
fi

. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

mkdir -p "${TARGET_DIR}"
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

systemctl enable docker
systemctl start docker
docker --version
docker compose version
REMOTE

echo "Bootstrap complete on ${TARGET_HOST}; target dir: ${TARGET_DIR}"
