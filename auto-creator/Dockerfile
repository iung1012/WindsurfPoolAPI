FROM python:3.11-slim

# System deps for Chromium (without relying on playwright --with-deps which breaks on Debian trixie)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget curl \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    libatspi2.0-0 libwayland-client0 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium binary only (skip system deps, already installed above)
RUN playwright install chromium

COPY src/ ./src/

WORKDIR /app/src

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
