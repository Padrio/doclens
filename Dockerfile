# doclens — document-indexing pipeline runtime
#
# Provides Python 3.12 + Docling + Tesseract (multi-language) +
# Anthropic SDK. Scripts are NOT baked into the image; they're mounted
# from the calling directory at /work, so users can version + modify
# them per project without rebuilding.
#
# Build once with `./scripts/doclens.sh build`, then run any command
# via `./scripts/doclens.sh <subcommand>`.

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-deu \
        tesseract-ocr-fra \
        tesseract-ocr-spa \
        tesseract-ocr-ita \
        poppler-utils \
        libgl1 \
        libglib2.0-0 \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# venv outside /work — /work is overlaid by the host volume at runtime.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

# Force CPU-only torch wheels. Without this, transitive deps pull
# nvidia-cuda-* (~2.7 GB) and triton (~640 MB) we never use.
ENV UV_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
ENV UV_INDEX_STRATEGY=unsafe-best-match

WORKDIR /opt/build
RUN uv venv /opt/venv

# Install torch+torchvision CPU-only first so transitive resolution
# from docling can't escalate them to the CUDA flavor.
RUN uv pip install --python /opt/venv/bin/python \
        --index-url https://download.pytorch.org/whl/cpu \
        torch torchvision

COPY pyproject.toml ./
RUN uv sync --no-install-project

# Strip __pycache__ to shave a few hundred MB.
RUN find /opt/venv -type d -name __pycache__ -prune -exec rm -rf {} +

ENV PATH="/opt/venv/bin:${PATH}"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
# HF cache lives in /work/.cache/huggingface so layout models persist
# across container runs without bloating the image.
ENV HF_HOME=/work/.cache/huggingface

WORKDIR /work
ENTRYPOINT []
CMD ["python", "scripts/convert.py", "--help"]
