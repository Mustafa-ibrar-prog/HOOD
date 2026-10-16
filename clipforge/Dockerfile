# Single-image deployment: builds the React UI and serves it from FastAPI on :8000.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg fonts-inter fonts-dejavu-core fontconfig \
 && rm -rf /var/lib/apt/lists/*
# yt-dlp needs a JavaScript runtime (Deno >= 2.3) to solve YouTube's player challenges
COPY --from=denoland/deno:bin-2.4.0 /deno /usr/local/bin/deno
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# Optional local speech-to-text: uncomment (adds ~1 GB with model weights at runtime)
# RUN pip install --no-cache-dir faster-whisper
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
ENV CLIPFORGE_DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
