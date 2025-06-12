# Use official slim Python 3.10 image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies for Tesseract OCR and image libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-hin \
    libtesseract-dev \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    espeak \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create virtual environment and set PATH
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port from environment variable (default 5000)
ENV PORT=5000
EXPOSE $PORT

# Run with gunicorn: 1 worker, preload app, bind to all interfaces
CMD ["gunicorn", "--preload", "--workers", "1", "--bind", "0.0.0.0:5000", "app:app"]
