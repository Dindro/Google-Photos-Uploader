# Stage 1: Build dependencies (multi-stage build)
FROM python:3.11-alpine AS builder

WORKDIR /app

# Install system dependencies required for build
RUN apk add --no-cache \
    gcc \
    musl-dev \
    libc-dev \
    linux-headers \
    cifs-utils

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Final image
FROM python:3.11-alpine

# Install only essential runtime dependencies
RUN apk add --no-cache \
    cifs-utils \
    inotify-tools \
    sqlite

WORKDIR /app

# Copy python packages from builder
COPY --from=builder /usr/local /usr/local

# Prepare data directories
RUN mkdir -p /data /app/data

# Copy application files
COPY script_gphoto.py .
COPY cleanup_service.py .
COPY config.py .
COPY database.py .
COPY dashboard.py .
COPY filesystem_source.py .
COPY media_utils.py .
COPY sources.py .
COPY synology_photos_source.py .
COPY synology_photos.py .
COPY upload_processor.py .
COPY index.html .
COPY media ./media

ENV PYTHONUNBUFFERED=1 \
    WATCHED_FOLDER=/data \
    DB_FILE=/app/data/uploader.db

# Run script
CMD ["python", "-u", "script_gphoto.py"]
