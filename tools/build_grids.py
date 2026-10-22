#!/usr/bin/env python3
"""يولّد شبكات المطر الثابتة للنسخة العامة (GitHub Pages).

يعيد استخدام compute_grid من تطبيق الـ API نفسه (CHIRPS + احتياط GFS + قناع
الحدود) ويكتب النتائج JSON تحت data/grids/ — تستهلكها الواجهة الساكنة مباشرة.

التشغيل: python3 tools/build_grids.py
"""
import asyncio
import json
import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_DIR = os.environ.get("API_DIR", os.path.join(ROOT, "apps/api"))
sys.path.insert(0, API_DIR)

# بيئة افتراضية للاستيراد خارج الحاوية (لا اتصال فعلي بقاعدة البيانات)
os.environ.setdefault("DATA_DIR", os.path.join(ROOT, "data/tiles"))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost:1/x")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.pop("CHIRPS_PROXY", None)

from app.api_v1 import compute_grid  # noqa: E402

OUT = os.environ.get("GRIDS_OUT", os.path.join(ROOT, "data", "grids"))
DAILY_DAYS = 45          # عدد الأيام اليومية المتاحة في النسخة العامة


def wasm_window(today: date):
    """مطابقة لمنطق wasmWindow في الواجهة: موسم 52 يوماً من 16 أكتوبر."""
    s = date(today.year, 10, 16)
    if today >= s:
        return s, today
    prev = date(today.year - 1, 10, 16)
    return prev, prev + timedelta(days=51)


async def main() -> None:
    os.makedirs(os.path.join(OUT, "day"), exist_ok=True)
    today = date.today()
    y = today - timedelta(days=1)

    targets: dict[str, tuple[date, date]] = {}
    for n in (3, 7, 10, 20, 30, 40, 60, 90, 120, 180):
        targets[f"{n}days"] = (y - timedelta(days=n), y)
    w1, w2 = wasm_window(today)
    targets["wasm"] = (w1, min(w2, y))
    for i in range(DAILY_DAYS):
        d = y - timedelta(days=i)
        targets[f"day/{d}"] = (d, d)

    ok = fail = 0
    for key, (a, b) in sorted(targets.items()):
        path = os.path.join(OUT, key + ".json")
        try:
            r = await compute_grid(a, b)
            r["key"] = key
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False)
            os.replace(tmp, path)
            ok += 1
            print(f"✓ {key:22s} partial={r['partial']} gfs={r.get('gfs', 0)} max={max(r['data'])}")
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"✗ {key:22s} {str(e)[:140]}")
    print(f"تم: {ok} — فشل: {fail}")


if __name__ == "__main__":
    asyncio.run(main())
