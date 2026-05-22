# Hermes — NousResearch agent on the brein Hetzner CX22

Self-improving CLI/TUI AI agent ([NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)) running alongside Open WebUI on the existing `brein` Hetzner VPS. Telegram gateway daemon so you can chat from your phone without SSH. No web UI, no DNS, no TLS — interactive use is via `hermes --tui` over SSH.

This README walks from "empty hermes repo on GitHub" to "Telegram bot replying with Claude". Copy-paste friendly.

---

## Table of contents

1. [What you'll do, in order](#what-youll-do-in-order)
2. [Phase A — Local prep](#phase-a--local-prep)
3. [Phase B — Telegram bot](#phase-b--telegram-bot)
4. [Phase C — Install on the VPS](#phase-c--install-on-the-vps)
5. [Phase D — Configure Hermes](#phase-d--configure-hermes)
6. [Phase E — Brein memory diet](#phase-e--brein-memory-diet)
7. [Verify everything works](#verify-everything-works)
8. [Day-2 ops](#day-2-ops)
9. [Troubleshooting](#troubleshooting)
10. [Memory budget](docs/memory-budget.md)

---

## What you'll do, in order

- [ ] **Phase A** — Push this repo to `marnixboersema/hermes` from your Mac.
- [ ] **Phase B** — Create a Telegram bot via `@BotFather`, grab the token and your own Telegram user ID.
- [ ] **Phase C** — SSH into brein, clone the repo, run `setup.sh`.
- [ ] **Phase D** — Switch to the `hermes` user, run `hermes setup`, paste token + allowlist into `~/.hermes/.env`, enable the gateway.
- [ ] **Phase E** — Drop brein's `mem_limit` to 2.5 GB via the supplied override file.
- [ ] **Verify** — Telegram reply, gateway healthy, brein still healthy, RAM stable.

Estimated wall time: 20–30 minutes once you have the brein SSH set up.

---

## Phase A — Local prep

You already have:
- `ssh brein` working (from brein/README Phase A).
- An empty `https://github.com/marnixboersema/hermes` repo.

If this README + the rest of the scaffold is sitting in some other working tree, sync it into the empty repo:

```bash
git clone https://github.com/marnixboersema/hermes.git ~/hermes
# copy the scaffold (e.g. from your local checkout of brein-open-webui)
cp -r ~/path/to/brein-open-webui/hermes-scaffold/. ~/hermes/
cd ~/hermes
git add .
git commit -m "Initial Hermes scaffold"
git push -u origin main
```

After this the repo on GitHub has setup.sh, .env.example, the systemd unit, etc.

---

## Phase B — Telegram bot

### B.1 Create the bot

1. Open Telegram, search `@BotFather`, start a chat.
2. Send `/newbot`. Pick a display name (e.g. `Hermes — marnix`). Pick a username ending in `bot` (e.g. `marnix_hermes_bot`).
3. BotFather replies with a token like `1234567890:AAH...`. **Save this** — it's the only time it's shown unsealed.

### B.2 Find your own Telegram user ID

The allowlist is a critical defence — without it anyone who guesses the bot username can DM it and burn your API credits.

1. In Telegram, message `@userinfobot` `/start`.
2. It replies with your ID — a 9-10 digit number. Save it.

Optionally also fetch IDs for family members you want to allow.

---

## Phase C — Install on the VPS

SSH in and clone the repo:

```bash
ssh brein
sudo apt-get update && sudo apt-get install -y git
sudo git clone https://github.com/marnixboersema/hermes.git /opt/hermes-src
sudo bash /opt/hermes-src/setup.sh
```

`setup.sh` is idempotent — safe to re-run if interrupted. It will:

- Install `git`, `ripgrep`, `ffmpeg`, and other deps the Hermes installer expects.
- Grow the swapfile from 2 GB → 4 GB if needed (you'll need extra swap with two services sharing 4 GB RAM).
- Create an unprivileged `hermes` Linux user and enable `loginctl` linger so its systemd services keep running without an SSH session.
- Install a `user-<UID>.slice` memory cap (1.5 GB hard / 1.2 GB soft) covering everything the `hermes` user runs.
- Run the official Hermes installer (`curl ... | bash`) as the `hermes` user. This installs `uv`, Python 3.11, Node 22, Playwright + Chromium.
- Template `~hermes/.hermes/.env` from `/opt/brein/.env` — pulling out `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from brein's combined `OPENAI_API_KEYS`.
- Copy `config.yaml.example` to `~hermes/.hermes/config.yaml`.
- Drop the Telegram gateway systemd unit into place (but **not** start it — token is still blank).
- Install the weekly backup cron.

Run takes ~5 minutes (most of it is Playwright/Chromium download). Output logs to `/var/log/hermes/install.log`.

---

## Phase D — Configure Hermes

### D.1 Switch to the hermes user

```bash
sudo -iu hermes
```

You're now at `hermes@brein:~$`. The `hermes` binary is on PATH (`~/.local/bin/hermes`).

### D.2 Pick the default model

```bash
hermes setup
```

The wizard will ask for a provider. Pick **Anthropic** or **OpenAI** — both keys are already in `~/.hermes/.env`. Suggested model:

- `anthropic/claude-opus-4-7` — best reasoning, billed against your Anthropic key.
- Or `openai/gpt-5-mini` — cheap, fast, fine for most chats.

The wizard writes choices to `~/.hermes/config.yaml`. Quit (`q` or Ctrl-C) when done.

### D.3 Paste the Telegram token + allowlist

```bash
nano ~/.hermes/.env
```

Fill in:

- `TELEGRAM_BOT_TOKEN=` — the token from BotFather.
- `TELEGRAM_ALLOWED_USER_IDS=` — your user ID (and any other allowed IDs, comma-separated).

Save and close.

### D.4 Enable and start the gateway

```bash
systemctl --user daemon-reload
systemctl --user enable --now hermes-gateway-telegram
systemctl --user status hermes-gateway-telegram
```

`status` should show `active (running)` and recent logs about connecting to Telegram. Tail logs if it doesn't:

```bash
journalctl --user-unit hermes-gateway-telegram -f
```

### D.5 Smoke-test from your phone

In Telegram, DM your bot:

> hi, what model are you?

Within ~5–10 seconds it should reply, referencing the model you picked in D.2.

If it doesn't reply, see [Troubleshooting](#troubleshooting).

---

## Phase E — Brein memory diet

Now that Hermes is running, lower Open WebUI's `mem_limit` so they coexist without the kernel OOM-killing the wrong one. Back as the root SSH session:

```bash
exit   # leave the hermes user, back to root@brein
sudo cp /opt/hermes-src/overlays/brein-docker-compose.override.yml \
  /opt/brein/docker-compose.override.yml
cd /opt/brein
sudo docker compose up -d
sudo docker compose ps
```

Docker reads `docker-compose.override.yml` automatically — the `mem_limit: 2.5g` takes effect on the next restart, which `up -d` triggers. Container should go `healthy` within 60s.

If brein later starts failing healthchecks under load (extremely unlikely with a family of 4), roll back:

```bash
sudo rm /opt/brein/docker-compose.override.yml
cd /opt/brein && sudo docker compose up -d
```

…and consider moving Hermes to a dedicated VPS — see [docs/memory-budget.md](docs/memory-budget.md).

---

## Verify everything works

| # | Test | How |
|---|------|-----|
| 1 | Gateway active | `sudo -iu hermes systemctl --user status hermes-gateway-telegram` → `active (running)`, no restart loops. |
| 2 | Telegram reply | DM the bot, ask "what model are you?" → reply with the configured model within ~10s. |
| 3 | Allowlist works | DM the bot from a different Telegram account (not on the allowlist) → no reply (gateway logs show the rejection). |
| 4 | Brein still healthy | `sudo docker compose -f /opt/brein/docker-compose.yml ps` → `(healthy)`. Open WebUI in browser still works. |
| 5 | TUI works | `sudo -iu hermes hermes --tui` → interactive UI opens, you can chat directly. |
| 6 | Memory headroom | `free -h` → ≥200 MB free, swap <50% used at idle. |
| 7 | Slice cap installed | `systemctl status user-$(id -u hermes).slice` → `MemoryMax: 1.5G`. |
| 8 | Backup manually | `sudo -iu hermes bash /opt/hermes-src/backup.sh && ls -lh /var/backups/hermes/` → one `.tar.gz`. |

If any of these fail, see [Troubleshooting](#troubleshooting) below.

---

## Day-2 ops

### Update Hermes

The official installer tracks `main`. Update in place:

```bash
sudo -iu hermes
hermes update                      # pulls the latest hermes-agent release
systemctl --user restart hermes-gateway-telegram
```

If an update breaks the gateway, roll back to a previous git ref:

```bash
sudo -iu hermes
cd ~/.local/share/hermes-agent     # exact path: see ~/.bashrc PATH entries
git log --oneline | head -10
git checkout <previous-sha>
systemctl --user restart hermes-gateway-telegram
```

### Rotate the Telegram bot token

If the token leaks:

1. Message `@BotFather` → `/token` → pick the bot → it issues a new token and **revokes the old one**.
2. On the VPS: `sudo -iu hermes nano ~/.hermes/.env` — paste new token.
3. `systemctl --user restart hermes-gateway-telegram`.

### Add an allowed user

Append their Telegram user ID to `TELEGRAM_ALLOWED_USER_IDS` in `~/.hermes/.env`, comma-separated. Restart the gateway.

### Disable Hermes temporarily

```bash
sudo -iu hermes systemctl --user disable --now hermes-gateway-telegram
```

The user, files, and brein override stay in place. Re-enable with `enable --now`.

### Where to monitor spend

Same dashboards as brein:
- OpenAI: https://platform.openai.com/usage
- Anthropic: https://console.anthropic.com/settings/usage

Tip: Hermes can be chatty (background skills, scheduled reports). Watch the first week's bill closely.

---

## Troubleshooting

### Gateway: `Failed to start` / restart loop

```bash
sudo -iu hermes
journalctl --user-unit hermes-gateway-telegram --since "10 minutes ago"
```

Common causes:
- `TELEGRAM_BOT_TOKEN` blank or wrong format — must be `<number>:<base64ish>`.
- `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` blank — gateway can't make model calls. Verify with:
  ```bash
  grep -E '^(OPENAI_API_KEY|ANTHROPIC_API_KEY|TELEGRAM_BOT_TOKEN)=' ~/.hermes/.env | sed 's/=.*/=<set>/'
  ```
- Network: gateway needs outbound 443 to `api.telegram.org` + provider APIs. UFW + Hetzner Cloud Firewall both default-allow outbound — no change needed.

### Bot replies to anyone

The allowlist isn't loaded. Check:
```bash
grep TELEGRAM ~/.hermes/.env
sudo -iu hermes systemctl --user show hermes-gateway-telegram | grep -i environ
```
`HERMES_TELEGRAM_USER_ALLOWLIST` must be exported (it's expanded from `TELEGRAM_ALLOWED_USER_IDS` in the .env). Restart the gateway after fixing.

### OOM-kills

```bash
journalctl -k --since "1 day ago" | grep -i 'killed process'
```

If brein keeps dying: roll back Phase E (`rm /opt/brein/docker-compose.override.yml`) and migrate Hermes to its own VPS. If Hermes keeps dying: turn off browser tools (`hermes config set browser.enabled false` then restart the gateway) — that's the biggest RAM hog.

See [docs/memory-budget.md](docs/memory-budget.md) for the full accounting.

### Hermes update broke something

```bash
sudo -iu hermes
hermes --version
# roll back via the git checkout dance described in Day-2 ops above
```

If the .env or config.yaml schema changed between versions, the install log notes them: `cat /var/log/hermes/install.log`.

### Can't find the hermes binary

```bash
ls -l /home/hermes/.local/bin/hermes
```

If missing, re-run the installer manually:
```bash
sudo -iu hermes bash -c 'curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash'
```

---

## File layout reference

On the VPS after deploy:

```
/opt/hermes-src/                       # git clone of this repo — read-only source of truth
├── setup.sh                           # idempotent bootstrap (re-runnable)
├── backup.sh                          # weekly cron target
├── crontab.txt
├── .env.example
├── config.yaml.example
├── systemd/
│   └── hermes-gateway-telegram.service
├── overlays/
│   └── brein-docker-compose.override.yml
└── docs/
    └── memory-budget.md

/home/hermes/.hermes/                  # runtime state — backed up weekly
├── .env                               # secrets — never in backups
├── config.yaml                        # model + tool config
└── memory/                            # learned skills, conversation index

/etc/systemd/system/user-<UID>.slice.d/
└── 50-hermes-memory.conf              # memory cap covering all hermes user processes

/home/hermes/.config/systemd/user/
└── hermes-gateway-telegram.service    # user-mode service unit

/var/backups/hermes/                   # weekly tar.gz, 4 most recent
└── hermes-YYYY-MM-DD.tar.gz

/var/log/hermes/                       # install + backup logs
├── install.log
└── backup.log

/opt/brein/docker-compose.override.yml # 2.5 GB mem_limit for Open WebUI
```
