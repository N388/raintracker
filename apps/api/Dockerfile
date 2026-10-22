FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv

# مكتبات تشغيل rasterio/GDAL وecCodes (لقراءة GRIB الخاص بـ GFS)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 libtiff6 libjpeg62-turbo libpng16-16 libwebp7 libzstd1 \
    libcurl4 libsqlite3-0 libpq5 libeccodes-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
