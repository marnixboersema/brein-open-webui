#!/usr/bin/env bash
# install.sh — wire up the vault-sync cron + log on the brein VPS.
# Run once as root after creating the three secret files (see README.md).

set -euo pipefail

REQUIRED_SECRETS=(
  /root/.brein-github-token
  /root/.brein-owui-token
  /root/.brein-owui-collection-id
)

# Sanity: secret files present + non-empty
for f in "${REQUIRED_SECRETS[@]}"; do
  if [[ ! -s "$f" ]]; then
    echo "Missing or empty: $f"
    echo "See sync-vault/README.md for what each file should contain."
    exit 1
  fi
  chmod 600 "$f"
done

# Sanity: binaries
for bin in python3 curl git; do
  command -v "$bin" >/dev/null 2>&1 || { echo "Missing $bin in PATH"; exit 1; }
done

# Resolve script location — the cron entry needs an absolute path.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/sync-vault.py"
[[ -f "$SCRIPT" ]] || { echo "Cannot find $SCRIPT"; exit 1; }
chmod 755 "$SCRIPT"

# Cron — hourly at :17, wrapped in flock to prevent overlapping runs.
CRON_DST=/etc/cron.d/brein-vault-sync
cat > "$CRON_DST" <<EOF
# Sync studeerkamer-vault → Open WebUI Studeerkamer collection.
# Hourly at :17 past, flock to prevent overlap if a sync runs long.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
17 * * * * root flock -n /var/lock/brein-vault-sync.lock $SCRIPT >> /var/log/brein-vault-sync.log 2>&1
EOF
chmod 644 "$CRON_DST"

# Log file
mkdir -p /var/log
touch /var/log/brein-vault-sync.log
chmod 640 /var/log/brein-vault-sync.log

echo "Installed."
echo
echo "Cron entry:   $CRON_DST"
echo "Script:       $SCRIPT"
echo "Log:          /var/log/brein-vault-sync.log"
echo "Cache:        /var/lib/brein/vault-cache/"
echo "State:        /var/lib/brein/vault-sync-state.json"
echo
echo "Seed the collection now (uploads everything; takes ~5 min for ~500 notes):"
echo "  $SCRIPT"
echo
echo "After that, cron handles incremental syncs hourly at :17 past."
