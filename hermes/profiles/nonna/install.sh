#!/usr/bin/env bash
# Installeer die Nonna kennisbasis na ~/.hermes/profiles/nonna/.
# Idempotent — kan veilig herhaal word.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${HOME}/.hermes/profiles/nonna"

log() { printf '\n\033[1;34m[nonna-kb]\033[0m %s\n' "$*"; }

log "doel: ${DEST}"
mkdir -p "${DEST}/workspace/kb"/{diary,homeschool,notes,pdfs/originals,pdfs/ocr}

log "kopieer kb_manager.py"
install -m 0755 "${SRC}/workspace/kb/kb_manager.py" "${DEST}/workspace/kb/kb_manager.py"

# SOUL.md: skep as dit ontbreek, anders voeg die KB-afdeling by (een keer).
SOUL="${DEST}/SOUL.md"
MARKER="<!-- nonna-kb-section -->"
if [[ ! -f "${SOUL}" ]]; then
  log "skep nuwe SOUL.md (slegs KB-afdeling — vul self die res in)"
  cat "${SRC}/SOUL-kb-section.md" > "${SOUL}"
elif ! grep -qF "${MARKER}" "${SOUL}"; then
  log "voeg KB-afdeling by bestaande SOUL.md"
  printf '\n' >> "${SOUL}"
  cat "${SRC}/SOUL-kb-section.md" >> "${SOUL}"
else
  log "SOUL.md het reeds KB-afdeling — slaan oor"
fi

log "initialiseer DB (idempotent)"
python3 "${DEST}/workspace/kb/kb_manager.py" stats >/dev/null

# Stelsels-afhanklikhede — slegs as ons root is. Misluk nie die heel
# installasie as apt 'n derdeparty-PPA-fout gee nie; net die OCR-stap.
if [[ $EUID -eq 0 ]]; then
  if ! command -v ocrmypdf >/dev/null 2>&1 || ! command -v pdftotext >/dev/null 2>&1; then
    log "installeer OCR-afhanklikhede (tesseract afr+eng, ocrmypdf, poppler-utils)"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y || log "waarskuwing: apt-get update het foute gegee — probeer steeds installeer"
    if ! apt-get install -y \
        tesseract-ocr tesseract-ocr-afr tesseract-ocr-eng \
        ocrmypdf poppler-utils; then
      log "waarskuwing: OCR-pakkette nie geïnstalleer nie — PDF-pad sal nie werk nie"
    fi
  else
    log "OCR-afhanklikhede reeds aanwesig"
  fi
else
  log "nie-root — slaan apt-stap oor. Loop as root vir tesseract/ocrmypdf/poppler."
fi

log "klaar"
python3 "${DEST}/workspace/kb/kb_manager.py" stats
