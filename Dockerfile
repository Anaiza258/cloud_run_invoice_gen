# Use official Python slim image
FROM python:3.11-slim

WORKDIR /app

# # Install system deps (if needed)
# RUN apt-get update && apt-get install -y build-essential libmagic1 curl && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Cloud Run uses $PORT
ENV PORT 8080

EXPOSE 8080

# Run with Gunicorn; make sure your Flask app is named `app` inside app_gemini.py
CMD ["gunicorn", "-b", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "app_gemini:app"]
