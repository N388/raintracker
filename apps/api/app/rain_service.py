"""منطق المطر: الاستيعاب، نقطة الاستعلام، الفترات، الوسم، COG."""
from __future__ import annotations
import io
import os
from datetime import date

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .sources import Grid, RainSource, build_sources

RAIN_DAY_MM = 0.1  # عتبة يوم المطر (خطة §4.2)

QUICK_PRESETS = [
    ("3days", 3), ("7days", 7), ("10days", 10), ("20days", 20), ("30days", 30),
    ("40days", 40), ("60days", 60), ("90days", 90), ("120days", 120), ("180days", 180),
]


# ───────────── الاستيعاب اليومي ─────────────

async def ingest_grid(db: AsyncSession, g: Grid, source: RainSource) -> int:
    """يدخل قيم اليوم دفعة واحدة (upsert). يرجع عدد الخلايا."""
    vals = np.nan_to_num(g.values, nan=-1.0).astype(float)
    rows = [(g.day, source.key, iy, ix, vals[iy, ix])
            for iy in range(g.ny) for ix in range(g.nx)]
    await db.execute(text("DELETE FROM rain_values WHERE day=:d AND source=:s"),
                     {"d": g.day, "s": source.key})
    conn = await db.connection()
    raw = await conn.get_raw_connection()
    await raw.driver_connection.executemany(
        "INSERT INTO rain_values (day, source, iy, ix, val) VALUES ($1,$2,$3,$4,$5)", rows)
    await db.execute(text("""
        INSERT INTO rain_daily (day, product, source, cells) VALUES (:d, :p, :s, :c)
        ON CONFLICT (day, product) DO UPDATE SET cells = EXCLUDED.cells, fetched_at = now()
    """), {"d": g.day, "p": source.product, "s": source.key, "c": len(rows)})
    await db.commit()
    return len(rows)


async def run_etl(db: AsyncSession, only: str | None = None) -> dict:
    """دورة الجلب الاستطلاعي لكل المصادر. في وضع التجربة: توليد محلي."""
    settings = get_settings()
    sources = build_sources(settings)
    if only:
        sources = {k: v for k, v in sources.items() if k == only}
    report: dict = {}
    for key, src in sources.items():
        have = await db.scalar(text(
            "SELECT max(day) FROM rain_daily WHERE source=:s"), {"s": key})
        days = await src.missing_days(have)
        done = []
        for d in days:
            g = await src.fetch_day(d)
            await ingest_grid(db, g, src)
            done.append(str(d))
        report[key] = {"fetched": done}
    await db.execute(text("SELECT refresh_rain_mvs()"))
    await db.commit()
    return report


async def backfill(db: AsyncSession, source_key: str, d1: date, d2: date,
                   product: str = "final") -> dict:
    """اكتتاب تاريخي: يجلب نطاقاً كاملاً (يوم-ب-يوم، يتجاوز الأيام الموجودة بنفس المنتج).
    IMERG Final منذ 2000-06، CHIRPS v3 منذ 1981. يُنفَّذ على دفعات متوازية من الطلبات."""
    import asyncio
    settings = get_settings()
    sources = build_sources(settings)
    if source_key not in sources:
        raise ValueError("مصدر غير معروف")
    src = sources[source_key]
    if settings.rain_dry_run:
        raise ValueError("اكتب RAIN_DRY_RUN=false أولاً (وضع التجربة لا يجلب تاريخياً)")
    days = [d1 + timedelta(days=i) for i in range((d2 - d1).days + 1)]
    ok, failed = 0, []
    sem = asyncio.Semaphore(4)  # تهذيب ودي لخوادم المصادر

    async def one(d: date):
        nonlocal ok
        async with sem:
            try:
                g = await src.fetch_day(d, product=product) if source_key == "imerg_v07" \
                    else await src.fetch_day(d)
                await ingest_grid(db, g, src)
                ok += 1
            except Exception as e:
                failed.append({"day": str(d), "error": str(e)[:200]})

    await asyncio.gather(*(one(d) for d in days))
    await db.execute(text("SELECT refresh_rain_mvs()"))
    await db.commit()
    return {"source": source_key, "product": product, "from": str(d1), "to": str(d2),
            "ingested": ok, "failed": len(failed), "failures": failed[:20]}


# ───────────── نقطة الاستعلام ─────────────

