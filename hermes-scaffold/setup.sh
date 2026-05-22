#!/usr/bin/env bash
# Hermes bootstrap — idempotent. Run as root on the existing brein CX22.
#   sudo bash /opt/hermes-src/setup.sh
#
# Mirrors brein/setup.sh idioms. Coexists with brein on the same host by:
#   - running everything Hermes-related as a dedicated `hermes` Linux user
#   - capping the hermes user's total memory via a systemd slice
#   - bumping the swapfile from 2 GB to 4 GB so Open WebUI and Hermes have
#     room to breathe under load
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
	echo "Run as root (sudo bash setup.sh)" >&2
	exit 1
fi

REPO_DIR=${REPO_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)}
HERMES_USER=${HERMES_USER:-hermes}
HERMES_HOME=/home/$HERMES_USER
BREIN_ENV=${BREIN_ENV:-/opt/brein/.env}

log() { printf '\n\033[1;34m[hermes-setup]\033[0m %s\n' "$*"; }

. /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
	log "Warning: tested on Ubuntu 24.04. Detected: ${PRETTY_NAME:-unknown}"
fi

# -----------------------------------------------------------------------------
# Base packages — most are already installed by brein/setup.sh; idempotent.
# -----------------------------------------------------------------------------
log "Refreshing apt and installing base deps"
export DEBIAN_FRONTEND=noninteractive
for i in 1 2 3 4 5; do
	apt-get update -y && break
	log "apt-get update attempt $i failed, retrying in 5s..."
	sleep 5
done
apt-get install -y ca-certificates curl jq git ripgrep ffmpeg

# -----------------------------------------------------------------------------
# Swapfile — grow from 2 GB to 4 GB. CX22 is 4 GB RAM; running brein + hermes
# + Chromium will spill into swap, and 2 GB swap is too thin.
# -----------------------------------------------------------------------------
WANT_SWAP_BYTES=$((4 * 1024 * 1024 * 1024))
CURRENT_SWAP_BYTES=$(swapon --show=SIZE --bytes --noheadings 2>/dev/null | awk '{s+=$1} END {print s+0}')
if [[ "$CURRENT_SWAP_BYTES" -lt "$WANT_SWAP_BYTES" ]]; then
	log "Resizing swap from ${CURRENT_SWAP_BYTES} B to 4 GB"
	swapoff -a || true
	rm -f /swapfile
	fallocate -l 4G /swapfile
	chmod 600 /swapfile
	mkswap /swapfile
	swapon /swapfile
	grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
	sysctl -w vm.swappiness=10 >/dev/null
else
	log "Swap already >= 4 GB"
fi

# -----------------------------------------------------------------------------
# hermes user — unprivileged, separate home for ~/.hermes state.
# -----------------------------------------------------------------------------
if ! id -u "$HERMES_USER" >/dev/null 2>&1; then
	log "Creating user $HERMES_USER"
	useradd --create-home --shell /bin/bash "$HERMES_USER"
else
	log "User $HERMES_USER already exists"
fi

# linger so systemd --user services keep running without an active SSH session
loginctl enable-linger "$HERMES_USER"

# -----------------------------------------------------------------------------
# Memory cap for the entire hermes user, via a drop-in slice file.
# Bounds gateway + TUI + Playwright/Chromium collectively. Without this the
# 4 GB CX22 will OOM under simultaneous brein + browser-using Hermes load.
# -----------------------------------------------------------------------------
log "Installing user-hermes.slice memory cap (MemoryMax=1.5G, MemoryHigh=1.2G)"
install -d -m 0755 /etc/systemd/system/user-.slice.d
HERMES_UID=$(id -u "$HERMES_USER")
cat >"/etc/systemd/system/user-${HERMES_UID}.slice.d/50-hermes-memory.conf" <<EOF
[Slice]
MemoryAccounting=yes
MemoryHigh=1.2G
MemoryMax=1.5G
EOF
systemctl daemon-reload

# -----------------------------------------------------------------------------
# Working directories.
# -----------------------------------------------------------------------------
log "Creating /var/backups/hermes and /var/log/hermes"
install -d -m 0750 -o "$HERMES_USER" -g "$HERMES_USER" /var/backups/hermes
install -d -m 0755 /var/log/hermes

# -----------------------------------------------------------------------------
# Install Hermes itself — run the official installer as the hermes user.
# `sudo -iu` gives a login shell with correct HOME/PATH; the installer writes
# to ~/.bashrc and assumes both are set.
# -----------------------------------------------------------------------------
if [[ ! -x "$HERMES_HOME/.local/bin/hermes" ]]; then
	log "Running NousResearch Hermes installer as $HERMES_USER"
	sudo -iu "$HERMES_USER" bash -c '
		set -e
		curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh \
			| bash
	' 2>&1 | tee /var/log/hermes/install.log
else
	log "Hermes already installed at $HERMES_HOME/.local/bin/hermes"
fi

# -----------------------------------------------------------------------------
# Stage .env from brein's keys + .env.example placeholders.
# brein .env has OPENAI_API_KEYS="sk-openai...;sk-ant..." (semicolon-separated,
# paired with OPENAI_API_BASE_URLS for the two endpoints). Hermes wants them
# split into OPENAI_API_KEY and ANTHROPIC_API_KEY.
# -----------------------------------------------------------------------------
HERMES_DOTENV="$HERMES_HOME/.hermes/.env"
install -d -m 0700 -o "$HERMES_USER" -g "$HERMES_USER" "$HERMES_HOME/.hermes"

