FROM python:3.11-slim

# Install Playwright system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    libglib2.0-0 \
    libnss3 \
    libx11-xcb1 \
    libxcb-dri3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY monitor/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir playwright-stealth

RUN playwright install chromium

RUN playwright install-deps chromium || true

COPY . .

RUN mkdir -p /data

WORKDIR /app/monitor

CMD ["python3", "main.py"]
