#!/usr/bin/env python3
"""Annotate every image in docs/<slug>/document.md with a structured
description from Anthropic Claude, embedded as an HTML comment so
grep can find diagram contents.

Cache: docs/<slug>/descriptions.json keyed by SHA-256 of image bytes.
Re-runs are cheap (cache-only) unless --force-repatch is set.

System prompt:
- Default is a generic "technical document" prompt in the language set
  by DOCLENS_LANG (en|de, default en).
- Override with DOCLENS_SYSTEM_PROMPT_FILE pointing to a .txt file —
  use this to inject domain hints (e.g. "this is a medical paper",
  "this is a German government protocol spec", etc.).

Usage:
    python describe_images.py                          # all slugs
    python describe_images.py --slug my-doc            # one slug
    python describe_images.py --slug my-doc --sample 5 # dry-run
    python describe_images.py --report                 # coverage stats
    python describe_images.py --slug X --force-repatch # rebuild markers
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

ROOT = Path(os.environ.get("DOCLENS_ROOT", ".")).resolve()
DOCS = ROOT / "docs"

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = int(os.environ.get("DOCLENS_MAX_TOKENS", "2048"))
RETRY_BACKOFF_SECONDS = [2, 8, 32]
REQUEST_DELAY_SECONDS = float(os.environ.get("DOCLENS_REQUEST_DELAY", "0.2"))

SYSTEM_PROMPT_EN = """You analyze an image extracted from a technical document. Answer in a structured way and do not hallucinate. If you cannot identify something, say so explicitly.

Use this format:

**Type:** [Sequence diagram | Data model/ER | Flow chart | Table | Screenshot | XML schema rendering | Architecture diagram | Other]

**Summary:** (1-2 sentences describing what the image shows)

**Structured content:**
- Sequence diagram: every actor, every message with direction + name + payload, ordering, conditions/alternatives, timeouts
- Data model: every entity with fields and types, every relationship with cardinality
- Table: reproduce fully as a Markdown table
- Flow chart: every node in execution order, every branch condition
- XML schema: every element, attribute, type, occurrence
- Screenshot: visible UI elements, labels, button states, form fields with values

**Uncertainties:** (what couldn't you identify with confidence?)"""

SYSTEM_PROMPT_DE = """Du analysierst ein Bild aus einem technischen Dokument. Antworte strukturiert und erfinde nichts. Wenn du etwas nicht erkennst, sage das explizit.

Gib deine Antwort in diesem Format:

**Typ:** [Sequenzdiagramm | Datenmodell/ER | Flussdiagramm | Tabelle | Screenshot | XML-Schema-Darstellung | Architekturdiagramm | Sonstiges]

**Zusammenfassung:** (1-2 Saetze, was zeigt das Bild)

**Strukturierter Inhalt:**
- Sequenzdiagramm: alle Akteure, jede Nachricht mit Richtung + Name + Payload, Reihenfolge, Bedingungen/Alternativen, Timeouts
- Datenmodell: alle Entitaeten mit Feldern und Typen, alle Beziehungen mit Kardinalitaeten
- Tabelle: vollstaendig als Markdown-Tabelle rekonstruieren
- Flussdiagramm: alle Knoten in Ausfuehrungsreihenfolge, alle Verzweigungsbedingungen
- XML-Schema: alle Elemente, Attribute, Typen, Occurrences
- Screenshot: sichtbare UI-Elemente, Beschriftungen, Button-Zustaende, Formularfelder mit Werten

**Unsicherheiten:** (was konntest du nicht eindeutig erkennen?)"""

USER_TEXT_EN = "Please analyze this image according to the rules above."
USER_TEXT_DE = "Bitte analysiere dieses Bild gemaess Vorgabe."

MARKER_RE = re.compile(r"^<!-- (?:BILDBESCHREIBUNG|DOCLENS_DESC)_SHA=([0-9a-f]{64})\s*-->\s*$", re.MULTILINE)
IMG_REF_RE = re.compile(r"^(!\[.*?\]\((?P<path>assets/[^)\s]+)\))\s*$", re.MULTILINE)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def get_system_prompt() -> str:
    override = os.environ.get("DOCLENS_SYSTEM_PROMPT_FILE")
    if override and Path(override).exists():
        return Path(override).read_text(encoding="utf-8").strip()
    lang = os.environ.get("DOCLENS_LANG", "en").lower()
    return SYSTEM_PROMPT_DE if lang.startswith("de") else SYSTEM_PROMPT_EN


def get_user_text() -> str:
    lang = os.environ.get("DOCLENS_LANG", "en").lower()
    return USER_TEXT_DE if lang.startswith("de") else USER_TEXT_EN


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_descriptions(slug_dir: Path) -> dict[str, dict]:
    path = slug_dir / "descriptions.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_descriptions(slug_dir: Path, data: dict[str, dict]) -> None:
    path = slug_dir / "descriptions.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def image_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
    }.get(ext, "image/png")