if [[ ! -f "$HERMES_DOTENV" ]]; then
	log "Templating $HERMES_DOTENV"

	OPENAI_KEY=""
	ANTHROPIC_KEY=""
	if [[ -r "$BREIN_ENV" ]]; then
		# shellcheck disable=SC1090
		# read OPENAI_API_KEYS from brein .env without sourcing the whole file
		raw_keys=$(grep -E '^OPENAI_API_KEYS=' "$BREIN_ENV" | head -n1 | cut -d= -f2- | sed 's/^"//; s/"$//; s/^'\''//; s/'\''$//')
		raw_urls=$(grep -E '^OPENAI_API_BASE_URLS=' "$BREIN_ENV" | head -n1 | cut -d= -f2- | sed 's/^"//; s/"$//; s/^'\''//; s/'\''$//')

		IFS=';' read -ra _keys <<<"$raw_keys"
		IFS=';' read -ra _urls <<<"$raw_urls"
		for i in "${!_keys[@]}"; do
			k=$(echo "${_keys[$i]}" | xargs)
			u=$(echo "${_urls[$i]:-}" | xargs)
			if [[ "$u" == *anthropic* || "$k" == sk-ant-* ]]; then
				ANTHROPIC_KEY="$k"
			elif [[ "$k" == sk-* ]]; then
				OPENAI_KEY="$k"
			fi
		done
		log "Extracted OPENAI_KEY=${OPENAI_KEY:+<set>} ANTHROPIC_KEY=${ANTHROPIC_KEY:+<set>} from $BREIN_ENV"
	else
		log "Warning: $BREIN_ENV not readable; .env will have placeholder keys"
	fi

	# Build .env from template (.env.example) with substitutions
	sed \
		-e "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=${OPENAI_KEY}|" \
		-e "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${ANTHROPIC_KEY}|" \
		"$REPO_DIR/.env.example" > "$HERMES_DOTENV"
	chown "$HERMES_USER:$HERMES_USER" "$HERMES_DOTENV"
	chmod 0600 "$HERMES_DOTENV"
else
	log "$HERMES_DOTENV already exists; leaving alone"
fi

# config.yaml — non-secret defaults
HERMES_CONFIG="$HERMES_HOME/.hermes/config.yaml"
if [[ ! -f "$HERMES_CONFIG" ]]; then
	log "Templating $HERMES_CONFIG"
	install -m 0644 -o "$HERMES_USER" -g "$HERMES_USER" \
		"$REPO_DIR/config.yaml.example" "$HERMES_CONFIG"
else
	log "$HERMES_CONFIG already exists; leaving alone"
fi

# -----------------------------------------------------------------------------
# systemd --user units (gateway). Drop in but do NOT start — Telegram token
# must be pasted into ~/.hermes/.env first.
# -----------------------------------------------------------------------------
USER_UNIT_DIR="$HERMES_HOME/.config/systemd/user"
install -d -m 0755 -o "$HERMES_USER" -g "$HERMES_USER" "$USER_UNIT_DIR"
install -m 0644 -o "$HERMES_USER" -g "$HERMES_USER" \
	"$REPO_DIR/systemd/hermes-gateway-telegram.service" \
	"$USER_UNIT_DIR/hermes-gateway-telegram.service"

log "Reloading hermes user systemd"
sudo -iu "$HERMES_USER" systemctl --user daemon-reload || true

# -----------------------------------------------------------------------------
# Weekly backup cron — runs as hermes user (root cron via crontab.txt would
# expose the .env path traversal; user cron keeps least-privilege).
# -----------------------------------------------------------------------------
log "Installing weekly backup cron for $HERMES_USER"
TMP_CRON=$(mktemp)
crontab -u "$HERMES_USER" -l 2>/dev/null > "$TMP_CRON" || true
if ! grep -q '/opt/hermes-src/backup.sh' "$TMP_CRON"; then
	cat "$REPO_DIR/crontab.txt" >> "$TMP_CRON"
	crontab -u "$HERMES_USER" "$TMP_CRON"
fi
rm -f "$TMP_CRON"

log "Bootstrap complete. Next steps:"
cat <<EOF

  1. Switch to the hermes user:
       sudo -iu $HERMES_USER

  2. Configure the model provider (interactive wizard):
       hermes setup
     Pick OpenAI or Anthropic; the keys are already in ~/.hermes/.env.
     Suggested default model: anthropic/claude-opus-4-7  (or gpt-5-mini)

  3. Create a Telegram bot:
       Open Telegram, message @BotFather, /newbot, save the token.
     Then find your own Telegram user ID (DM @userinfobot, save the number).

  4. Paste the token + your user ID into ~/.hermes/.env:
       nano ~/.hermes/.env
     Set TELEGRAM_BOT_TOKEN=... and TELEGRAM_ALLOWED_USER_IDS=<your-id>.
     The allowlist is critical — without it anyone can DM your bot and burn
     your API credits.

  5. Enable + start the Telegram gateway:
       systemctl --user enable --now hermes-gateway-telegram
       systemctl --user status hermes-gateway-telegram

  6. Apply the brein memory diet (drops Open WebUI mem_limit from 3g to 2.5g):
       sudo cp /opt/hermes-src/overlays/brein-docker-compose.override.yml \\
         /opt/brein/docker-compose.override.yml
       (cd /opt/brein && sudo docker compose up -d)

  7. Sanity-check:
       free -h
       systemctl --user status hermes-gateway-telegram
       sudo docker compose -f /opt/brein/docker-compose.yml ps

EOF
