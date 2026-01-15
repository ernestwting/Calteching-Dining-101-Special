FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Install Tesseract OCR and system dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium for Playwright
RUN playwright install chromium

# Copy the rest of the application
COPY . .

# Expose port for health check
EXPOSE 8080

CMD ["python", "main.py"]
