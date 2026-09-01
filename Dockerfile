# Container for the live WhatsApp Digital FTE webhook (deployed on Render).
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (better layer caching).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app. Secrets/.env are never baked in (git-ignored) — the host injects env vars.
COPY . .

# The host provides $PORT (Render sets it; 8080 is the local fallback). Bind uvicorn to it.
ENV PORT=8080
CMD exec uvicorn whatsapp_webhook.main:app --host 0.0.0.0 --port $PORT
