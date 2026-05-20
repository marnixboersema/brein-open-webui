#!/usr/bin/env python3
"""
sync-vault.py — mirror studeerkamer-vault into the Open WebUI
"Studeerkamer" Knowledge collection on this VPS.

Reads three small config files in /root/:
  .brein-github-token       — fine-grained PAT, read access to the vault repo
  .brein-owui-token         — Open WebUI API key
  .brein-owui-collection-id — UUID of the empty Studeerkamer collection

Cache + state at /var/lib/brein/:
  vault-cache/              — git clone of the vault
  vault-sync-state.json     — { last_commit, files: { rel: { owui_id, sha256 } } }

Idempotent + cron-friendly. SHA-256 gated so unchanged files don't burn
embedding tokens. Logs to /var/log/brein-vault-sync.log.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

# --- config -----------------------------------------------------------------

REPO_URL = "https://x-access-token@github.com/marnixboersema/studeerkamer-vault.git"
ASKPASS = Path(__file__).resolve().parent / "askpass.sh"
VAULT_CACHE = Path("/var/lib/brein/vault-cache")
STATE_FILE = Path("/var/lib/brein/vault-sync-state.json")
LOG_FILE = Path("/var/log/brein-vault-sync.log")
OWUI_BASE = "http://127.0.0.1:8080"

GH_TOKEN_FILE = Path("/root/.brein-github-token")
OWUI_TOKEN_FILE = Path("/root/.brein-owui-token")
COLLECTION_ID_FILE = Path("/root/.brein-owui-collection-id")

# Top-level directories to ignore (scaffolding, not content).
SKIP_PREFIXES = (".git", ".obsidian", "_meta", "Templates")
# Only these extensions get synced.
SYNC_EXTS = (".md",)


# --- helpers ----------------------------------------------------------------


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def log(msg: str) -> None:
    line = f"[{now_iso()}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def die(msg: str) -> None:
    log(f"FATAL: {msg}")
    sys.exit(1)


def read_secret(p: Path) -> str:
    if not p.exists():
        die(f"Missing secret file: {p}. See sync-vault/README.md for setup.")
    val = p.read_text().strip()
    if not val:
        die(f"Empty secret file: {p}")
    return val


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, capture_output=True, env=env)


# --- git --------------------------------------------------------------------


def git_env() -> dict:
    """Env for git calls. GIT_ASKPASS feeds the PAT to git from a file so the
    token never appears in argv, the remote URL, or tracebacks on failure."""
    env = os.environ.copy()
    env["GIT_ASKPASS"] = str(ASKPASS)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def git_clone_or_fetch() -> str:
    """Bring the cache to origin/main HEAD. Return current SHA."""
    env = git_env()
    if not (VAULT_CACHE / ".git").exists():
        log(f"first sync — cloning vault into {VAULT_CACHE}")
        VAULT_CACHE.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--quiet", REPO_URL, str(VAULT_CACHE)], env=env)
    else:
        run(["git", "-C", str(VAULT_CACHE), "remote", "set-url", "origin", REPO_URL], env=env)
        run(["git", "-C", str(VAULT_CACHE), "fetch", "--quiet", "origin", "main"], env=env)
        run(["git", "-C", str(VAULT_CACHE), "reset", "--quiet", "--hard", "origin/main"], env=env)
    return run(["git", "-C", str(VAULT_CACHE), "rev-parse", "HEAD"]).stdout.strip()


# --- vault walking ----------------------------------------------------------


def should_sync(rel: Path) -> bool:
    if rel.parts and rel.parts[0] in SKIP_PREFIXES:
        return False
    if rel.suffix not in SYNC_EXTS:
        return False
    return True


def list_vault_files() -> dict[str, str]:
    """Return {rel_path: sha256} for every syncable file in the vault."""
    out: dict[str, str] = {}
    for p in VAULT_CACHE.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(VAULT_CACHE)
        if not should_sync(rel):
            continue
        out[str(rel)] = sha256_of(p)
    return out


def flat_filename(rel: str) -> str:
    """Vault path → flat OWUI filename. Preserves folder context as a prefix.

    'Preekstudies/2026-05-Romeine-8.md' → 'Preekstudies—2026-05-Romeine-8.md'
    """
    return rel.replace("/", "—")


# --- Open WebUI HTTP --------------------------------------------------------


def upload_file(rel: str, owui_token: str) -> str | None:
    """POST /api/v1/files/ — returns new file id or None."""
    path = VAULT_CACHE / rel
    fname = flat_filename(rel)
    try:
        result = subprocess.run(
            [
                "curl", "-sS", "--fail-with-body", "-X", "POST",
                "-H", f"Authorization: Bearer {owui_token}",
                "-F", f"file=@{path};filename={fname};type=text/markdown",
                f"{OWUI_BASE}/api/v1/files/",
            ],
            check=True, text=True, capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        log(f"  upload failed for {rel}: {(e.stderr or e.stdout or '')[:300]}")
        return None
    try:
        return json.loads(result.stdout).get("id")
    except json.JSONDecodeError:
        log(f"  upload returned non-JSON for {rel}: {result.stdout[:200]}")
        return None


def attach_file(file_id: str, collection_id: str, owui_token: str) -> bool:
    """POST /api/v1/knowledge/{cid}/file/add — true on 200."""
    try:
        subprocess.run(
            [
                "curl", "-sS", "--fail-with-body", "-X", "POST",
                "-H", f"Authorization: Bearer {owui_token}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps({"file_id": file_id}),
                f"{OWUI_BASE}/api/v1/knowledge/{collection_id}/file/add",
            ],
            check=True, text=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        log(f"  attach failed for {file_id}: {(e.stderr or e.stdout or '')[:300]}")
        return False


def delete_file(file_id: str, owui_token: str) -> bool:
    """DELETE /api/v1/files/{id} — also removes from any collection."""
    try:
        subprocess.run(
            [
                "curl", "-sS", "--fail-with-body", "-X", "DELETE",
                "-H", f"Authorization: Bearer {owui_token}",
                f"{OWUI_BASE}/api/v1/files/{file_id}",
            ],
            check=True, text=True, capture_output=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        log(f"  delete failed for {file_id}: {(e.stderr or e.stdout or '')[:300]}")
        return False


# --- main -------------------------------------------------------------------


def main() -> int:
    # Validate the GH token file exists & is non-empty. askpass.sh reads it
    # at git-call time so the token never enters argv or the URL.
    read_secret(GH_TOKEN_FILE)
    owui_token = read_secret(OWUI_TOKEN_FILE)
    collection_id = read_secret(COLLECTION_ID_FILE)

    if not ASKPASS.exists():
        die(f"askpass helper missing: {ASKPASS}")

    log("--- sync run start ---")
    current_sha = git_clone_or_fetch()
    log(f"vault HEAD: {current_sha[:7]}")

    state: dict = {"last_commit": None, "files": {}}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            log("warn: state file unreadable, starting fresh")

    if state.get("last_commit") == current_sha:
        log("no new commits since last sync — nothing to do")
        return 0

    current_files = list_vault_files()
    previous_files = state.get("files", {})

    to_upload: list[str] = []
    to_replace: list[tuple[str, str]] = []  # (rel, old_id)
    to_delete: list[tuple[str, str]] = []

    for rel, h in current_files.items():
        prev = previous_files.get(rel)
        if prev is None:
            to_upload.append(rel)
        elif prev.get("sha256") != h:
            to_replace.append((rel, prev["owui_id"]))

    for rel, meta in previous_files.items():
        if rel not in current_files:
            to_delete.append((rel, meta["owui_id"]))

    log(
        f"plan: upload={len(to_upload)} replace={len(to_replace)} "
        f"delete={len(to_delete)}"
    )

    new_files: dict[str, dict[str, str]] = dict(previous_files)

    for rel, old_id in to_delete:
        log(f"  - {rel}")
        delete_file(old_id, owui_token)
        new_files.pop(rel, None)

    for rel, old_id in to_replace:
        log(f"  ~ {rel}")
        delete_file(old_id, owui_token)
        new_id = upload_file(rel, owui_token)
        if new_id and attach_file(new_id, collection_id, owui_token):
            new_files[rel] = {"owui_id": new_id, "sha256": current_files[rel]}
        else:
            new_files.pop(rel, None)

    for rel in to_upload:
        log(f"  + {rel}")
        new_id = upload_file(rel, owui_token)
        if new_id and attach_file(new_id, collection_id, owui_token):
            new_files[rel] = {"owui_id": new_id, "sha256": current_files[rel]}

    new_state = {
        "last_commit": current_sha,
        "last_synced": now_iso(),
        "files": new_files,
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(new_state, indent=2, sort_keys=True))
    tmp.replace(STATE_FILE)

    log(f"sync complete. tracking {len(new_files)} files")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        raise
