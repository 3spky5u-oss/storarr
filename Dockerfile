FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ templates/
COPY static/ static/

ENV STORARR_DATA_DIR=/data
VOLUME ["/data"]

EXPOSE 8585
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8585/healthz', timeout=3)" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8585", "--workers", "1", "--threads", "4", "app:app"]
