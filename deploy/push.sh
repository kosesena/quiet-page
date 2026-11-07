#!/usr/bin/env bash
# Copy the repo to the VM and (re)run the setup.  Usage: deploy/push.sh root@<vm-ip>
set -euo pipefail
HOST=${1:?usage: deploy/push.sh root@<vm-ip>}
cd "$(dirname "$0")/.."
rsync -az --delete --exclude .git --exclude .venv --exclude '__pycache__' --exclude '*.blend' --exclude '*.blend1' \
  ./ "$HOST:/opt/quiet-page/"
ssh "$HOST" 'bash /opt/quiet-page/deploy/setup-vm.sh'
