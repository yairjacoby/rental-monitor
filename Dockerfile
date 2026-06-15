FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY monitor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install playwright-stealth

COPY . .

RUN mkdir -p /data

WORKDIR /app/monitor

CMD ["python3", "main.py"]
