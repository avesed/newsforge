# =============================================================================
# NewsForge Multi-Stage Dockerfile
# =============================================================================

# --- Stage 1: Frontend Builder ---
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Backend (dev/standalone) ---
FROM python:3.11-slim AS backend
WORKDIR /app/backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir .

COPY backend/ ./
COPY backend/config/ ../config/

RUN mkdir -p /app/data/articles

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--loop", "uvloop"]

# --- Stage 3: Production (all-in-one with supervisord + nginx) ---
FROM python:3.11-slim AS production
WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    nginx \
    supervisor \
    dumb-init \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY backend/pyproject.toml /app/backend/
RUN pip install --no-cache-dir /app/backend/

# Install Playwright browsers (needed for Google News URL resolution)
RUN pip install --no-cache-dir playwright && playwright install chromium --with-deps

# Backend code
COPY backend/ /app/backend/
COPY backend/config/ /app/config/

# Frontend static files
COPY --from=frontend-builder /app/frontend/dist /usr/share/nginx/html

# Nginx config
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -f /etc/nginx/sites-enabled/default

# Supervisord config
COPY docker/supervisord.conf /app/docker/supervisord.conf

# Entrypoint
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh

# Data directory
RUN mkdir -p /app/data/articles

EXPOSE 80 8000

ENTRYPOINT ["dumb-init", "--"]
CMD ["/app/docker/entrypoint.sh"]

# --- Stage 4: Frontend only (Nginx) ---
FROM nginx:alpine AS frontend
COPY --from=frontend-builder /app/frontend/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
