#!/usr/bin/env bash
# Hermes backup — weekly tar of ~hermes/.hermes/ excluding secrets.
# Runs as the hermes user via cron (see crontab.txt).
#
# Excludes:
#   .env                 — Telegram token + API keys; recoverable from brein
#   .cache/              — uv / Playwright caches; re-downloadable
#   browser-data/*/Cache — Chromium caches inside any browser profile
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/var/backups/hermes}
HERMES_DIR=${HERMES_DIR:-$HOME/.hermes}
KEEP=${KEEP:-4}

TS=$(date +%Y-%m-%d)
DEST="$BACKUP_DIR/hermes-$TS.tar.gz"

log() { printf '[%s] %s\n' "$(date -Iseconds)" "$*"; }

if [[ ! -d "$HERMES_DIR" ]]; then
	log "No $HERMES_DIR — nothing to back up"
	exit 0
fi

mkdir -p "$BACKUP_DIR"

log "Writing $DEST"
tar czf "$DEST" \
	--exclude='.env' \
	--exclude='.cache' \
	--exclude='*/Cache' \
	--exclude='*/CachedData' \
	-C "$(dirname "$HERMES_DIR")" \
	"$(basename "$HERMES_DIR")"

log "Pruning — keep last $KEEP"
ls -1t "$BACKUP_DIR"/hermes-*.tar.gz 2>/dev/null \
	| tail -n +$((KEEP + 1)) \
	| xargs -r rm -v

log "Done. Current backups:"
ls -lh "$BACKUP_DIR"/hermes-*.tar.gz 2>/dev/null || true
