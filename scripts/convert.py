#!/usr/bin/env python3
"""PDF → Markdown via Docling.

Iterates over all PDFs in ROOT (`./*.pdf` by default, override with
DOCLENS_ROOT env or --root). Each PDF gets a folder under docs/<slug>/
with document.md, assets/, meta.json.

Slug derivation:
1. If `slugs.json` exists in ROOT, use its `pdf_filename → slug` mapping
   (any keys with `_` prefix are treated as metadata, e.g. `_order`).
2. Otherwise, auto-derive from filename (lowercased, non-alphanumeric → "-").

Idempotent: skips PDFs whose meta.json already matches source mtime.
Use --force to re-convert.

Usage:
    python convert.py                     # all PDFs
    python convert.py --only my-doc       # one PDF
    python convert.py --force             # ignore cache
    python convert.py --dry-run           # show plan only
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

ROOT = Path(os.environ.get("DOCLENS_ROOT", ".")).resolve()
DOCS = ROOT / "docs"
LOG_FILE = ROOT / "convert.log"
SLUGS_FILE = ROOT / "slugs.json"


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def docling_version() -> str:
    try:
        return importlib.metadata.version("docling")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def auto_slug(filename: str) -> str:
    """Derive a stable slug from a PDF filename."""
    stem = Path(filename).stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem)
    return stem.strip("-")


def load_slug_map() -> dict[str, str]:
    """Load explicit slug overrides from slugs.json, or {} if not present."""
    if not SLUGS_FILE.exists():
        return {}
    raw = json.loads(SLUGS_FILE.read_text(encoding="utf-8"))
    # Strip metadata keys (anything starting with _)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def resolve_slug(filename: str, overrides: dict[str, str]) -> str:
    return overrides.get(filename, auto_slug(filename))


def is_up_to_date(pdf: Path, meta_path: Path) -> bool:
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return meta.get("source_mtime") == pdf.stat().st_mtime
    except (json.JSONDecodeError, OSError):
        return False


def convert_one(pdf: Path, slug: str, force: bool) -> tuple[str, float | None]:
    """Convert a single PDF. Returns (status, duration_seconds)."""
    out_dir = DOCS / slug
    meta_path = out_dir / "meta.json"

    if not force and is_up_to_date(pdf, meta_path):
        return ("skipped", None)

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TesseractCliOcrOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling_core.types.doc import ImageRefMode

    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(exist_ok=True)

    ocr_lang = os.environ.get("DOCLENS_OCR_LANG", "eng+deu").split("+")
    pipeline_options = PdfPipelineOptions(
        do_ocr=True,
        ocr_options=TesseractCliOcrOptions(lang=ocr_lang),
        generate_picture_images=True,
        images_scale=2.0,
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )

    start = time.time()
    try:
        result = converter.convert(str(pdf))
    except Exception as exc:  # noqa: BLE001
        return (f"error:convert:{exc!r}", None)
    duration = time.time() - start

    try:
        result.document.save_as_markdown(
            filename=out_dir / "document.md",
            image_mode=ImageRefMode.REFERENCED,
            artifacts_dir=assets_dir,
        )
    except AttributeError:
        md = result.document.export_to_markdown(
            image_mode=ImageRefMode.REFERENCED,
            artifacts_dir=assets_dir,
        )
        (out_dir / "document.md").write_text(md, encoding="utf-8")

    # Make image refs relative — Docling writes absolute paths.
    md_path = out_dir / "document.md"
    text = md_path.read_text(encoding="utf-8")
    abs_assets_prefix = str(assets_dir.resolve()) + "/"
    abs_outdir_prefix = str(out_dir.resolve()) + "/"
    text = text.replace(f"]({abs_assets_prefix}", "](assets/")
    text = text.replace(f"]({abs_outdir_prefix}", "](")
    md_path.write_text(text, encoding="utf-8")

    page_count: int | None = None
    try:
        np_attr = getattr(result.document, "num_pages", None)
        if callable(np_attr):
            page_count = int(np_attr())
        elif isinstance(np_attr, int):
            page_count = np_attr
        else:
            pages = getattr(result.document, "pages", None) or {}
            page_count = len(pages)
    except Exception:  # noqa: BLE001
        page_count = None

    meta = {
        "source_pdf": pdf.name,
        "source_mtime": pdf.stat().st_mtime,
        "page_count": page_count,
        "converted_at": datetime.now(timezone.utc).isoformat(),
        "docling_version": docling_version(),
        "duration_seconds": round(duration, 2),
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return ("converted", duration)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="Convert only this slug")
    parser.add_argument("--force", action="store_true", help="Re-convert even if cached")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    args = parser.parse_args()

    setup_logging()
    DOCS.mkdir(exist_ok=True)
    overrides = load_slug_map()

    pdfs = sorted(ROOT.glob("*.pdf"))
    if not pdfs:
        logging.error("No PDFs found in %s", ROOT)
        return 1

    items: list[tuple[Path, str]] = []
    for pdf in pdfs:
        slug = resolve_slug(pdf.name, overrides)
        if args.only and slug != args.only:
            continue
        items.append((pdf, slug))

    if not items:
        logging.error("No PDFs matched filter --only=%s. Available slugs: %s",
                      args.only, [resolve_slug(p.name, overrides) for p in pdfs])
        return 1

    logging.info("Docling version: %s", docling_version())
    logging.info("ROOT: %s, %d PDF(s)", ROOT, len(items))

    if args.dry_run:
        for pdf, slug in items:
            meta_path = DOCS / slug / "meta.json"
            state = "would-skip" if is_up_to_date(pdf, meta_path) and not args.force else "would-convert"
            print(f"[{state}] {pdf.name} -> docs/{slug}/")
        return 0

    stats = {"converted": 0, "skipped": 0, "error": 0}
    total_start = time.time()
    for pdf, slug in tqdm(items, desc="Converting"):
        status, duration = convert_one(pdf, slug, args.force)
        if status == "converted":
            stats["converted"] += 1
            logging.info("  [OK]   %s -> docs/%s/ (%.1fs)", pdf.name, slug, duration or 0)
        elif status == "skipped":
            stats["skipped"] += 1
            logging.info("  [skip] %s (unchanged)", pdf.name)
        else:
            stats["error"] += 1
            logging.error("  [ERR]  %s: %s", pdf.name, status)

    logging.info("Done in %.1fs: %d converted, %d skipped, %d errors",
                 time.time() - total_start, stats["converted"], stats["skipped"], stats["error"])
    return 0 if stats["error"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
