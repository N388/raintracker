"""واجهات لوحة التحكم (JWT): المصادقة، ETL، الإعدادات، الطبقات، السجلات."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import rain_service, security
from .config import get_settings
from .db import get_db
from .deps import limiter, require_admin

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
@limiter.limit("10/minute")
async def login(request: Request, body: LoginIn):
    s = get_settings()
    if body.email != s.admin_email or not security.verify_password(body.password, security.hash_password(s.admin_password)):
        # مقارنة آمنة ثابتة الزمن ضد الهاش المحسوب
        raise HTTPException(401, "بيانات الدخول غير صحيحة")
    return {"access_token": security.make_token(body.email), "token_type": "bearer"}


@router.get("/auth/me")
async def me(email: str = Depends(require_admin)):
    return {"email": email, "role": "admin"}


@router.post("/etl/run")
async def etl_run(only: str | None = None, email: str = Depends(require_admin),
                  db: AsyncSession = Depends(get_db)):
    report = await rain_service.run_etl(db, only)
    await db.execute(text(
        "INSERT INTO audit_logs (actor, action, meta) VALUES (:a, 'etl.run', :m)"),
        {"a": email, "m": __import__("json").dumps(report)})
    await db.commit()
    return report


class BackfillIn(BaseModel):
    source: str = Field(pattern="^(imerg_v07|chirps_v3)$")
    from_d: str = Field(alias="from")
    to_d: str = Field(alias="to")
    product: str = Field("final", pattern="^(final|late)$")

    model_config = {"populate_by_name": True}


@router.post("/etl/backfill")
async def etl_backfill(body: BackfillIn, email: str = Depends(require_admin),
                       db: AsyncSession = Depends(get_db)):
    """اكتتاب تاريخي (قد يستغرق وقتاً طويلاً — نفّذه بدفعات سنوية)."""
    from datetime import date as _date
    d1, d2 = _date.fromisoformat(body.from_d), _date.fromisoformat(body.to_d)
    if d1 > d2 or (d2 - d1).days > 370:
        raise HTTPException(400, "نطاق غير صالح أو أكبر من سنة — قسّمه لدفعات")
    run = await db.execute(text(
        "INSERT INTO etl_runs (job, product, status) VALUES ('backfill', :p, 'running') RETURNING id"),
        {"p": f"{body.source}_{body.product}"})
    run_id = run.scalar()
    await db.commit()
    try:
        report = await rain_service.backfill(db, body.source, d1, d2, body.product)
        await db.execute(text(
            "UPDATE etl_runs SET status='ok', finished_at=now(), stats=:s WHERE id=:i"),
            {"s": __import__("json").dumps(report), "i": run_id})
    except Exception as e:
        await db.execute(text(
            "UPDATE etl_runs SET status='error', finished_at=now(), error=:e WHERE id=:i"),
            {"e": str(e)[:500], "i": run_id})
        await db.commit()
        raise HTTPException(400, str(e))
    await db.execute(text(
        "INSERT INTO audit_logs (actor, action, meta) VALUES (:a, 'etl.backfill', :m)"),
        {"a": email, "m": __import__("json").dumps(report)})
    await db.commit()
    return report


@router.get("/etl/runs")
async def etl_runs(limit: int = 20, db: AsyncSession = Depends(get_db),
                   _: str = Depends(require_admin)):
    rows = await db.execute(text(
        "SELECT id, job, product, status, started_at, finished_at, stats FROM etl_runs ORDER BY id DESC LIMIT :l"),
        {"l": limit})
    return [dict(r._mapping) for r in rows]


@router.get("/settings")
async def settings_get(db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    rows = await db.execute(text("SELECT key, value FROM app_settings"))
    return {r[0]: r[1] for r in rows}


class SettingsPut(BaseModel):
    value: dict


@router.put("/settings/{key}")
async def settings_put(key: str, body: SettingsPut, email: str = Depends(require_admin),
                       db: AsyncSession = Depends(get_db)):
    if key not in ("wasm", "qa_threshold_pct", "rain_sources"):
        raise HTTPException(400, "مفتاح غير قابل للتعديل")
    await db.execute(text(
        "INSERT INTO app_settings (key, value) VALUES (:k, :v) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value"),
        {"k": key, "v": __import__("json").dumps(body.value)})
    await db.execute(text("SELECT refresh_rain_mvs()"))
    await db.commit()
    return {"ok": True}


@router.post("/indexes/rebuild")
async def rebuild(email: str = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    await db.execute(text("SELECT refresh_rain_mvs()"))
    await db.commit()
    return {"ok": True, "refreshed": ["mv_rain_cell_imerg_v07", "mv_rain_cell_chirps_v3"]}


@router.get("/layers")
async def layers_all(db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    rows = await db.execute(text("SELECT * FROM layers_meta ORDER BY ord"))
    return [dict(r._mapping) for r in rows]


class LayerPut(BaseModel):
    name_ar: str | None = None
    enabled: bool | None = None
    style: dict | None = None
    ord: int | None = None


@router.put("/layers/{key}")
async def layer_put(key: str, body: LayerPut, email: str = Depends(require_admin),
                    db: AsyncSession = Depends(get_db)):
    await db.execute(text("""
        UPDATE layers_meta SET
          name_ar = coalesce(:na, name_ar),
          enabled = coalesce(:en, enabled),
          style   = coalesce(:st, style),
          ord     = coalesce(:ord, ord)
        WHERE key = :k
    """), {"k": key, "na": body.name_ar, "en": body.enabled, "st": body.style, "ord": body.ord})
    await db.commit()
    return {"ok": True}


@router.get("/logs")
async def logs(limit: int = 50, db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    rows = await db.execute(text(
        "SELECT id, actor, action, meta, at FROM audit_logs ORDER BY id DESC LIMIT :l"), {"l": limit})
    return [dict(r._mapping) for r in rows]


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db), _: str = Depends(require_admin)):
    days = await db.scalar(text("SELECT count(DISTINCT day) FROM rain_daily"))
    cells = await db.scalar(text("SELECT count(*) FROM rain_values"))
    layers = await db.scalar(text("SELECT count(*) FROM layers_meta WHERE enabled"))
    return {"rain_days": days, "rain_values": cells, "enabled_layers": layers}