def encode_image_b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def describe_with_anthropic(client, model: str, path: Path) -> str:
    import anthropic

    message = {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_media_type(path),
                    "data": encode_image_b64(path),
                },
            },
            {"type": "text", "text": get_user_text()},
        ],
    }

    last_exc: Exception | None = None
    for attempt, backoff in enumerate([0, *RETRY_BACKOFF_SECONDS]):
        if backoff:
            time.sleep(backoff)
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                system=get_system_prompt(),
                messages=[message],
            )
            parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
            return "\n".join(parts).strip()
        except (anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIError) as exc:
            last_exc = exc
            logging.warning("API error (attempt %d/%d): %s", attempt + 1, len(RETRY_BACKOFF_SECONDS) + 1, exc)
            continue
    raise RuntimeError(f"Anthropic API failed after {len(RETRY_BACKOFF_SECONDS) + 1} attempts") from last_exc


def parse_description(text: str) -> dict:
    """Pull out Type/Summary/Structured/Uncertainties (works for EN+DE prompts)."""
    def section(*labels: str) -> str:
        for label in labels:
            pattern = re.compile(
                rf"\*\*{re.escape(label)}:\*\*\s*(.*?)(?=\n\*\*[A-Za-zÀ-ÿ][^*]*:\*\*|\Z)",
                re.DOTALL,
            )
            m = pattern.search(text)
            if m:
                return m.group(1).strip()
        return ""

    return {
        "type": section("Type", "Typ"),
        "summary": section("Summary", "Zusammenfassung"),
        "structured": section("Structured content", "Strukturierter Inhalt"),
        "uncertainties": section("Uncertainties", "Unsicherheiten"),
        "raw": text,
    }


def format_comment_block(sha: str, parsed: dict) -> str:
    lines = [f"<!-- DOCLENS_DESC_SHA={sha} -->", "<!-- DOCLENS_DESC"]
    if parsed.get("type"):
        lines.append(f"Type: {parsed['type']}")
    if parsed.get("summary"):
        lines.append(f"Summary: {parsed['summary']}")
    if parsed.get("structured"):
        lines.append("Structured:")
        lines.append(parsed["structured"])
    if parsed.get("uncertainties"):
        lines.append(f"Uncertainties: {parsed['uncertainties']}")
    lines.append("-->")
    return "\n".join(lines)


def patch_document(slug_dir: Path, image_shas: dict[str, str], descriptions: dict[str, dict],
                   force_repatch: bool = False) -> int:
    doc = slug_dir / "document.md"
    if not doc.exists():
        return 0

    text = doc.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=False)
    out: list[str] = []
    i = 0
    patched = 0

    while i < len(lines):
        line = lines[i]
        img_match = IMG_REF_RE.match(line + "\n")
        if not img_match:
            out.append(line)
            i += 1
            continue

        out.append(line)
        i += 1
        rel_path = img_match.group("path")
        sha = image_shas.get(rel_path)

        existing_sha: str | None = None
        block_start = i
        if i < len(lines):
            m = MARKER_RE.match(lines[i] + "\n")
            if m:
                existing_sha = m.group(1)
                while i < len(lines) and "-->" not in lines[i]:
                    i += 1
                if i < len(lines) and "-->" in lines[i]:
                    i += 1

        parsed = descriptions.get(sha) if sha else None
        if not parsed:
            if existing_sha and not force_repatch:
                out.extend(lines[block_start:i])
            continue

        if existing_sha == sha and not force_repatch:
            out.extend(lines[block_start:i])
            continue

        out.append(format_comment_block(sha, parsed))
        patched += 1

    new_text = "\n".join(out)
    if not new_text.endswith("\n"):
        new_text += "\n"
    if new_text != text:
        doc.write_text(new_text, encoding="utf-8")
    return patched


def collect_slug_dirs(only: str | None) -> list[Path]:
    if not DOCS.exists():
        return []
    dirs = sorted(d for d in DOCS.iterdir() if d.is_dir())
    if only:
        return [d for d in dirs if d.name == only]
    return dirs


