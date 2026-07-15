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
CMD ["python", "app.py"]
