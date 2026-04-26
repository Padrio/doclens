# doclens

> **Make image-heavy PDFs grep-able for AI agents.**
>
> Convert any document corpus (specs, manuals, research papers, regulatory PDFs) into structured Markdown where **every diagram, screenshot, and table is searchable as text** — so LLMs and coding agents can navigate it like a codebase, not like a stack of opaque blobs.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/runs%20in-docker-blue)](Dockerfile)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue)](.python-version)

---

## Why

Modern AI coding agents (Claude Code, Cursor, Aider, Copilot) are **excellent at code** and **terrible at image-heavy specifications**. When you point one at a 250-page PDF full of sequence diagrams, OCR'd tables and Visio screenshots, you get one of three failure modes:

1. **Truncation** — the PDF is too big to fit in context, so the agent reads the first 30 pages and confidently extrapolates.
2. **Image blindness** — even if it does ingest the PDF, every PNG is just `<image>`. Sequence diagrams, ER models, flow charts → invisible.
3. **No anchor** — without a section index, the agent re-reads the same chapters in every session.

The standard answer is "build a RAG pipeline." That's a ton of moving parts (embeddings, vector DB, chunking strategy, hybrid search, re-ranker) for a problem that, for most teams, just needs **good Markdown**.

`doclens` is the boring middle layer: PDFs in, navigable Markdown out. Every image gets an LLM-generated structured description embedded as an HTML comment — so `grep` finds it. An `INDEX.md` and per-doc `TOC.md` give agents stable entry points. A `CLAUDE.md` / `AGENTS.md` teaches the agent how to navigate.

No vector DB. No embeddings. No re-ranker. Just Markdown that an agent can read like source code.

---

## What it actually produces

Drop a PDF into a folder. Run three commands. Get this:

```
your-project/
├── EGVP_Fachkonzept_4-3-1.pdf       (the source — untouched)
├── INDEX.md                           ← entry point: title table, abstracts, deep-links
├── docs/
│   └── egvp-fachkonzept/
│       ├── document.md                ← full text, headers preserved, tables as Markdown
│       ├── TOC.md                     ← header outline with line anchors
│       ├── assets/image_*.png         ← every diagram, extracted as a file
│       ├── descriptions.json          ← SHA-256 cached image descriptions
│       └── meta.json                  ← page count, conversion time, source mtime
├── CLAUDE.md                          ← navigation rules for AI sessions
└── AGENTS.md                          ← same, for runtimes that prefer this filename
```

Inside `document.md`, every image looks like this:

```markdown
![Figure 12](assets/image_0042.png)
<!-- DOCLENS_DESC_SHA=a1b2c3... -->
<!-- DOCLENS_DESC
Type: Sequence diagram
Summary: SAML-based Single Sign-On flow between Principal, SP and IdP.
Structured:
Actors: Principal (browser), Service Provider (SP), Identity Provider (IdP)
1) Principal → SP:  GET /resource
2) SP → Principal:  HTTP 302 redirect with SAMLRequest
3) Principal → IdP: SAMLRequest (HTTP-Redirect binding)
4) IdP ↔ Principal: authentication challenge
5) IdP → Principal: SAMLResponse + assertion
6) Principal → SP:  POST /assert with SAMLResponse
7) SP → Principal:  granted access to /resource
Uncertainties: Step 4 binding (form-post vs browser-native auth) not explicit.
-->
```

`grep "SAMLResponse"` now finds it. So does an agent.

---

## Quick start

### Prerequisites

