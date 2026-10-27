# aptscout server image: the API, the dataset tools and the built web app.
FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
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
