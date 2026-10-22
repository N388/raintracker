"""عامل الخلفية (arq): جلب استطلاعي، توليد ليلي، تقرير جودة شهري."""
import asyncio
import json
from datetime import date, timedelta

from arq import cron
from sqlalchemy import text

from .config import get_settings
from .db import SessionLocal
from . import rain_service


async def _etl_cycle(ctx):
    async with SessionLocal() as db:
        report = await rain_service.run_etl(db)
        for src, info in report.items():
            await db.execute(text("""
                INSERT INTO etl_runs (job, product, status, stats) VALUES ('poll', :p, 'ok', :s)
            """), {"p": src, "s": json.dumps(info)})
        await db.commit()
        return report


async def _nightly(ctx):
    """توليد COG للفترات السريعة + الوسم (تسريع أول ظهور)."""
    async with SessionLocal() as db:
        presets = await rain_service.presets(db)
        md = await db.scalar(text("SELECT max(day) FROM rain_daily WHERE source='imerg_v07'"))
        if not md:
            return
        md = date.fromisoformat(str(md))
        for p in presets["quick"]:
            d1 = md - timedelta(days=p["days"])
            try:
                await rain_service.period_cog_path(db, "imerg_v07", d1, md)
            except Exception:
                pass
        w = presets["wasm"]
        await rain_service.period_cog_path(db, "imerg_v07", date.fromisoformat(w["start"]),
                                           date.fromisoformat(w["end"]))


async def _qa_monthly(ctx):
    """تقرير QA: مقارنة IMERG/CHIRPS على الشبكة المشتركة 0.1° (خطة §4.7)."""
    async with SessionLocal() as db:
        await db.execute(text("TRUNCATE data_quality"))
        # تجميع CHIRPS (0.05°) نحو الأخشن 0.1° بمتوسط موزون (إعادة أخذ عينات للمقارنة فقط)
        await db.execute(text("""
            INSERT INTO data_quality (month, cell_geom, bias_mm, rel_bias, baseline_med, flag, threshold_used)
            WITH pair AS (
              SELECT date_trunc('month', v.day)::date m,
                     floor(c2.ix/2.0)::int ix1, floor(c2.iy/2.0)::int iy1,
                     avg(v.val) ch, max(v2.val) im
              FROM rain_values v
              JOIN rain_cells c2 ON c2.source='chirps_v3' AND c2.ix=v.ix AND c2.iy=v.iy
              JOIN rain_values v2 ON v2.source='imerg_v07' AND v2.day=v.day
                     AND v2.ix=floor(c2.ix/2.0)::int AND v2.iy=floor(c2.iy/2.0)::int
              WHERE v.source='chirps_v3' AND v.day >= date_trunc('month', now()) - interval '1 month'
              GROUP BY 1,2,3
            )
            SELECT m, ST_SetSRID(ST_MakePoint(34.4+(ix1+0.5)*0.1, 15.0+(iy1+0.5)*0.1),4326),
                   (ch-im) bias,
                   CASE WHEN im > 0.5 THEN ((ch-im)/im*100.0) ELSE NULL END rel,
                   NULL, NULL,
                   (SELECT value::text::float FROM app_settings WHERE key='qa_threshold_pct')
            FROM pair
        """))
        await db.commit()


async def startup(ctx):
    pass


class WorkerSettings:
    functions = [_etl_cycle, _nightly, _qa_monthly]
    on_startup = startup
    redis_settings = __import__("arq").connections.RedisSettings.from_dsn(get_settings().redis_url)
    cron_jobs = [
        cron(_etl_cycle, minute=set(range(0, 60, 30))),          # استطلاع كل 30 دقيقة
        cron(_nightly, hour=3, minute=12),                        # توليد ليلي
        cron(_qa_monthly, day=1, hour=4, minute=12),              # تقرير شهري
    ]
    max_jobs = 4
    job_timeout = 1200