- **Docker** (Desktop, OrbStack, colima — anything with `docker build` / `docker run`)
- **Anthropic API key** ([console.anthropic.com](https://console.anthropic.com/settings/keys)) for the image-description step
- **`ripgrep`** on host is optional (the search script falls back to `grep`)

### 30-second setup

```bash
# 1. Clone or init in your project
git clone https://github.com/Padrio/doclens.git
cd doclens
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# 2. Drop your PDFs in (any number, any names)
cp ~/Downloads/*.pdf .

# 3. Run the pipeline
./scripts/doclens.sh build           # build container, ~5–15 min, one-time
./scripts/doclens.sh all             # convert + describe + index
```

That's it. Open `INDEX.md`, point your agent at it.

### Per-step commands

```bash
./scripts/doclens.sh convert                  # PDFs → Markdown
./scripts/doclens.sh convert --only my-doc    # one PDF
./scripts/doclens.sh describe                 # all images
./scripts/doclens.sh describe --slug my-doc --sample 5   # dry-run, prints to stdout
./scripts/doclens.sh index                    # rebuild INDEX.md + TOC.md
./scripts/doclens.sh report                   # coverage stats
./scripts/doclens.sh search "SAMLResponse"    # ripgrep with image-desc included
./scripts/doclens.sh shell                    # bash inside the container
```

Everything is **idempotent**. Re-running `convert` on unchanged PDFs is a no-op. Re-running `describe` only hits the API for new images (SHA-256 cache).

---

## How it works

```
                ┌──────────────────────┐
                │   PDFs in ./*.pdf    │
                └──────────┬───────────┘
                           │
                           │  scripts/convert.py
                           │  (Docling 2.x, Tesseract OCR)
                           ▼
                ┌──────────────────────┐
                │  docs/<slug>/        │
                │  ├─ document.md      │  text, headers, tables
                │  ├─ assets/*.png     │  extracted images as files
                │  └─ meta.json        │
                └──────────┬───────────┘
                           │
                           │  scripts/describe_images.py
                           │  (Anthropic Claude vision)
                           ▼
                ┌──────────────────────────────────────┐
                │  document.md, now with HTML comments │
                │  under every image:                  │
                │  <!-- DOCLENS_DESC                   │
                │  Type: Sequence diagram              │
                │  Actors: ...                         │
                │  -->                                 │
                │  + descriptions.json (SHA-cached)    │
                └──────────┬───────────────────────────┘
                           │
                           │  scripts/build_index.py
                           ▼
                ┌──────────────────────┐
                │  INDEX.md            │  global navigation
                │  docs/*/TOC.md       │  per-doc outline
                └──────────────────────┘
```

| Step | Tool | What it does |
|---|---|---|
| 1. Convert | [Docling](https://github.com/DS4SD/docling) 2.x | OCR + layout-aware Markdown export with image extraction |
| 2. Describe | Anthropic Claude (configurable model) | Structured description per image, cached by SHA-256 |
| 3. Index | Pure regex / JSON | Deterministic `INDEX.md` + `TOC.md`, no LLM, fast |
| 4. Search | ripgrep (host) | Finds matches across text **and** image descriptions |

---

## For AI agents — install doclens in any project

If you're an AI coding agent (Claude Code, Cursor, Aider, etc.) reading this to set `doclens` up in a user's project, follow this exact sequence:

### Detect prerequisites

```bash
docker --version || echo "MISSING: docker"
test -f .env || cp .env.example .env       # then prompt user to add ANTHROPIC_API_KEY
```

### Option A — clone, drop in PDFs, run

```bash
git clone https://github.com/Padrio/doclens.git <target-dir>
cd <target-dir>
# user adds PDFs and ANTHROPIC_API_KEY
./scripts/doclens.sh build
./scripts/doclens.sh all
```

### Option B — embed in an existing project

```bash
# from a doclens checkout
./scripts/init.sh /path/to/existing-project/docs-source
# this copies Dockerfile, scripts/, pyproject.toml, .env.example,
# CLAUDE.md, AGENTS.md into the target — does NOT touch existing files
```

The init script never overwrites; pass `--force` if you mean it.

### Verify after setup

```bash
ls scripts/                          # convert.py, describe_images.py, build_index.py, doclens.sh, search.sh, search_sections.sh, init.sh
test -f Dockerfile -a -f pyproject.toml -a -f .env.example
test -f CLAUDE.md -a -f AGENTS.md
```

### What to tell the user

After running `doclens.sh all`, your next session in their project should:

1. **Read `INDEX.md` first** in any task that touches the source documents.
2. **Use `./scripts/doclens.sh search "term"`** before reading `document.md` directly.
3. **Slice `document.md`** with `Read offset=<line> limit=200` based on TOC line anchors. Never read the whole file.
4. **Treat PDFs as last resort** — they're untouched, but Markdown + descriptions cover ~99% of needs.

The `CLAUDE.md` (or `AGENTS.md`) the init script wrote enforces this in future sessions automatically.

---

## Configuration

All config is **optional**. doclens works on a folder full of PDFs with zero extra files.

### `slugs.json` — override auto-derived slugs

By default, `My_Doc.pdf` → slug `my-doc`. Override per file or set a display order:

```json
{
  "_order": ["primary-doc", "secondary-doc"],
  "Confusing_Filename_v1.2.3.pdf": "auth-spec",
  "OTHER FILE WITH SPACES.pdf": "deployment-guide"
}
```

### `feature-map.json` — feature → document mapping in `INDEX.md`

For project-specific shortcuts:

```json
[
  {"feature": "Authentication flow",  "primary": "auth-spec",        "secondary": "deployment-guide"},
  {"feature": "Database schema",       "primary": "data-model",       "secondary": "—"},
  {"feature": "Error handling",        "primary": "api-spec",         "secondary": "deployment-guide"}
]
```

Renders as a table in `INDEX.md` with deep-links.

### `system-prompt.txt` — domain-specific image-description prompt

Default prompts are generic ("technical document", in `en` or `de` via `DOCLENS_LANG`). For domain-specific corpora, drop a custom prompt:

```bash
echo "These images come from medical-device regulatory submissions. Pay special attention to risk-class diagrams and traceability matrices..." > system-prompt.txt
echo "DOCLENS_SYSTEM_PROMPT_FILE=system-prompt.txt" >> .env
```

### Environment variables (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | API key for image descriptions |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | Vision model |
| `DOCLENS_LANG` | `en` | Language of default system prompt (`en` or `de`) |
| `DOCLENS_SYSTEM_PROMPT_FILE` | — | Path to custom system prompt (overrides `DOCLENS_LANG`) |
| `DOCLENS_OCR_LANG` | `eng+deu` | Tesseract languages, `+`-separated |
| `DOCLENS_MAX_TOKENS` | `2048` | Per-description response limit |
| `DOCLENS_REQUEST_DELAY` | `0.2` | Seconds between API calls (rate-limit friendly) |
| `DOCLENS_IMAGE` | `doclens:latest` | Docker image tag |
| `DOCLENS_ROOT` | `$PWD` | Mount root inside container |

---

## Cost

Per image description: ~400 input tokens (auto-resized) + ~500 output tokens.

With `claude-sonnet-4-6` ($3 / MTok input, $15 / MTok output):

| Corpus | Images | Cost |
|---|---|---|
| Single 100-page spec | ~50 | $0.05 – $0.15 |
| Mid-size project (8 docs, 500 pages total) | ~350 | $0.30 – $1.00 |
| Large enterprise corpus (50 docs, 5000 pages) | ~3500 | $3 – $10 |

Re-runs are free (SHA-256 cache). New PDFs only describe new images.

---

## doclens vs. RAG vs. Vector DB

|  | doclens | Classic RAG | Pure Vector DB |
|---|---|---|---|
| Setup time | 15 min | 1–3 days | 2–4 hours |
| Moving parts | 1 (Markdown) | 5+ (embeddings, store, retrieval, re-ranker, prompt builder) | 3+ (embedder, DB, retriever) |
| Image content | ✅ Greppable text | ⚠️ Only if you preprocess | ❌ Skipped |
| Source attribution | ✅ Line numbers | ⚠️ Chunk IDs | ⚠️ Chunk IDs |
| Cost (50 PDFs) | ~$5 once | ~$5 + recurring | ~$3 + recurring |
| Works with any LLM | ✅ Markdown is universal | ✅ | ✅ |
| Works **offline** after build | ✅ | Depends | Depends |
| Iteration | Edit a `.md`, commit | Re-embed, re-deploy | Re-embed |
| Best for | Spec/doc corpora < 10k pages | Customer support, FAQ | Semantic search at scale |
| **Sweet spot** | Coding agents on technical specs | Conversational Q&A | Production search |

doclens is **not** a replacement for RAG when you need fuzzy semantic recall over millions of chunks. It's a replacement for **"how do I get my agent to actually read this PDF correctly."**

---

## FAQ

### Why Docker? I want native.

Docling pulls PyTorch + transformers + HuggingFace models. PyTorch dropped macOS-Intel wheels at 2.3, the dependency graph for native installs is a maze, and we don't want to maintain a "supported OS" matrix. Docker gives us a Linux x86_64 / arm64 base where the wheels are sane.

### Can I use a non-Anthropic vision model?

Today, no — `describe_images.py` is hard-coded to the Anthropic SDK. PRs welcome to add an OpenAI / Ollama / local-VLM backend. The structure is straightforward (one function `describe_with_anthropic`).

### What about non-PDF input?

Docling supports DOCX, PPTX, HTML, images directly. Right now `convert.py` only iterates PDFs; extending to other formats is a 5-line change. PRs welcome.

### Does it commit images?

By default yes — `docs/<slug>/assets/*.png` are part of the KB and version-controlled. They're typically 50–200 KB each. If your corpus produces gigabytes of images, gitignore `assets/` and use Git LFS or external storage.

### What happens to my PDFs?

Nothing. doclens reads them; it never writes. The pipeline is purely additive — it generates `docs/`, `INDEX.md`, etc., and leaves your sources untouched.

### Is the API key sent anywhere besides Anthropic?

No. `describe_images.py` makes direct calls to `api.anthropic.com`. Image bytes are sent as base64 in the request body; descriptions come back as text. Nothing else leaves your machine.

### What if the description is wrong?

Three escape hatches:

1. **Manually edit** `descriptions.json` — keep the SHA key, change the body. Then `doclens.sh describe --force-repatch` re-injects into `document.md`.
2. **Re-describe** — delete the SHA from `descriptions.json`, re-run `describe`.
3. **Custom prompt** — drop hints in `system-prompt.txt` and `--force-repatch` everything.

---

## Roadmap

- [ ] OpenAI / local-VLM backend for `describe_images`
- [ ] DOCX / PPTX input
- [ ] Incremental Markdown patching when source PDF changes (currently full re-convert)
- [ ] Optional embedding sidecar for RAG hybrid setups
- [ ] CI helper: detect un-described images, fail PR

If any of these matter to you, open an issue or PR.

---

## Credits

- [Docling](https://github.com/DS4SD/docling) — the heavy lifting on PDF → structured Markdown
- [Anthropic Claude](https://www.anthropic.com/claude) — vision model for image descriptions
- The pattern was distilled from real production use on a German legal-tech (eBO/EGVP) project where 8 image-heavy government specs (~500 pages) needed to be made navigable for Claude Code

## License

[MIT](LICENSE) — use it, fork it, ship it.
