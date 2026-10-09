FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt requirements-worker.txt ./
# Binary geospatial wheels bundle GDAL/GEOS/PROJ; fail rather than silently build native libraries.
RUN pip install --no-cache-dir --only-binary=fiona,shapely,pyproj -r requirements-worker.txt
COPY app ./app
COPY tests ./tests
COPY migrations ./migrations
COPY alembic.ini ./
RUN mkdir -p /data
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
