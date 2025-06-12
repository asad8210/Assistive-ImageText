# Use official Python 3.10 slim image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-hin \
        tesseract-ocr-tam \
        tesseract-ocr-spa \
        libtesseract-dev \
        libgl1 \
        libsm6 \
        libxext6 \
        libxrender-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy app source code
COPY . .

# Set default port if not provided
ENV PORT=5000

# Expose port for container runtime
EXPOSE ${PORT}

# Start the application using Gunicorn
CMD exec gunicorn --workers 2 --bind 0.0.0.0:${PORT} app:app
