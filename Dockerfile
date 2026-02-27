FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY web_app.py .
COPY static/ static/

# Папка data монтируется через volume (см. docker-compose.yml)
RUN mkdir -p data

EXPOSE 8000

CMD ["python", "web_app.py"]
