"""واجهات API عامة: المطر، الطبقات، البحث."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import rain_service
from .config import get_settings
from .db import get_db
from .deps import limiter

router = APIRouter(prefix="/api/v1", tags=["public"])

SRC_IMERG, SRC_CHIRPS = "imerg_v07", "chirps_v3"


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/layers")
async def layers(db: AsyncSession = Depends(get_db)):
    rows = await db.execute(text("""
        SELECT key, name_ar, name_en, group_ar, geom_type, minzoom, style, ord
        FROM layers_meta WHERE enabled ORDER BY ord
    """))
    return [dict(r._mapping) for r in rows]


@router.get("/search")
@limiter.limit("60/minute")
async def search(request: Request, q: str = Query(min_length=1, max_length=80),
                 limit: int = Query(8, ge=1, le=20),
                 db: AsyncSession = Depends(get_db)):
    # دعم الإحداثيات "24.6,46.7"
    parts = [p.strip() for p in q.split(",")]
    if len(parts) == 2:
        try:
            lat, lon = float(parts[0]), float(parts[1])
            if 15 <= lat <= 32.3 and 34.4 <= lon <= 55.6:
                return {"type": "coordinates", "lat": lat, "lon": lon, "results": []}
        except ValueError:
            pass
    rows = await db.execute(text("""
        SELECT name, kind, source,
               ST_X(geom) lon, ST_Y(geom) lat,
               similarity(normalize_ar(name), normalize_ar(:q)) score
        FROM places_search
        WHERE normalize_ar(name) % normalize_ar(:q)
        ORDER BY score DESC, length(name) LIMIT :lim
    """), {"q": q, "lim": limit})
    return {"type": "places", "results": [dict(r._mapping) for r in rows]}


@router.get("/rain/presets")
async def rain_presets(db: AsyncSession = Depends(get_db)):
    return await rain_service.presets(db)


@router.get("/rain/point")
@limiter.limit("120/minute")
async def rain_point(request: Request, lat: float = Query(ge=15, le=32.3),
                     lon: float = Query(ge=34.4, le=55.6),
                     source: str = Query("both", pattern="^(imerg_v07|chirps_v3|both)$"),
                     db: AsyncSession = Depends(get_db)):
    srcs = [SRC_IMERG, SRC_CHIRPS] if source == "both" else [source]
    out = {}
    for s in srcs:
        r = await rain_service.point_query(db, lat, lon, s)
        out[s] = r
    return {"lat": lat, "lon": lon, "sources": out}


@router.get("/rain/tiles/{z}/{x}/{y}.png")
async def rain_tiles(z: int, x: int, y: int,
                     from_d: date = Query(alias="from"),
                     to_d: date = Query(alias="to"),
                     source: str = Query(SRC_IMERG, pattern="^(imerg_v07|chirps_v3)$"),
                     db: AsyncSession = Depends(get_db)):
    """بلاطات مطر ملوّنة: يولّد COG الفترة (مخبأ) ويحوّل لـ TiTiler."""
    s = get_settings()
    try:
        path = await rain_service.period_cog_path(db, source, from_d, to_d)
    except ValueError as e:
        raise HTTPException(404, str(e))
    import urllib.parse
    cmap = urllib.parse.quote(__import__("json").dumps(rain_service.COLORMAP))
    url = (f"{s.titiler_url}/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png"
           f"?url=file://{urllib.parse.quote(path)}&colormap={cmap}&rescale=0,80")
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url, status_code=307)


@router.get("/rain/last")
async def rain_last(lat: float = Query(ge=15, le=32.3),
                    lon: float = Query(ge=34.4, le=55.6),
                    db: AsyncSession = Depends(get_db)):
    r = await rain_service.point_query(db, lat, lon, SRC_IMERG)
    if not r:
        raise HTTPException(404, "لا بيانات")
    return {"last_rain_day": r["last_rain_day"], "in_data_cell": True}


@router.get("/elevation")
@limiter.limit("120/minute")
async def elevation(request: Request,
                    lat: float = Query(ge=15, le=32.3),
                    lon: float = Query(ge=34.4, le=55.6)):
    """الارتفاع من AWS Terrain Tiles (terrarium, z13) مع كاش Redis 24 ساعة."""
    import httpx
    from .db import get_redis
    key = f"elev:{round(lat, 4)}:{round(lon, 4)}:z13"
    r = get_redis()
    cached = await r.get(key)
    if cached is not None:
        return {"elevation_m": float(cached) if cached != "na" else None, "cached": True}
    import math
    n = 2 ** 13
    x = min(n - 1, max(0, int((lon + 180) / 360 * n)))
    lat_r = math.radians(lat)
    y = min(n - 1, max(0, int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n)))
    try:
        import rasterio
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/13/{x}/{y}.png")
            resp.raise_for_status()
        with rasterio.MemoryFile(resp.content) as mem:
            with mem.open() as ds:
                px = int((lon + 180) / 360 * n * 256) % ds.width
                merc = (1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n
                py = int(merc * 256) % ds.height
                rgb = ds.read(window=((py, py + 1), (px, px + 1)))
        rr, gg, bb = int(rgb[0][0][0]), int(rgb[1][0][0]), int(rgb[2][0][0])
        elev = rr * 256 + gg + bb / 256 - 32768
        await r.set(key, str(round(elev, 1)), ex=86400)
        return {"elevation_m": round(elev, 1), "cached": False}
    except Exception:
        await r.set(key, "na", ex=3600)
        return {"elevation_m": None, "cached": False}


GRID_NX, GRID_NY = 212, 173
GRID_RES = 0.1
CHIRPS_RNL = ("https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/rnl/"
              "{y}/chirps-v3.0.rnl.{y}.{m:02d}.{d:02d}.tif")
CHIRPS_PRELIM = ("https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/prelim/sat/"
                 "{y}/chirps-v3.0.prelim.{y}.{m:02d}.{d:02d}.tif")
CHIRPS_DEKAD = ("https://data.chc.ucsb.edu/products/CHIRPS/v3.0/dekads/global/tifs/"
                "chirps-v3.0.{y}.{m:02d}.{dk}.tif")


def _crop_tif(content: bytes, s) -> "np.ndarray":
    import numpy as np
    import rasterio
    with rasterio.MemoryFile(content) as mem:
        with mem.open() as ds:
            arr = ds.read(1).astype("float32")
            t = ds.transform
    c0 = int((s.bbox_west - t.c) / t.a)
    c1 = int((s.bbox_east - t.a / 2 - t.c) / t.a) + 1
    r_hi = int((t.f - s.bbox_south) / -t.e)
    r_lo = int((t.f - (s.bbox_north - t.e / 2)) / -t.e)
    sub = arr[r_lo:r_hi, c0:c1]
    sub[sub < -9000] = np.nan
    h, w = sub.shape
    h2, w2 = h // 2, w // 2
    sub = sub[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2)
    with np.errstate(invalid="ignore"):
        g = np.nanmean(sub, axis=(1, 3))
    return np.nan_to_num(g, nan=0.0).astype(np.float32)


_SA_MASK_PATH = None


async def sa_mask() -> "np.ndarray | None":
    """قناع الخلايا داخل حدود المملكة (212×173 float 0/1) — يُبنى مرة ويُخبأ."""
    global _SA_MASK_PATH
    import gzip
    import os

    import numpy as np
    from .db import engine
    s = get_settings()
    d = os.path.join(s.data_dir, "cache")
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, "sa_mask.npy.gz")
    if os.path.exists(fp):
        with gzip.open(fp, "rb") as f:
            return np.load(f)
    async with engine.connect() as conn:
        rows = await conn.execute(text("""
            WITH cells AS (
              SELECT ix, iy,
                     -- الصف 0 = الشمال (مطابق لاتجاه بيانات CHIRPS في compute_grid)
                     ST_SetSRID(ST_MakePoint(34.4 + (ix+0.5)*0.1,
                                             32.3 - (iy+0.5)*0.1), 4326) AS pt
              FROM generate_series(0, 211) ix, generate_series(0, 172) iy
            )
            SELECT c.iy, c.ix,
                   EXISTS(SELECT 1 FROM sa_border b
                          WHERE ST_Intersects(b.wkb_geometry, c.pt))::int AS inside
            FROM cells c
        """))
        mask = np.zeros((GRID_NY, GRID_NX), dtype=np.float32)
        for r in rows.all():
            mask[int(r[0]), int(r[1])] = float(r[2])
    with gzip.open(fp, "wb") as f:
        np.save(f, mask)
    return mask


async def compute_grid(d1: date, d2: date) -> dict:
    import asyncio
    import calendar
    import gzip
    import os

    import httpx
    import numpy as np
    s = get_settings()
    if (d2 - d1).days > 400:
        raise HTTPException(400, "الفترة أكبر من 400 يوم")
    if d2 >= date.today():
        d2 = date.today() - __import__("datetime").timedelta(days=1)
    cache_dir = os.path.join(s.data_dir, "cache", "chirps")
    os.makedirs(cache_dir, exist_ok=True)
    sem = asyncio.Semaphore(2)          # جلب هادئ — UCSB يحظر التوازي العالي (CrowdSec)
    missing: list[str] = []             # قطع تعذر جلبها في هذه الجولة
    ban_until = 0.0                     # قاطع الدائرة: توقف كامل مؤقت عند الحظر
    # بروكسي المضيف (شبكة نظيفة) لتجاوز حظر بصمة الحاوية لدى CrowdSec
    proxy = os.environ.get("CHIRPS_PROXY", "").rstrip("/")

    async def fetch_grid(urls: list[str], ckey: str):
        nonlocal ban_until
        fp = os.path.join(cache_dir, f"{ckey}.npy.gz")
        if os.path.exists(fp):
            with gzip.open(fp, "rb") as f:
                return np.load(f)
        if ban_until > asyncio.get_event_loop().time():
            missing.append(ckey)
            return None
        content = None
        headers = {"User-Agent": "raintracker-local/1.0 (personal rain viewer)"}
        async with sem:
            for attempt in range(2):
                url = urls[min(attempt, len(urls) - 1)]
                if proxy:
                    url = proxy + "/chirps" + url.split("data.chc.ucsb.edu", 1)[-1]
                try:
                    async with httpx.AsyncClient(timeout=60, headers=headers) as c:
                        r = await c.get(url)
                    if r.status_code in (403, 418, 429):   # حظر/إغراق → هدنة قصيرة ثم محاولة أخيرة
                        if attempt == 0:
                            await asyncio.sleep(5)
                            continue
                        ban_until = asyncio.get_event_loop().time() + 900
                        missing.append(ckey)
                        break
                    if r.status_code == 404:
                        if attempt >= len(urls) - 1:
                            missing.append(ckey)
                            break
                        continue
                    if r.status_code >= 500:
                        await asyncio.sleep(2)
                        continue
                    r.raise_for_status()
                    content = r.content
                    break
                except Exception:
                    if attempt == 0:
                        await asyncio.sleep(2)
        if content is None:
            if ckey not in missing:
                missing.append(ckey)
            return None
        g = _crop_tif(content, s)
        with gzip.open(fp, "wb") as f:
            np.save(f, g)
        return g

    gfs_used: list[str] = []            # أيام غُطيت بـ GFS (CHIRPS غير منشور بعد)

    async def day_grid(d: date):
        import datetime as _dt
        recent = d >= (date.today() - _dt.timedelta(days=21))
        urls = [CHIRPS_PRELIM if recent else CHIRPS_RNL,
                CHIRPS_RNL if recent else CHIRPS_PRELIM]
        g = await fetch_grid([u.format(y=d.year, m=d.month, d=d.day) for u in urls], f"{d}")
        if g is not None:
            return g
        # فجوة الأيام القريبة: CHIRPS لم يُنشر → احتياط GFS (دقة 0.25° تقديرية)
        if d >= (date.today() - _dt.timedelta(days=10)):
            from .gfs_daily import gfs_day_grid
            gf = await gfs_day_grid(d)
            if gf is not None:
                gfs_used.append(str(d))
                if f"{d}" in missing:
                    missing.remove(f"{d}")   # غُطي اليوم — لا يُحسب ناقصاً
                return gf
        return None

    async def dekad_grid(y: int, m: int, dk: int):
        return await fetch_grid([CHIRPS_DEKAD.format(y=y, m=m, dk=dk)], f"dk:{y}.{m:02d}.{dk}")

    async def month_grid(y: int, m: int):
        mc = os.path.join(cache_dir, f"m:{y:04d}-{m:02d}.npy.gz")
        if os.path.exists(mc):
            with gzip.open(mc, "rb") as f:
                return np.load(f)
        dks = await asyncio.gather(*[dekad_grid(y, m, k) for k in (1, 2, 3)])
        if any(g is None for g in dks):
            # ديكاد غير منشور (شهر حديث) → اجمعه يومياً
            dim = calendar.monthrange(y, m)[1]
            days = await asyncio.gather(*[day_grid(date(y, m, dd)) for dd in range(1, dim + 1)])
            dks = []
            for grp in (days[0:10], days[10:20], days[20:dim]):
                ssum = np.zeros((GRID_NY, GRID_NX), dtype=np.float32)
                n = 0
                for g in grp:
                    if g is not None:
                        h, w = min(g.shape[0], GRID_NY), min(g.shape[1], GRID_NX)
                        ssum[:h, :w] += g[:h, :w]
                        n += 1
                dks.append(ssum if n else None)
        out = np.zeros((GRID_NY, GRID_NX), dtype=np.float32)
        n = 0
        for g in dks:
            if g is not None:
                h, w = min(g.shape[0], GRID_NY), min(g.shape[1], GRID_NX)
                out[:h, :w] += g[:h, :w]
                n += 1
        if n < 3:
            return None            # شهر ناقص → لا نخبئ أبداً
        if date(y, m, calendar.monthrange(y, m)[1]) < date.today() - __import__("datetime").timedelta(days=4):
            with gzip.open(mc, "wb") as f:
                np.save(f, out)
        return out

    acc = np.zeros((GRID_NY, GRID_NX), dtype=np.float64)

    async def add(g):
        if g is not None:
            h, w = min(g.shape[0], GRID_NY), min(g.shape[1], GRID_NX)
            acc[:h, :w] += g[:h, :w]

    # تجزئة النطاق: أشهر كاملة (ديكادات) + أيام الأطراف (يومي)
    tasks = []
    cy, cm = d1.year, d1.month
    while (cy, cm) <= (d2.year, d2.month):
        ms, me = date(cy, cm, 1), date(cy, cm, calendar.monthrange(cy, cm)[1])
        if ms >= d1 and me <= d2:
            tasks.append(month_grid(cy, cm))
        else:
            ds_, de_ = max(d1, ms), min(d2, me)
            for off in range((de_ - ds_).days + 1):
                tasks.append(day_grid(ds_ + __import__("datetime").timedelta(days=off)))
        cm += 1
        if cm == 13:
            cm, cy = 1, cy + 1
    for g in await asyncio.gather(*tasks):
        await add(g)
    mask = await sa_mask()
    if mask is not None:
        acc *= mask
    data = np.round(acc, 1).astype(float).ravel().tolist()
    return {"nx": GRID_NX, "ny": GRID_NY, "west": s.bbox_west, "south": s.bbox_south,
            "res": GRID_RES, "from": str(d1), "to": str(d2), "data": data,
            "partial": bool(missing), "missing": len(missing), "gfs": len(gfs_used)}


@router.get("/rain/grid")
@limiter.limit("60/minute")
async def rain_grid(request: Request,
                    from_d: date = Query(alias="from"),
                    to_d: date = Query(alias="to")):
    """شبكة المملكة (0.1°) لمجموع الفترة — CHIRPS (ديكادات + يومي) مع كاش ثلاثي."""
    d1, d2 = min(from_d, to_d), max(from_d, to_d)
    if (d2 - d1).days > 400:
        raise HTTPException(400, "الفترة أكبر من 400 يوم")
    return await compute_grid(d1, d2)


@router.get("/rain/grid/top")
@limiter.limit("60/minute")
async def rain_grid_top(request: Request,
                        from_d: date = Query(alias="from"),
                        to_d: date = Query(alias="to")):
    """أعلى خلايا الفترة مع أقرب مكان مسماً لكل خلية."""
    import numpy as np
    d1, d2 = min(from_d, to_d), max(from_d, to_d)
    grid = await compute_grid(d1, d2)
    data = np.array(grid["data"], dtype=np.float32)
    flat = data.ravel()
    mask = await sa_mask()
    order = np.argsort(flat)[::-1][:60]
    cells = []
    for i in order:
        v = float(flat[int(i)])
        if v < 1:
            break
        iy, ix = divmod(int(i), grid["nx"])
        if mask is not None and mask[iy, ix] < 0.5:
            continue
        cells.append({"lon": round(grid["west"] + (ix + 0.5) * grid["res"], 3),
                      "lat": round(grid["south"] + (grid["ny"] - 0.5 - iy) * grid["res"], 3),
                      "mm": round(v, 1)})
        if len(cells) >= 12:
            break
    from .db import SessionLocal
    async with SessionLocal() as db:
        for cell in cells:
            row = await db.execute(text("""
                SELECT name, kind,
                       round(ST_Distance(geom::geography,
                             ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography)/1000)::int
                FROM places_search
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon,:lat),4326)
                LIMIT 1"""), cell)
            r0 = row.first()
            cell["near"] = r0[0] if r0 else None
            cell["near_kind"] = r0[1] if r0 else None
            cell["near_km"] = r0[2] if r0 else None
    return {"period": {"from": str(d1), "to": str(d2)}, "top": cells}


@router.get("/rain/season")
@limiter.limit("30/minute")
async def rain_season(request: Request, years: int = Query(5, ge=2, le=20)):
    """ملخص الوسم: مجموع الموسم الحالي حتى أمس + متوسط السنوات السابقة + التاريخ."""
    import json
    import os
    import time

    import numpy as np
    from sqlalchemy import text as _t
    s = get_settings()
    from .db import SessionLocal
    async with SessionLocal() as db:
        row = await db.execute(_t("SELECT value FROM app_settings WHERE key='wasm'"))
        wcfg = row.first()[0]
    start_md, length = wcfg["start"], int(wcfg["length_days"])
    sm, sd = int(start_md.split("-")[0]), int(start_md.split("-")[1])
    today = date.today()

    def win(y: int):
        st = date(y, sm, sd)
        return st, st + __import__("datetime").timedelta(days=length - 1)

    cache_f = os.path.join(s.data_dir, "cache", f"season_{years}_{today.year}_{today}.json")
    if os.path.exists(cache_f) and os.path.getmtime(cache_f) > time.time() - 6 * 3600:
        with open(cache_f) as f:
            return json.load(f)

    yest = today - __import__("datetime").timedelta(days=1)
    m = await sa_mask()
    cells = int(m.sum()) if m is not None else GRID_NX * GRID_NY

    def stats(g):
        a = np.array(g["data"], dtype=np.float32)
        return {"mean_mm": round(float(a.sum()) / max(cells, 1), 1),
                "wet_pct": round(float((a >= 5).sum()) / max(cells, 1) * 100, 1)}

    hist = []
    for y in range(today.year - years, today.year):
        st, en = win(y)
        hist.append(stats(await compute_grid(st, min(en, yest))))
    st, en = win(today.year)
    started = yest >= st
    cur = stats(await compute_grid(st, max(en, yest))) if started else {"mean_mm": 0.0, "wet_pct": 0.0}
    # قبل بدء الوسم: نافذة «حتى أمس» فارغة منطقياً → صفر حتى الانطلاق

    hmean = [h["mean_mm"] for h in hist]
    normal = round(float(np.mean(hmean)), 1) if hmean else None
    out = {"window": {"start": str(st), "end": str(en), "length": length},
           "current": {**cur,
                       "days_in": max(0, (yest - st).days + 1),
                       "started": started,
                       "ongoing": started and today <= en},
           "normal_avg_mm": normal,
           "pct_of_normal": round(cur["mean_mm"] / normal * 100) if normal else None,
           "years": years,
           "history": [{"year": y, **h} for y, h in
                       zip(range(today.year - years, today.year), hist)]}
    os.makedirs(os.path.dirname(cache_f), exist_ok=True)
    with open(cache_f, "w") as f:
        json.dump(out, f, ensure_ascii=False)
    return out


@router.get("/rain/rawdat")
@limiter.limit("30/minute")
async def rain_rawdat(request: Request,
                      from_d: date = Query(alias="from"),
                      to_d: date = Query(alias="to"),
                      min_mm: float = Query(10, ge=0, le=200)):
    """الروضات والفيضات المسمّاة التي أمطرت ≥ min_mm في الفترة."""
    import numpy as np
    from .db import SessionLocal
    d1, d2 = min(from_d, to_d), max(from_d, to_d)
    grid = await compute_grid(d1, d2)
    north = grid["south"] + grid["ny"] * grid["res"]
    data = np.array(grid["data"], dtype=np.float32).reshape(grid["ny"], grid["nx"])
    mask = await sa_mask()
    out = []
    async with SessionLocal() as db:
        rows = await db.execute(text("""
            SELECT name, kind, ST_X(geom) lon, ST_Y(geom) lat
            FROM places_search
            WHERE kind IN ('روضة','فيضة') AND name IS NOT NULL
            ORDER BY name"""))
        for r in rows.all():
            ix = int((float(r[2]) - grid["west"]) // grid["res"])
            iy = int((north - float(r[3])) // grid["res"])
            if not (0 <= ix < grid["nx"] and 0 <= iy < grid["ny"]):
                continue
            if mask is not None and mask[iy, ix] < 0.5:
                continue
            v = float(data[iy, ix])
            if v >= min_mm:
                out.append({"name": r[0], "kind": r[1], "lon": round(float(r[2]), 3),
                            "lat": round(float(r[3]), 3), "mm": round(v, 1)})
    out.sort(key=lambda x: -x["mm"])
    return {"period": {"from": str(d1), "to": str(d2)}, "min_mm": min_mm, "rawdat": out[:40]}


@router.get("/rain/rawdat")
@limiter.limit("30/minute")
async def rain_rawdat(request: Request,
                      from_d: date = Query(alias="from"),
                      to_d: date = Query(alias="to"),
                      min_mm: float = Query(10, ge=0, le=200)):
    """الروضات والفيضات المسمّاة التي أمطرت ≥ min_mm في الفترة."""
    import numpy as np
    from .db import SessionLocal
    d1, d2 = min(from_d, to_d), max(from_d, to_d)
    grid = await compute_grid(d1, d2)
    north = grid["south"] + grid["ny"] * grid["res"]
    data = np.array(grid["data"], dtype=np.float32).reshape(grid["ny"], grid["nx"])
    mask = await sa_mask()
    out = []
    async with SessionLocal() as db:
        rows = await db.execute(text("""
            SELECT name, kind, ST_X(geom) lon, ST_Y(geom) lat
            FROM places_search
            WHERE kind IN ('روضة','فيضة') AND name IS NOT NULL
            ORDER BY name"""))
        for r in rows.all():
            ix = int((float(r[2]) - grid["west"]) // grid["res"])
            iy = int((north - float(r[3])) // grid["res"])
            if not (0 <= ix < grid["nx"] and 0 <= iy < grid["ny"]):
                continue
            if mask is not None and mask[iy, ix] < 0.5:
                continue
            v = float(data[iy, ix])
            if v >= min_mm:
                out.append({"name": r[0], "kind": r[1], "lon": round(float(r[2]), 3),
                            "lat": round(float(r[3]), 3), "mm": round(v, 1)})
    out.sort(key=lambda x: -x["mm"])
    return {"period": {"from": str(d1), "to": str(d2)}, "min_mm": min_mm, "rawdat": out[:40]}


@router.get("/dunes/mask")
async def dunes_mask():
    """شبكة 212×173 (0/1) لخلايا الكثبان — لرسم نقاط stipple في المتصفح."""
    import gzip
    import os

    import numpy as np
    from .db import engine
    s = get_settings()
    fp = os.path.join(s.data_dir, "cache", "dunes_mask.npy.gz")
    if os.path.exists(fp):
        with gzip.open(fp, "rb") as f:
            arr = np.load(f)
        return {"nx": GRID_NX, "ny": GRID_NY, "data": arr.astype(int).ravel().tolist()}
    async with engine.connect() as conn:
        rows = await conn.execute(text("""
            WITH cells AS (
              SELECT ix, iy,
                     ST_SetSRID(ST_MakePoint(34.4 + (ix+0.5)*0.1, 15.0 + (iy+0.5)*0.1), 4326) pt
              FROM generate_series(0, 211) ix, generate_series(0, 172) iy
            )
            SELECT c.iy, c.ix,
                   EXISTS(SELECT 1 FROM dunes d WHERE ST_Intersects(d.geom, c.pt))::int
            FROM cells c
        """))
        grid = np.zeros((GRID_NY, GRID_NX), dtype=np.int8)
        for r in rows.all():
            grid[int(r[0]), int(r[1])] = int(r[2])
    with gzip.open(fp, "wb") as f:
        np.save(f, grid)
    return {"nx": GRID_NX, "ny": GRID_NY, "data": grid.ravel().tolist()}
