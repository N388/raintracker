#!/usr/bin/env bash
# اشتقاق تضاريس hillshade للسعودية من Copernicus DEM 30m → COG يقدَّم عبر TiTiler.
# البديل الموثق (docs/terrain_decision.md): ملف Terrain.sqlitedb الأصلي يحتوي بلاطات لمنطقة القطب الشمالي.
set -euo pipefail
cd "$(dirname "$0")/.."
DEM_DIR="$PWD/data/dem"
OUT="$PWD/data/tiles"
GDAL_IMG="ghcr.io/osgeo/gdal:alpine-small-latest"
mkdir -p "$OUT"

echo "==> 1/4 بناء VRT موزاييك"
docker run --rm -v "$DEM_DIR:/dem:ro" -v "$OUT:/out" "$GDAL_IMG" \
  sh -c 'gdalbuildvrt /out/saudi_dem.vrt /dem/*.tif'

echo "==> 2/4 قصّ صندوق الحدود"
docker run --rm -v "$DEM_DIR:/dem:ro" -v "$OUT:/out" "$GDAL_IMG" \
  gdal_translate -projwin 34.4 32.3 55.6 15.0 /out/saudi_dem.vrt /out/saudi_dem_clip.tif

echo "==> 3/4 حساب hillshade (زاوية 315، ارتفاع 45)"
docker run --rm -v "$DEM_DIR:/dem:ro" -v "$OUT:/out" "$GDAL_IMG" \
  gdaldem hillshade -compute_edges -z 2 -s 111120 -az 315 -alt 45 \
  /out/saudi_dem_clip.tif /out/saudi_hillshade.tif

echo "==> 4/4 تخزين COG مع أهرامات عرض"
docker run --rm -v "$DEM_DIR:/dem:ro" -v "$OUT:/out" "$GDAL_IMG" \
  gdal_translate /out/saudi_hillshade.tif /out/terrain_hillshade_cog.tif \
  -of COG -co COMPRESS=DEFLATE -co RESAMPLING=AVERAGE

rm -f "$OUT"/saudi_dem.vrt "$OUT"/saudi_dem_clip.tif "$OUT"/saudi_hillshade.tif
ls -lh "$OUT/terrain_hillshade_cog.tif"
echo "تم."
