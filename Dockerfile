FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY frontend ./frontend
COPY scripts ./scripts
COPY data/entreprises_Marrakech_FINAL.csv ./data/entreprises_Marrakech_FINAL.csv
COPY offres_jooble.csv ./offres_jooble.csv
COPY gunicorn.conf.py ./
ENV STORAGE_ROOT=/data SESSION_COOKIE_SECURE=1 FLASK_DEBUG=0 PORT=8080
EXPOSE 8080
CMD ["gunicorn", "--config", "gunicorn.conf.py", "backend.app:app"]
