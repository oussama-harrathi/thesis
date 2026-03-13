# ── Backend Dockerfile ──────────────────────────────────────────────
# Python 3.11 + TeX Live (for PDF export) + all pip dependencies.
#
# Build:   docker compose build backend
# Run:     docker compose up -d
# ───────────────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ── System dependencies ───────────────────────────────────────────
# texlive-latex-base   → pdflatex compiler (~150 MB)
# texlive-latex-extra  → additional packages (enumitem, geometry, etc.)
# texlive-fonts-recommended → standard fonts
# Other: build-essential for some pip packages, libpq-dev for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-latex-recommended \
    texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*

# Verify pdflatex is available
RUN pdflatex --version | head -1

WORKDIR /app

# ── Python dependencies (cached layer) ────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────────
COPY . .

# Create data directories
RUN mkdir -p data/uploads data/exports

# Make entrypoint executable
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ── Default command: run uvicorn ──────────────────────────────────
EXPOSE 8001
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
