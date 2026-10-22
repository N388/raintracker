# مطر — منصة الأمطار التاريخية التفاعلية للمملكة العربية السعودية

خريطة ويب تفاعلية لعرض الأمطار التاريخية (NASA GPM IMERG + CHIRPS v3) فوق طبقات خرائط الصحراء
(الفياض، الأودية، الشعاب، القمم، الآبار، علامات الدلالة...) المحوّلة من ملفات OsmAnd.

## البنية

| المكوّن | التقنية |
|---|---|
| الواجهة | Next.js 15 + React 19 + MapLibre GL + Tailwind (RTL عربي) |
| الـ API | FastAPI (async) + Swagger — REST نظيف |
| قاعدة البيانات | PostgreSQL 16 + PostGIS (متجهات + بحث trgm) |
| بلاطات المتجهات | Martin (وظائف MVT بتبسيط حسب التكبير) |
| بلاطات الراستر | TiTiler (COG) — المطر + التضاريس |
| المعالجة | Worker (arq): ETL استطلاعي لعدة مصادر + QA شهري |
| البنية التحتية | Docker Compose + Caddy (TLS + Headers) |

## التشغيل المحلي

```bash
docker compose up -d db cache martin titiler api worker   # البنية
cd apps/web && npm install && npx next build && npx next start -p 3100
# الموقع: http://localhost:3100 — الإدارة: /admin
```

التوثيق التفصيلي:
- [خط أنابيب البيانات](docs/data-pipeline.md) — تحويل OBF → PostGIS → بلاطات.
- [قرار التضاريس](docs/terrain_decision.md) — لماذا DEM بديل + فجوات المصدر.
- [دليل النشر](docs/deployment.md) — إطلاق إنتاجي كامل.

## الاختبارات
- وحدات API: `pytest apps/api/tests/unit` (6)
- E2E: `cd apps/web && npx playwright test` (6)
- حمل: `k6 run infra/load/k6.js`

## الإسناد
- بيانات الخرائط © مساهمو OpenStreetMap (ODbL) — منتج Planetiler/OpenMapTiles.
- بيانات المطر: NASA GPM IMERG V07 / CHIRPS v3.
- التضاريس: Copernicus DEM 30m (AWS Open Data)، الارتفاع: Mapzen Terrain Tiles.
