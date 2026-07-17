FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    proj-data \
    proj-bin \
    && rm -rf /var/lib/apt/lists/*

ENV CPLUS_INCLUDE_PATH=/usr/include/gdal \
    C_INCLUDE_PATH=/usr/include/gdal

COPY requirements.txt pyproject.toml ./

RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

RUN pip install --no-deps -e . \
    && groupadd --system appuser \
    && useradd --system --gid appuser --create-home appuser \
    && mkdir -p /app/data/raw /app/data/processed /app/logs \
    && chown -R appuser:appuser /app

USER appuser

CMD ["python", "scripts/monitoring/run_daily_pipeline.py"]
