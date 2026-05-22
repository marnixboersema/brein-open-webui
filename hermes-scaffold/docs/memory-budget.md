# Memory budget — shared CX22 (4 GB RAM)

You chose to run Hermes on the same Hetzner CX22 as brein/Open WebUI. The box has 4 GB RAM and (after this setup) 4 GB swap. Here's exactly how the budget is enforced.

## Steady-state target

| Component | Cap | Mechanism | Notes |
|---|---|---|---|
| Open WebUI (`brein-open-webui` container) | 2.5 GB | `mem_limit` in `docker-compose.override.yml` | Was 3 GB. Idle ~600 MB, ingest can spike to ~2 GB. |
| Hermes user (everything `hermes` runs) | 1.5 GB hard / 1.2 GB soft | `user-<UID>.slice` MemoryMax/MemoryHigh | Set by `setup.sh`. Covers gateway + TUI + Playwright + Chromium combined. |
| Hermes Telegram gateway (per-service) | 1.0 GB hard / 768 MB soft | unit `MemoryMax` / `MemoryHigh` | Inside the user slice. Gateway alone idles ~150-300 MB. |
| Caddy + Docker daemon + fail2ban + systemd + kernel | ~400 MB | (best-effort) | Roughly Ubuntu baseline. |
| Swap | 4 GB | `/swapfile` | `vm.swappiness=10`, so the kernel prefers RAM until it really has to swap. |

**Sum of caps**: 2.5 (brein) + 1.5 (hermes user) + 0.4 (system) ≈ **4.4 GB** — i.e. caps slightly exceed physical RAM. Under simultaneous peak this leans on swap. That is by design: swap absorbs spikes; the caps prevent runaway processes from killing the wrong neighbour.

## What happens when limits hit

- **Hermes user hits 1.2 GB (soft)**: the kernel starts reclaiming pages from this slice first. Slowness, no kills.
- **Hermes user hits 1.5 GB (hard)**: kernel kills the most memory-heavy process in the slice. Usually a Chromium tab. Gateway restarts automatically (`Restart=on-failure`).
- **Open WebUI hits 2.5 GB**: container OOM-killed; Docker restarts it (`restart: unless-stopped`). Active chat sessions get a connection error and need refresh.
- **Total memory + swap exhausted**: global OOM killer picks a victim by score; usually Chromium, sometimes Open WebUI. Symptoms: brein web UI hangs, gateway unresponsive.

## Watching it

```bash
# RAM + swap at a glance
free -h

# Per-slice usage
systemctl status user-$(id -u hermes).slice
docker stats --no-stream brein-open-webui

# Recent OOM events
journalctl -k --since "1 day ago" | grep -i 'killed process\|out of memory'

# Hermes gateway-specific
sudo -iu hermes systemctl --user status hermes-gateway-telegram
sudo -iu hermes journalctl --user-unit hermes-gateway-telegram --since "1 hour ago"
```

## When to bail to a separate VPS

If you see any of these for a week running:
- Daily OOM-kills of Open WebUI or the Hermes gateway.
- `free -h` showing >2 GB swap in use during normal interactive use (not just backups).
- Open WebUI request latency >5s on cached prompts.

Provision a fresh CX22 (or CX32, 8 GB, ~€7/mo) for Hermes alone. Steps:
1. `sudo systemctl --user --machine=hermes@ disable --now hermes-gateway-telegram`
2. `bash /opt/hermes-src/backup.sh` — capture the latest skills/memory.
3. `scp /var/backups/hermes/hermes-YYYY-MM-DD.tar.gz` to the new VPS.
4. Run `setup.sh` on the new VPS (drop the brein-env-reading lines or pass `BREIN_ENV=/dev/null` and paste keys manually).
5. Restore the tarball into `~hermes/.hermes/`.
6. Remove the `/opt/brein/docker-compose.override.yml` on the old CX22 to give Open WebUI its 3 GB back.
