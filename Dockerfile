# Use official lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for Pillow (Image processing)
RUN apt-get update && apt-get install -y \
    gcc \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your app code
COPY . .

# Run with Gunicorn (1 worker to prevent duplicate data fetching)
CMD gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 0
