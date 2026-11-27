# Stage 1: build the web page. The final image carries only the built files, not node or node_modules.
FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: the API, which also serves the built page from frontend/dist.
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# tesseract-ocr + poppler-utils: OCR for images and scanned PDFs (pytesseract, pdf2image).
# libpq-dev/gcc kept for psycopg2 builds on platforms without a binary wheel.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Exact, hashed versions (requirements.lock); requirements.txt only states minimums.
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY . .
COPY --from=web /web/dist ./frontend/dist

# Run as an unprivileged user.
RUN groupadd --system app && useradd --system --gid app --home-dir /app --no-create-home app \
    && chown -R app:app /app
USER app

EXPOSE 8000

# Apply migrations (alembic is the schema source of truth), then serve.
# --no-access-log: request paths and client addresses are not written to logs.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --no-access-log"]
