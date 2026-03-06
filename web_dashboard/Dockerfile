# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy module_config from parent directory (needed by unified_app.py)
# If the build context is web_dashboard/, copy from parent must happen pre-build
# So we handle the import gracefully - the fallback in unified_app.py covers this

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV AUTO_SYNC_ENABLED=true
ENV AUTO_SYNC_INTERVAL_MINUTES=60

# Expose port
EXPOSE 8080

# Run with gunicorn
CMD exec gunicorn --bind :$PORT --workers 1 --threads 16 --timeout 900 unified_app:app
