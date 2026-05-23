#!/usr/bin/env python3
# Nonna KB — SQLite FTS5 kennisbasis vir die Hermes Agent profiel "nonna".
# Stdlib only. PDF-paaie roep ocrmypdf en pdftotext via subprocess aan.

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent
DB_PATH = KB_DIR / "nonna_kb.db"
PDF_ORIG = KB_DIR / "pdfs" / "originals"
PDF_OCR = KB_DIR / "pdfs" / "ocr"

VALID_TYPES = {"diary", "homeschool", "note", "pdf_summary", "recipe", "admin"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_file TEXT,
    tags TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    metadata TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title, content, tags,
    content=documents,
    content_rowid=id,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, title, content, tags)
    VALUES (new.id, new.title, new.content, new.tags);
END;

CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, content, tags)
    VALUES('delete', old.id, old.title, old.content, old.tags);
END;

CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, content, tags)
    VALUES('delete', old.id, old.title, old.content, old.tags);
    INSERT INTO documents_fts(rowid, title, content, tags)
    VALUES (new.id, new.title, new.content, new.tags);
END;
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def die(msg, code=1):
    print(f"fout: {msg}", file=sys.stderr)
    sys.exit(code)


def validate_type(t):
    if t not in VALID_TYPES:
        die(f"onbekende tipe '{t}'. Geldig: {', '.join(sorted(VALID_TYPES))}")
    return t


# FTS5 MATCH gebruik 'n eie sintaks. Aanhalings en quotes maak gebruikersinvoer
# veilig vir tipiese soektog terwyl operatore (AND/OR/NOT) steeds werk wanneer
# die gebruiker hulle eksplisiet skryf. Eenvoudige reël: as die query reeds 'n
# operator of aanhalingsteken bevat, los hom soos hy is; anders splits in terme
# en quote elkeen.
_FTS_OPERATORS = re.compile(r'[\"\(\)\*\:]|\b(AND|OR|NOT|NEAR)\b')


def to_fts_query(raw):
    raw = raw.strip()
    if not raw:
        return ""
    if _FTS_OPERATORS.search(raw):
        return raw
    parts = [p for p in re.split(r"\s+", raw) if p]
    return " ".join('"' + p.replace('"', '""') + '"' for p in parts)


def cmd_add(args):
    validate_type(args.type)
    if not args.content and not args.content_file:
        die("--content of --content-file is verplig")
    content = args.content
    if args.content_file:
        content = Path(args.content_file).read_text(encoding="utf-8")
    metadata = None
    if args.metadata:
        try:
            json.loads(args.metadata)
            metadata = args.metadata
        except json.JSONDecodeError as e:
            die(f"--metadata moet JSON wees: {e}")

    conn = connect()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO documents (type, title, content, source_file, tags, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (args.type, args.title, content, args.source_file, args.tags, metadata),
        )
        new_id = cur.lastrowid
    print(f"bygevoeg id={new_id} type={args.type} title={args.title!r}")
    return new_id


def cmd_search(args):
    if args.type:
        validate_type(args.type)
    fts_q = to_fts_query(args.query)
    if not fts_q:
        die("leë soekterm")

    sql = """
        SELECT d.id, d.type, d.title, d.tags, d.created_at,
               snippet(documents_fts, 1, '[', ']', '...', 12) AS snip,
               bm25(documents_fts) AS score
        FROM documents_fts
        JOIN documents d ON d.id = documents_fts.rowid
        WHERE documents_fts MATCH ?
    """
    params = [fts_q]
    if args.type:
        sql += " AND d.type = ?"
        params.append(args.type)
    sql += " ORDER BY score LIMIT ?"
    params.append(args.limit)

    conn = connect()
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        die(f"FTS5 soekfout: {e} (query: {fts_q!r})")

    if args.json:
        out = [dict(r) for r in rows]
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    if not rows:
        print("geen resultate")
        return
    for r in rows:
        print(f"#{r['id']:>4}  [{r['type']:<12}] {r['title']}")
        if r["tags"]:
            print(f"       tags: {r['tags']}")
        print(f"       {r['created_at']}")
        print(textwrap.indent(r["snip"], "       "))
        print()


def cmd_show(args):
    conn = connect()
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (args.id,)).fetchone()
    if not row:
        die(f"id {args.id} nie gevind nie")
    if args.json:
        print(json.dumps(dict(row), ensure_ascii=False, indent=2))
        return
    print(f"#{row['id']}  [{row['type']}] {row['title']}")
    if row["tags"]:
        print(f"tags: {row['tags']}")
    if row["source_file"]:
        print(f"bron: {row['source_file']}")
    print(f"geskep: {row['created_at']}  opdateer: {row['updated_at']}")
    print()
    print(row["content"])


def cmd_delete(args):
    conn = connect()
    with conn:
        cur = conn.execute("DELETE FROM documents WHERE id = ?", (args.id,))
    if cur.rowcount == 0:
        die(f"id {args.id} nie gevind nie")
    print(f"verwyder id={args.id}")


def cmd_list(args):
    if args.type:
        validate_type(args.type)
    sql = "SELECT id, type, title, tags, created_at FROM documents"
    params = []
    if args.type:
        sql += " WHERE type = ?"
        params.append(args.type)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(args.limit)
    conn = connect()
    rows = conn.execute(sql, params).fetchall()
    if args.json:
        print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
        return
    if not rows:
        print("leeg")
        return
    for r in rows:
        print(f"#{r['id']:>4}  [{r['type']:<12}] {r['title']}   ({r['created_at']})")