def list_images(slug_dir: Path) -> list[Path]:
    assets = slug_dir / "assets"
    if not assets.exists():
        return []
    return sorted(p for p in assets.rglob("*")
                  if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))


def report_coverage(slug_dirs: list[Path]) -> None:
    total_images = 0
    total_described = 0
    rows = []
    for d in slug_dirs:
        images = list_images(d)
        desc = load_descriptions(d)
        described = sum(1 for img in images if sha256_file(img) in desc)
        rows.append((d.name, described, len(images)))
        total_images += len(images)
        total_described += described

    print("\nCoverage Report")
    print("=" * 64)
    print(f"{'Slug':<40} {'Described':>14} {'Total':>8}")
    print("-" * 64)
    for slug, described, total in rows:
        pct = (100 * described / total) if total else 0
        print(f"{slug:<40} {described:>7} ({pct:5.1f}%) {total:>8}")
    print("-" * 64)
    pct = (100 * total_described / total_images) if total_images else 0
    print(f"{'TOTAL':<40} {total_described:>7} ({pct:5.1f}%) {total_images:>8}")


def anthropic_client(model: str):
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY not set. Create .env from .env.example.")
    return anthropic.Anthropic(api_key=key), model


def run_slug(slug_dir: Path, client, model: str, force_repatch: bool) -> tuple[int, int, int]:
    images = list_images(slug_dir)
    if not images:
        return (0, 0, 0)
    descriptions = load_descriptions(slug_dir)
    image_shas: dict[str, str] = {}
    new_count = cached_count = error_count = 0

    for img in tqdm(images, desc=slug_dir.name, leave=False):
        rel = img.relative_to(slug_dir).as_posix()
        sha = sha256_file(img)
        image_shas[rel] = sha
        if sha in descriptions:
            cached_count += 1
            continue
        try:
            text = describe_with_anthropic(client, model, img)
        except Exception as exc:  # noqa: BLE001
            logging.error("%s: error on %s: %s", slug_dir.name, rel, exc)
            error_count += 1
            continue
        parsed = parse_description(text)
        parsed["model"] = model
        parsed["created_at"] = datetime.now(timezone.utc).isoformat()
        descriptions[sha] = parsed
        save_descriptions(slug_dir, descriptions)
        new_count += 1
        time.sleep(REQUEST_DELAY_SECONDS)

    patched = patch_document(slug_dir, image_shas, descriptions, force_repatch=force_repatch)
    logging.info("%s: %d new, %d cached, %d errors, %d markers patched",
                 slug_dir.name, new_count, cached_count, error_count, patched)
    return (new_count, cached_count, error_count)


def run_sample(slug_dir: Path, client, model: str, n: int) -> None:
    images = list_images(slug_dir)
    descriptions = load_descriptions(slug_dir)
    candidates = [img for img in images if sha256_file(img) not in descriptions] or images
    sample = random.sample(candidates, min(n, len(candidates)))
    for img in sample:
        print(f"\n{'=' * 70}\nIMAGE: {img.relative_to(slug_dir)}\n{'=' * 70}")
        try:
            text = describe_with_anthropic(client, model, img)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}")
            continue
        print(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", help="Process only this slug")
    parser.add_argument("--sample", type=int, metavar="N",
                        help="Dry-run: describe N random images, print to stdout")
    parser.add_argument("--report", action="store_true", help="Coverage stats only")
    parser.add_argument("--force-repatch", action="store_true",
                        help="Re-patch document.md markers even if up-to-date")
    args = parser.parse_args()

    setup_logging()
    load_dotenv(ROOT / ".env")

    slug_dirs = collect_slug_dirs(args.slug)
    if not slug_dirs:
        logging.error("No slug directories in %s", DOCS)
        return 1

    if args.report:
        report_coverage(slug_dirs)
        return 0

    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
    client, _ = anthropic_client(model)

    if args.sample:
        if not args.slug:
            logging.error("--sample requires --slug <slug>")
            return 1
        run_sample(slug_dirs[0], client, model, args.sample)
        return 0

    totals = {"new": 0, "cached": 0, "error": 0}
    for d in slug_dirs:
        n, c, e = run_slug(d, client, model, args.force_repatch)
        totals["new"] += n
        totals["cached"] += c
        totals["error"] += e

    logging.info("Total: %d new, %d cached, %d errors",
                 totals["new"], totals["cached"], totals["error"])
    return 0 if totals["error"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
