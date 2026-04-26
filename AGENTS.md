# Agents — Installing doclens in a project

> If you're an AI coding agent (Claude Code, Cursor, Aider, etc.) and the user asked you to set `doclens` up on their machine, this is your runbook.

## Decision tree

```
Does the user already have doclens?
├── No  → "Option A: clone fresh"
└── Yes → "Option B: init.sh into existing project"

Do they have Docker?
├── No  → install Docker Desktop / OrbStack / colima first; doclens needs it
└── Yes → proceed

Do they have ANTHROPIC_API_KEY?
├── No  → ask them to create one at https://console.anthropic.com/settings/keys
└── Yes → proceed
```

## Option A — fresh clone (recommended for new projects)

```bash
TARGET=~/path/to/new-kb            # ask user where they want it
git clone https://github.com/Padrio/doclens.git "$TARGET"
cd "$TARGET"

# 1. API key
cp .env.example .env
# → ask user to paste their ANTHROPIC_API_KEY into .env

# 2. PDFs
# → ask user to drop PDFs into "$TARGET" (any filenames; slugs auto-derive)

# 3. Build (slow, one-time)
./scripts/doclens.sh build

# 4. Run
./scripts/doclens.sh all
```

## Option B — embed in existing project

Use this when the user has a project (e.g. `my-app/`) and wants the KB inside it (e.g. at `my-app/docs-source/`).

```bash
# from a doclens checkout (clone it once if needed)
cd /path/to/doclens
./scripts/init.sh /path/to/my-app/docs-source

# then the user follows the same flow inside my-app/docs-source:
cd /path/to/my-app/docs-source
cp .env.example .env  # add API key
cp ~/their-pdfs/*.pdf .
./scripts/doclens.sh build
./scripts/doclens.sh all
```

`init.sh` is **non-destructive** — never overwrites existing files unless `--force` is passed.

## After installation, do this

1. **Verify it works:**
   ```bash
   ls scripts/                      # 7 files: convert.py describe_images.py build_index.py doclens.sh search.sh search_sections.sh init.sh
   ./scripts/doclens.sh --help
   ```

2. **Smoke-test on the smallest PDF:**
   ```bash
   ./scripts/doclens.sh convert --only $(ls *.pdf | head -1 | sed 's/\.pdf$//' | tr '[:upper:]_' '[:lower:]-')
   head docs/*/document.md
   ```

3. **Tell the user about navigation rules:**
   - Always start sessions by reading `INDEX.md`.
   - The `CLAUDE.md` (or `AGENTS.md`) in the directory enforces this.

## What you should NOT do

- ❌ Don't `pip install docling` natively — it will fight with PyTorch wheels on macOS Intel and waste 30 minutes. Use the container.
- ❌ Don't commit `.env`. The `.gitignore` shipped with doclens excludes it; check that the user's `.gitignore` does too if you're embedding.
- ❌ Don't process huge corpora (>50 docs) without asking the user about API costs. The `report` command shows expected size before you run `describe`.
- ❌ Don't modify the scripts directly to "personalize" them on first run. Use `slugs.json`, `feature-map.json`, `system-prompt.txt` for per-project config.

## When something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `docker build` fails on torch wheels | Docker daemon under memory pressure or arm64/x86_64 mismatch | Restart Docker Desktop, retry |
| `ModuleNotFoundError: tqdm` at runtime | venv is in `/work/.venv` (volume-mount kills it) | Make sure `Dockerfile` puts venv at `/opt/venv` (it does in shipped version) |
| OCR garbage | Tesseract language pack missing | Add languages to `Dockerfile` apt-install line, rebuild |
| `wsse:InvalidSecurity` etc. — wait, that's not us | You're looking at the wrong tool | This is doclens, not an XML/SOAP debugger |

## Reading the source

If you need to modify behavior, here's the layout:

```
scripts/
├── convert.py            ← Docling pipeline; SLUGS auto-derive or override
├── describe_images.py    ← Anthropic SDK loop, SHA cache, document.md patcher
├── build_index.py        ← regex-based, deterministic; no LLM
├── search.sh             ← ripgrep wrapper with grep fallback
├── search_sections.sh    ← Python-based: hits + nearest header
├── doclens.sh            ← Docker entry point for all subcommands
└── init.sh               ← copy template into another project
```

All scripts read `DOCLENS_ROOT` env (default `.`) so they work both inside the doclens checkout and inside an `init.sh`-populated project directory.
