#!/usr/bin/env bash
# استيراد طبقات GeoJSON (ناتجة من محوّل OBF) إلى PostGIS عبر حاوية GDAL.
set -euo pipefail
cd "$(dirname "$0")/.."

PG_HOST="${PG_HOST:-host.docker.internal}"
PG_PORT="${PG_PORT:-5433}"
PG_USER="${PG_USER:-rain}"
PG_PASS="${PG_PASS:-rain_dev_pw}"
PG_DB="${PG_DB:-rain}"
LAYERS_DIR="${LAYERS_DIR:-data/processed/layers}"

CONN="PG:host=${PG_HOST} port=${PG_PORT} user=${PG_USER} password=${PG_PASS} dbname=${PG_DB}"
GDAL_IMG="ghcr.io/osgeo/gdal:alpine-small-latest"

for f in "${LAYERS_DIR}"/*.geojson; do
  table="$(basename "${f}" .geojson)"
  echo "==> استيراد ${table}"
  docker run --rm -v "${PWD}/${LAYERS_DIR}:/data:ro" "${GDAL_IMG}" ogr2ogr \
    -f PostgreSQL "${CONN}" "/data/$(basename "${f}")" \
    -nln "${table}" \
    -s_srs EPSG:4326 -t_srs EPSG:4326 \
    -lco GEOMETRY_NAME=geom -lco FID=gid -lco SPATIAL_INDEX=NONE \
    -gt 65536 --config PG_USE_COPY YES
done
echo "تم الاستيراد."
