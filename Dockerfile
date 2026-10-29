FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime data (SQLite db + generated session secret). Mount a volume here in
# production so accounts survive a redeploy, or pass DATABASE_URL to use
# PostgreSQL instead and ignore this path entirely.
ENV PULSE_DB_PATH=/data/pulse_users.db
RUN mkdir -p /data

EXPOSE 8000

CMD ["sh", "-c", "gunicorn app:app --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 60 --access-logfile - --error-logfile -"]
