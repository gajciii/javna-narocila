FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# OCR for scanned PDF attachments (see tenders/ocr.py).
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-slv tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data/media
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py init_workspace && gunicorn radar.wsgi:application --bind 0.0.0.0:8000 --workers 1 --threads 4 --timeout 300"]
