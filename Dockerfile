FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api ./api
COPY mf_plain ./mf_plain
COPY pipeline ./pipeline
COPY ui ./ui
COPY data/tigzig_benchmark_map.csv ./data/tigzig_benchmark_map.csv
COPY data/store/mf.sqlite ./data/store/mf.sqlite
COPY data/raw/2026-10-14/scheme_details_latest.parquet ./data/raw/2026-10-14/scheme_details_latest.parquet
COPY data/raw/2026-10-14/data_quality.csv ./data/raw/2026-10-14/data_quality.csv

EXPOSE 8080
CMD uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8080}