def cmd_stats(args):
    conn = connect()
    total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    by_type = conn.execute(
        "SELECT type, COUNT(*) AS n FROM documents GROUP BY type ORDER BY n DESC"
    ).fetchall()
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    if args.json:
        print(
            json.dumps(
                {
                    "total": total,
                    "by_type": {r["type"]: r["n"] for r in by_type},
                    "db_size_bytes": db_size,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(f"totaal: {total} dokumente")
    print(f"DB grootte: {db_size / 1024:.1f} KiB")
    for r in by_type:
        print(f"  {r['type']:<14} {r['n']}")


def _run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def cmd_ingest_pdf(args):
    src = Path(args.path).expanduser().resolve()
    if not src.exists():
        die(f"PDF nie gevind nie: {src}")
    if src.suffix.lower() != ".pdf":
        die("verwagte .pdf lêer")
    if not shutil.which("ocrmypdf"):
        die("ocrmypdf nie geïnstalleer nie — sien install.sh")
    if not shutil.which("pdftotext"):
        die("pdftotext nie geïnstalleer nie — installeer poppler-utils")

    PDF_ORIG.mkdir(parents=True, exist_ok=True)
    PDF_OCR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", src.stem)
    orig_dest = PDF_ORIG / f"{timestamp}-{safe_name}.pdf"
    ocr_dest = PDF_OCR / f"{timestamp}-{safe_name}.pdf"
    shutil.copy2(src, orig_dest)

    print(f"OCR ({args.lang}) → {ocr_dest.name}", file=sys.stderr)
    ocr_cmd = [
        "ocrmypdf",
        "--language", args.lang,
        "--skip-text",
        "--optimize", "0",
        str(orig_dest),
        str(ocr_dest),
    ]
    try:
        _run(ocr_cmd)
    except subprocess.CalledProcessError as e:
        die(f"ocrmypdf het misluk:\n{e.stderr}")

    try:
        txt = _run(["pdftotext", "-layout", str(ocr_dest), "-"]).stdout
    except subprocess.CalledProcessError as e:
        die(f"pdftotext het misluk:\n{e.stderr}")

    txt = txt.strip()
    if not txt:
        die("geen teks uit PDF gehaal nie")

    title = args.title or src.stem
    conn = connect()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO documents (type, title, content, source_file, tags, metadata)
            VALUES ('pdf_summary', ?, ?, ?, ?, ?)
            """,
            (
                title,
                txt,
                str(orig_dest),
                args.tags,
                json.dumps(
                    {
                        "ocr_path": str(ocr_dest),
                        "ocr_lang": args.lang,
                        "char_count": len(txt),
                    }
                ),
            ),
        )
        new_id = cur.lastrowid
    print(f"PDF ingelees id={new_id} chars={len(txt)} orig={orig_dest}")


def build_parser():
    p = argparse.ArgumentParser(
        prog="kb_manager",
        description="Nonna kennisbasis (SQLite FTS5).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_add = sub.add_parser("add", help="voeg 'n dokument by")
    sp_add.add_argument("--type", required=True, help=f"een van: {', '.join(sorted(VALID_TYPES))}")
    sp_add.add_argument("--title", required=True)
    sp_add.add_argument("--content", help="dokument-inhoud (gebruik --content-file vir groot teks)")
    sp_add.add_argument("--content-file", help="lees inhoud uit hierdie lêer")
    sp_add.add_argument("--tags", default=None, help="spasie- of komma-geskeide etikette")
    sp_add.add_argument("--source-file", default=None)
    sp_add.add_argument("--metadata", default=None, help="JSON-string")
    sp_add.set_defaults(func=cmd_add)

    sp_search = sub.add_parser("search", help="soek deur die kennisbasis")
    sp_search.add_argument("query", help="soekterm (FTS5)")
    sp_search.add_argument("--type", default=None, help="filter op tipe")
    sp_search.add_argument("--limit", type=int, default=10)
    sp_search.add_argument("--json", action="store_true")
    sp_search.set_defaults(func=cmd_search)

    sp_show = sub.add_parser("show", help="wys volledige dokument")
    sp_show.add_argument("id", type=int)
    sp_show.add_argument("--json", action="store_true")
    sp_show.set_defaults(func=cmd_show)

    sp_del = sub.add_parser("delete", help="verwyder 'n dokument")
    sp_del.add_argument("id", type=int)
    sp_del.set_defaults(func=cmd_delete)

    sp_list = sub.add_parser("list", help="lys onlangse dokumente")
    sp_list.add_argument("--type", default=None)
    sp_list.add_argument("--limit", type=int, default=20)
    sp_list.add_argument("--json", action="store_true")
    sp_list.set_defaults(func=cmd_list)

    sp_stats = sub.add_parser("stats", help="aantal dokumente per tipe")
    sp_stats.add_argument("--json", action="store_true")
    sp_stats.set_defaults(func=cmd_stats)

    sp_pdf = sub.add_parser("ingest-pdf", help="OCR + indekseer 'n PDF")
    sp_pdf.add_argument("path", help="pad na PDF")
    sp_pdf.add_argument("--title", default=None)
    sp_pdf.add_argument("--tags", default=None)
    sp_pdf.add_argument("--lang", default="afr+eng", help="Tesseract-taalkode (verstek: afr+eng)")
    sp_pdf.set_defaults(func=cmd_ingest_pdf)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
