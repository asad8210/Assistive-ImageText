# Use official slim Python 3.10 image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies for Tesseract, image processing, and espeak for pyttsx3
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-hin \
        libtesseract-dev \
        libgl1 \
        libsm6 \
        libxext6 \
        libxrender-dev \
        espeak \
        libespeak1 \
        libespeak-dev && \
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

# Set default port (overrideable by Render)
ENV PORT=5000

# Expose the port
EXPOSE $PORT

# Use a single worker to reduce memory usage, preload to reduce duplicate RAM
CMD exec gunicorn --preload --workers 1 --bind 0.0.0.0:${PORT} app:app
