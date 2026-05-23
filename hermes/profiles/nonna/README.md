# Nonna — kennisbasis

SQLite FTS5-kennisbasis vir die Hermes Agent profiel **Nonna**, Clarinda se
Telegram-assistent (Afrikaans). Klein voetafdruk — net `python3` en
`sqlite3` (stdlib). PDF-pad gebruik `ocrmypdf` + `pdftotext` via
subprocess.

## Wat hierdie gids bevat

```
hermes/profiles/nonna/
  install.sh                 # rol uit na ~/.hermes/profiles/nonna/
  SOUL-kb-section.md         # word by Nonna se SOUL.md gevoeg
  workspace/kb/
    kb_manager.py            # CLI: add / search / list / show / delete / stats / ingest-pdf
    diary/  homeschool/  notes/  pdfs/originals/  pdfs/ocr/
```

## Installeer op die brein VPS

```bash
ssh brein
git -C /opt/brein-src pull --ff-only
bash /opt/brein-src/hermes/profiles/nonna/install.sh
```

Die skrip:

1. Skep `~/.hermes/profiles/nonna/workspace/kb/` met al die sub-gidse.
2. Kopieer `kb_manager.py`.
3. Voeg die KB-afdeling by `SOUL.md` (een keer — gemerk met `<!-- nonna-kb-section -->`).
4. Initialiseer die SQLite DB (`nonna_kb.db`) — skema is in `kb_manager.py`.
5. As root: installeer `tesseract-ocr {afr,eng}`, `ocrmypdf`, `poppler-utils`.

## Gebruik

Soek (Afrikaans-vriendelik — diakritiese tekens word geïgnoreer):

```bash
python3 ~/.hermes/profiles/nonna/workspace/kb/kb_manager.py search "wiskunde"
python3 ~/.hermes/profiles/nonna/workspace/kb/kb_manager.py search --type homeschool "grammatika"
```

Voeg by:

```bash
python3 ~/.hermes/profiles/nonna/workspace/kb/kb_manager.py add \
    --type diary --title "Maandag" \
    --content "Vandag was lekker. Saskia het haar somme klaargemaak." \
    --tags "dagboek week-22"
```

Vir lang inhoud, gebruik `--content-file pad/na/teks.md`.

PDF-inneem (OCR + indeks):

```bash
python3 ~/.hermes/profiles/nonna/workspace/kb/kb_manager.py ingest-pdf \
    ~/Aflaaie/CC-Cycle-2.pdf --title "CC Cycle 2 Gids" --tags "homeschool cc"
```

Ander opdragte: `list`, `show <id>`, `delete <id>`, `stats`. Almal ondersteun
`--json` waar nuttig.

## Skema

Sien `workspace/kb/kb_manager.py` — `SCHEMA` aan die bo-kant. Kortliks:

- `documents` (gewone tabel) — `id, type, title, content, source_file, tags, created_at, updated_at, metadata`.
- `documents_fts` (FTS5 virtuele tabel) — geïndekseer op `title, content, tags`.
- Drie triggers hou `documents_fts` ge-sync met `documents`.
- Tokeniser: `unicode61 remove_diacritics 2` — `kafé` en `kafe` is dieselfde
  vir die soektog.

## Voetafdruk

Op die CX22 (3.7 GB RAM): geen agtergrond-diens nie. Die DB leef as een
SQLite-lêer; `kb_manager.py` is 'n eenmaal-uitvoer-CLI. Nonna roep dit aan
wanneer sy soek of stoor — geheue-piek is minder as 'n grep.
