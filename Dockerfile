# aptscout server image: the API, the dataset tools and the built web app.
# Base images pinned by version and multi-arch index digest; bump both together.
FROM node:24.22.1-trixie-slim@sha256:43b9ba1142b8dcf33fa8f922ca1be85714adc444e0586c7cf7726daaeabc1bea AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12.16-slim-trixie@sha256:962f801b08c870ac2a51b72bf02dae38c9a4162319e5e882ec244e198188d54e
# libexpat1: pyosmium (osmium) links it, and the slim image lacks it
# (import-places and build-otp-inputs read the OSM extract with it).
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
RUN useradd --system --create-home --uid 10001 aptscout
WORKDIR /app
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY server/ server/
COPY --from=web /web/dist web/dist
ENV PYTHONUNBUFFERED=1 APTSCOUT_DATA_DIR=/data APTSCOUT_WEB_DIST=/app/web/dist
WORKDIR /app/server
USER aptscout
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["python", "-m", "uvicorn", "aptscout.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
