FROM python:3.11-slim

# System deps required by Chromium (playwright install --with-deps handles the rest)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates wget curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium + all its system deps in one step
RUN playwright install --with-deps chromium

COPY src/ ./src/

WORKDIR /app/src

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
