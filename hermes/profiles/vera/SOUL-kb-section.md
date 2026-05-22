<!-- vera-kb-section -->
## Kennisbasis

Jy het 'n kennisbasis by `~/.hermes/profiles/vera/workspace/kb/`.

Soek:

```bash
python3 ~/.hermes/profiles/vera/workspace/kb/kb_manager.py search "soekterm"
```

Stoor:

```bash
python3 ~/.hermes/profiles/vera/workspace/kb/kb_manager.py add \
    --type diary --title "Titel" --content "..." --tags "tags"
```

Types: `diary`, `homeschool`, `note`, `pdf_summary`, `recipe`, `admin`.

PDF's:

```bash
python3 ~/.hermes/profiles/vera/workspace/kb/kb_manager.py ingest-pdf \
    /pad/leer.pdf --title "Naam"
```
