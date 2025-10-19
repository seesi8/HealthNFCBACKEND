FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install tzdata (ZoneInfo) and build deps if needed
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Add a small entrypoint helper that can write a service-account JSON from
# the FIREBASE_ADMIN_JSON environment variable into /app/firebase-admin.json
# at container start. This lets you provide credentials via fly secrets.
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
