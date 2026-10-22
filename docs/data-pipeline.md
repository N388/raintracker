# خط أنابيب بيانات طبقات الصحراء (M1)

## نظرة عامة

```
خرائط الصحراء.obf
      │
      ▼  scripts/obf_converter/convert.py   (بايثون خالص، بدون اعتماديات)
GeoJSON لكل طبقة (23 ملفاً) في data/processed/layers/
      │
      ▼  scripts/import_layers.sh           (حاوية GDAL: ogr2ogr)
PostgreSQL/PostGIS: جدول لكل طبقة + GiST + places_search + كتالوج layers_meta
      │
      ▼  migrations 003-005                  (وظائف mvt_* بتبسيط حسب التكبير)
Martin : بلاطات Vector Tiles عبر HTTP  ← الواجهة (MapLibre)
```

## 1) التحويل من OBF

```bash
python3 scripts/obf_converter/convert.py <ملف.obf> data/processed/layers
```

- يفك تنسيق OsmAnd Binary v2 بالكامل (هندسة 31-زوم delta، مضلعات خارجية/داخلية،
  أسماء عربية من stringTable، سمات intermittent/religion).
- يصنّف مجاري المياه بالأسماء العربية: فيضة/وادي/شعب/روضة/سبخة/أخرى.
- ناتج مُتحقق: 499,518 معلم؛ الأعداد طبقة بطبقة مطابقة لتحليل مستقل،
  والإحداثيات متطابقة 0.0 كم مع فهرس العناوين الداخلي في الملف نفسه.

## 2) الاستيراد إلى PostGIS

```bash
docker compose up -d db
docker compose exec -T db psql -U rain -d rain < infra/db/migrations/001_init.sql
./scripts/import_layers.sh
docker compose exec -T db psql -U rain -d rain < infra/db/migrations/002_layers_catalog.sql
docker compose exec -T db psql -U rain -d rain < infra/db/migrations/003_mvt_functions.sql
docker compose exec -T db psql -U rain -d rain < infra/db/migrations/004_catalog_fix.sql
docker compose exec -T db psql -U rain -d rain < infra/db/migrations/005_mvt_flat_props.sql
```

## 3) خدمة البلاطات (Martin)

```bash
docker compose up -d martin
# فهرس المصادر:
curl http://localhost:3000/catalog
# بلاطة مثال (مجاري المياه عند الرياض z9):
curl http://localhost:3000/waterways/9/322/219 -o tile.mvt
```

## 4) معاينة بصرية

افتح `scripts/preview/map.html` في المتصفح (Martin يعمل على localhost:3000).

## ملاحظات

- التبسيط حسب التكبير في mvt_waterways ضروري (322 ألف خط): z7 يُبسَّط إلى ~500م.
- التجمعات مُرشّحة حسب النوع: مدن فقط ≤z8، مدن+قرى z9-10، الكل من z11.
- بلاطات التضاريس القادمة من COG (بديل DEM الموثق في docs/terrain_decision.md)
  تُقدَّم عبر TiTiler لا Martin.
- خريطة الأساس (OSM→PMTiles عبر Planetiler) تُضاف كمصدر pmtiles في Martin عند اكتمالها.
