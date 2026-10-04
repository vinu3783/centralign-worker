# ---- 1. Build the React frontend ----
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- 2. Python backend serving API + built UI on one origin ----
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STATIC_DIR=/app/static \
    DATA_DIR=/data \
    DATABASE_URL=sqlite:////data/centralign.db \
    CHECKPOINT_DB_PATH=/data/checkpoints.db \
    FRONTEND_URL=http://127.0.0.1:8000 \
    CORS_ORIGINS=http://localhost:8000
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt \
 && python -m playwright install --with-deps chromium
COPY backend/app ./app
COPY --from=frontend /app/frontend/dist /app/static
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
