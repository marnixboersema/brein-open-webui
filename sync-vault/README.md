# sync-vault — mirror `studeerkamer-vault` into Open WebUI

Every hour, the VPS pulls the latest `marnixboersema/studeerkamer-vault`
from GitHub and reconciles the contents into the **`Studeerkamer`**
Knowledge collection in Open WebUI. New markdown files appear, edits
replace the old version, deletions remove from the collection. SHA-256
hashes track whether a file has actually changed, so unchanged files
don't burn embedding tokens.

The Knowledge collection (not the vault, not this script) is what chats
query. Once a file is in the collection, RAG works exactly like any other
Open WebUI collection — `#Studeerkamer` in chat, or attach via paperclip,
or wrap in a Workspace Model.

## What you set up once

### 1. Empty Knowledge collection in Open WebUI

- **Workspace** → **Knowledge** → **+ Create collection**.
- Name: `Studeerkamer`.
- **Access Control: Private** (admin-only — keep out of family accounts).
- Save. Don't upload anything — the script does that.

After creating, open the collection. The URL looks like:

    https://brein.marnixboersema.co.za/workspace/knowledge/<UUID>

Copy the `<UUID>`. That's your collection ID.

### 2. Open WebUI API key

- Top-right user menu → **Settings** → **Account** → **API Keys** → **`+`**.
- Name it `vault-sync`. Copy the key — only shown once.

### 3. GitHub fine-grained PAT

- https://github.com/settings/personal-access-tokens/new
- **Resource owner**: marnixboersema.
- **Repository access**: Only select repositories → `studeerkamer-vault`.
- **Permissions**: Repository → Contents → **Read-only**.
- **Expiration**: 12 months (set a calendar reminder to rotate).
- Generate. Copy the `github_pat_…` token.

### 4. Drop the three secrets on the VPS

```bash
ssh brein
echo 'github_pat_xxxxxxx'    > /root/.brein-github-token
echo 'sk-xxxxxxxxxxxxxxxx'   > /root/.brein-owui-token
echo '<collection-uuid>'     > /root/.brein-owui-collection-id
chmod 600 /root/.brein-*
```

### 5. Pull the repo to the VPS + install

If your VPS doesn't yet have this repo:

```bash
cd /opt/brein
git -C /opt/brein-src pull --ff-only || \
  git clone https://github.com/marnixboersema/brein-open-webui.git /opt/brein-src
cp -r /opt/brein-src/sync-vault /opt/brein/
```

Then install:

```bash
cd /opt/brein/sync-vault
bash install.sh                  # validates secrets, installs cron, sets perms
./sync-vault.py                  # first run — uploads everything (~5 min for ~500 notes)
```

Open OWUI → Workspace → Knowledge → Studeerkamer. The files should be
visible. Try a query in chat with `#Studeerkamer`.

### 6. Verify cron is wired

```bash
cat /etc/cron.d/brein-vault-sync
tail -f /var/log/brein-vault-sync.log     # watch the next hourly run at :17
```

## What gets synced, what gets skipped

| Synced | Skipped |
|---|---|
| All `.md` files, any depth | `.git/`, `.obsidian/`, `_meta/`, `Templates/` |
|   | `.base`, images, PDFs, anything non-`.md` |

Folder structure is preserved in the OWUI filename via `—` so you can
still see where a note came from:

    Preekstudies/2026-05-Romeine-8.md
      ↓
    Preekstudies—2026-05-Romeine-8.md

To change filters, edit `SKIP_PREFIXES` or `SYNC_EXTS` at the top of
`sync-vault.py`.

## Troubleshooting

**Nothing in the collection after first run.**
- Check `/var/log/brein-vault-sync.log` for errors.
- Verify the UUID: `cat /root/.brein-owui-collection-id`.
- Try one file by hand to isolate the failure:
  ```bash
  curl -X POST -H "Authorization: Bearer $(cat /root/.brein-owui-token)" \
       -F "file=@/var/lib/brein/vault-cache/_DASHBOARD.md" \
       http://127.0.0.1:8080/api/v1/files/
  ```
  - `401` → wrong OWUI token.
  - `403` → token lacks permission (regenerate with full access).
  - `404` → wrong base URL or endpoint changed.

**Sync says "no new commits" but I just pushed.**
- Confirm the push landed on `main`:
  ```bash
  gh api repos/marnixboersema/studeerkamer-vault/branches/main --jq '.commit.sha'
  ```
- Force a re-pull: `rm /var/lib/brein/vault-sync-state.json` and re-run.

**Duplicate files in the collection.**
- State drifted (manual OWUI edits, restored backup, etc.).
- Reset: delete all files from the collection in the OWUI UI, then
  `rm /var/lib/brein/vault-sync-state.json` and re-run the script.

**Stop syncing.**
- `rm /etc/cron.d/brein-vault-sync` — disables cron.
- Collection stays in OWUI as-is.
- To wipe everything: delete the collection in OWUI +
  `rm -rf /var/lib/brein/vault-cache /var/lib/brein/vault-sync-state.json`.

## Cost

OpenAI `text-embedding-3-small`: ~$0.02 per 1M tokens.
A 500-note vault @ ~500 tokens/note ≈ 250k tokens ≈ **$0.005** for the
initial bulk index. Incremental edits add fractions of a cent per
changed note. The hourly cron only embeds files whose SHA changed.

## Privacy

The collection is set to **Private** in OWUI — only admin (you) can see
it in the Workspace UI. But:

- As admin, you see all users' chats in Admin Panel.
- The SQLite DB on the VPS holds embeddings + chunked text in plaintext;
  anyone with SSH root sees it.
- If you give Clarinda's account admin rights, she'd see this collection.

Don't sync the vault into a multi-user OWUI instance you don't fully
trust. For pastoral/`#prive` content specifically, the Meester-MCP path
is structurally safer (it has built-in `#prive` gating that OWUI's
Knowledge layer doesn't).