def cell_of(lon: float, lat: float, res: float) -> tuple[int, int]:
    s = get_settings()
    ix = int((lon - s.bbox_west) // res)
    iy = int((lat - s.bbox_south) // res)
    nx = round((s.bbox_east - s.bbox_west) / res)
    ny = round((s.bbox_north - s.bbox_south) / res)
    return min(max(ix, 0), nx - 1), min(max(iy, 0), ny - 1)


async def point_query(db: AsyncSession, lat: float, lon: float, source: str) -> dict | None:
    s = get_settings()
    res = 0.1 if source == "imerg_v07" else 0.05
    ix, iy = cell_of(lon, lat, res)
    row = await db.execute(text(f"""
        SELECT sum_10d, sum_20d, sum_40d, sum_90d, sum_365d,
               wasm_sum, wasm_year, wasm_ongoing, last_rain_day
        FROM mv_rain_cell_{source} WHERE ix=:ix AND iy=:iy
    """), {"ix": ix, "iy": iy})
    r = row.first()
    if r is None:
        return None
    def rnd(x):
        return None if x is None else round(float(x), 1)
    return {
        "source": source,
        "cell": {"ix": ix, "iy": iy, "resolution_deg": res,
                 "approx_km": round(res * 111, 1)},
        "sums_mm": {"last_10d": rnd(r[0]), "last_20d": rnd(r[1]), "last_40d": rnd(r[2]),
                    "last_90d": rnd(r[3]), "last_365d": rnd(r[4])},
        "wasm": {"sum_mm": rnd(r[5]), "year": r[6], "ongoing": r[7]},
        "last_rain_day": str(r[8]) if r[8] else None,
        "last_rain_in_cell": True,
        "disclaimer": "تقدير قمر صناعي لخلية بيانات (~%g كم) — ليس قياساً في النقطة" % round(res * 111, 1),
    }


# ───────────── الفترات والوسم ─────────────

async def presets(db: AsyncSession) -> dict:
    w = (await db.execute(text("""
        SELECT win_start, win_end, win_year, ongoing
        FROM app_settings,
             LATERAL wasm_window(CURRENT_DATE, value->>'start', (value->>'length_days')::int)
        WHERE key='wasm'
    """))).first()
    wasm = {"key": "wasm", "label_ar": "الوسم",
            "start": str(w[0]), "end": str(w[1]), "year": w[2], "ongoing": w[3]}
    quick = [{"key": k, "days": d} for k, d in QUICK_PRESETS]
    return {"quick": quick, "wasm": wasm, "custom": True,
            "sources": get_settings().sources_list}


# ───────────── COG للفترات (تغذية TiTiler) ─────────────

COLORMAP = {  # عائلة خضراء→صفراء→حمراء (مميزة عن أزرق الأودية)
    "0": "#00000000", "1": "#d9f0a3", "5": "#78c679",
    "10": "#31a354", "20": "#fec44f", "40": "#f03b20", "80": "#bd0026",
}


async def period_cog_path(db: AsyncSession, source: str, d1: date, d2: date) -> str:
    """يجمّع قيم الفترة (SUM) من rain_values ويخزن COG مخبأ. يرجع المسار."""
    import rasterio
    from rasterio.transform import from_origin
    s = get_settings()
    key = f"{source}_{d1}_{d2}"
    path = os.path.join(s.data_dir, "cogs", f"{key}.tif")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        return path
    rows = await db.execute(text("""
        SELECT iy, ix, sum(val) s FROM rain_values
        WHERE source=:s AND day BETWEEN :d1 AND :d2 AND val >= 0
        GROUP BY iy, ix
    """), {"s": source, "d1": d1, "d2": d2})
    res = 0.1 if source == "imerg_v07" else 0.05
    nx = round((s.bbox_east - s.bbox_west) / res)
    ny = round((s.bbox_north - s.bbox_south) / res)
    grid = np.zeros((ny, nx), dtype=np.float32)
    n = 0
    for iy, ix, v in rows:
        grid[int(iy), int(ix)] = float(v)
        n += 1
    if n == 0:
        raise ValueError("لا بيانات للفترة المطلوبة")
    tmp = path + ".tmp"
    with rasterio.open(tmp, "w", driver="GTiff", height=ny, width=nx, count=1,
                       dtype="float32", crs="EPSG:4326",
                       transform=from_origin(s.bbox_west, s.bbox_south + ny * res, res, res),
                       nodata=-1) as ds:
        ds.write(grid, 1)
        ds.build_overviews([2, 4, 8, 16], __import__("rasterio").enums.Resampling.average)
        ds.update_tags(ns="rio_overview", resampling="average")
    os.replace(tmp, path)
    return path
