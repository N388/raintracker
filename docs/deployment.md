# نشر الإنتاج (دليل سريع)

## المتطلبات
- خادم سحابي (AWS EC2 / GCP e2) بـ 4 أنوية + 16GB RAM + 60GB تخزين (Docker)
- نطاق موجّه للخادم (A record)
- حساب NASA Earthdata مجاني (لـ IMERG): https://urs.earthdata.nasa.gov

## الخطوات

```bash
# 1) استنساخ المشروع على الخادم
git clone <repo> && cd rainTracker

# 2) الإعدادات
cp .env.example .env
# عدّل: POSTGRES_PASSWORD، JWT_SECRET (openssl rand -hex 32)،
#       ADMIN_EMAIL/ADMIN_PASSWORD، DOMAIN، ACME_EMAIL،
#       EARTHDATA_USERNAME/PASSWORD، RAIN_DRY_RUN=false

# 3) بناء وتشغيل كل الخدمات
docker compose up -d --build

# 4) هجرات قاعدة البيانات (بالترتيب)
for m in infra/db/migrations/*.sql; do
  docker compose exec -T db psql -U rain -d rain < "$m"
done

# 5) بيانات الصحراء (من ملف OBF)
python3 scripts/obf_converter/convert.py "خرائط الصحراء.obf" data/processed/layers
./scripts/import_layers.sh

# 6) التضاريس + خريطة الأساس (مرة واحدة)
./scripts/make_hillshade.sh
# ثم انسخ basemap.pmtiles إلى data/tiles/ (منتج Planetiler)

# 7) أول دورة ETL (ستكرر تلقائياً كل 30 دقيقة)
TOKEN=$(curl -s -X POST http://localhost/api/v1/admin/auth/login \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" | jq -r .access_token)
curl -X POST http://localhost/api/v1/admin/etl/run -H "Authorization: Bearer $TOKEN"

# 7ب) الاكتتاب التاريخي (دفعات سنة بسنة — IMERG من 2000، CHIRPS من 1981)
for y in $(seq 2000 2026); do
  curl -X POST http://localhost/api/v1/admin/etl/backfill \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "{\"source\":\"imerg_v07\",\"from\":\"$y-01-01\",\"to\":\"$y-12-31\",\"product\":\"final\"}"
done

# 8) تحقق
curl http://localhost/api/v1/health        # {"status":"ok"}
open http://localhost                       # الموقع
```

## ما يجري تلقائياً بعدها
- **ETL**: جلب IMERG (Late→Final) + CHIRPS كل 30 دقيقة، تحديث المواد المجمّلة فوراً.
- **ليلاً 03:12**: توليد COG للفترات السريعة + الوسم (تسريع أول ظهور).
- **شهرياً**: تقرير جودة IMERG/CHIRPS على الشبكة المشتركة 0.1° (لوحة التحكم).
- **Caddy**: TLS تلقائي (Let's Encrypt) + Security Headers.

## النسخ الاحتياطي
```bash
# قاعدة البيانات (يومياً عبر cron مقترح)
docker compose exec -T db pg_dump -U rain rain | gzip > backup-$(date +%F).sql.gz
# ملفات البيانات (PMTiles/COGs)
tar czf tiles-backup.tar.gz data/tiles
```

## المراقبة
- `GET /api/v1/health` — فحص حالة.
- `GET /api/v1/admin/stats` (JWT) — مؤشرات.
- لوحة التحكم `/admin` — سجلات ETL وجودة البيانات.

## التوسع الأفقي مستقبلاً
- ملفات `data/tiles` (PMTiles/COG) تُنقل إلى S3 + CDN دون تغيير كود (المسارات متوافقة).
- قاعدة البيانات تُرفع إلى RDS/Aurora بتغيير DATABASE_URL فقط.
- إضافة مصدر مطر جديد = محوّل في `app/sources.py` + سطر في RAIN_SOURCES.
