#!/usr/bin/env bash
# Brein backup — cold tar of named Docker volumes. Designed for cron.
# Keeps the 4 most recent archives per volume in /var/backups/brein/.
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/var/backups/brein}
COMPOSE_DIR=${COMPOSE_DIR:-/opt/brein}
KEEP=${KEEP:-4}

TS=$(date +%Y-%m-%d)

log() { printf '[%s] %s\n' "$(date -Iseconds)" "$*"; }

mkdir -p "$BACKUP_DIR"
cd "$COMPOSE_DIR"

log "Stopping services for cold backup"
docker compose stop open-webui waha

# Always restart, even if tar fails on either volume.
trap 'log "Restarting services (trap)"; docker compose start open-webui waha || true' EXIT

backup_volume() {
	local volume=$1 prefix=$2
	local dest="$BACKUP_DIR/${prefix}-${TS}.tar.gz"
	log "Writing $dest"
	docker run --rm \
		-v "$volume":/data:ro \
		-v "$BACKUP_DIR":/backup \
		alpine \
		tar czf "/backup/${prefix}-${TS}.tar.gz" -C / data
}

backup_volume open-webui-data brein
backup_volume waha-sessions   waha

log "Restarting services"
trap - EXIT
docker compose start open-webui waha

log "Pruning — keep last $KEEP per volume"
for prefix in brein waha; do
	ls -1t "$BACKUP_DIR/${prefix}-"*.tar.gz 2>/dev/null \
		| tail -n +$((KEEP + 1)) \
		| xargs -r rm -v
done

log "Done. Current backups:"
ls -lh "$BACKUP_DIR"/*.tar.gz 2>/dev/null || true
