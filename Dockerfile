FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Runtime dependencies only. duckdb belongs to the data job, not the server:
# the 178 MB NAV master and the parquet files never enter this image.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The ETL modules (nightly, quartiles, indices, store) are shipped but never
# imported by the server, and duckdb is imported lazily, so this image runs
# without it.
COPY api ./api
COPY mf_plain ./mf_plain
COPY pipeline ./pipeline
COPY ui ./ui
COPY data/tigzig_benchmark_map.csv ./data/tigzig_benchmark_map.csv
# Built by the scheduled data job: metrics, medians, scheme details, quality notes.
COPY data/store/mf.sqlite ./data/store/mf.sqlite

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request,sys; p=os.environ.get('PORT','8080'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/healthz', timeout=3).status == 200 else 1)"

CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
