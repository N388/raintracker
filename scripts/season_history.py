"""أغزر سنوات الوسم في السعودية 1981-اليوم — CHIRPS v3 عبر compute_grid."""
import asyncio
import json
from datetime import date, timedelta

import numpy as np
from sqlalchemy import text

from app.api_v1 import compute_grid, sa_mask
from app.db import engine


async def main():
    async with engine.connect() as c:
        r = await c.execute(text("SELECT value FROM app_settings WHERE key='wasm'"))
        w = r.first()[0]
    sm, sd = map(int, w["start"].split("-"))
    length = int(w["length_days"])
    mask = await sa_mask()
    cells = max(int(mask.sum()), 1)
    async def one(y: int):
        st = date(y, sm, sd)
        en = st + timedelta(days=length - 1)
        g = await compute_grid(st, en)
        a = np.array(g["data"], dtype=np.float32)
        return {"year": y,
                "mean_mm": round(float(a.sum()) / cells, 1),
                "wet_area_pct": round(float((a >= 10).sum()) / cells * 100, 1)}

    # دفعات صغيرة لتخفيف الخنق على المصدر
    years = list(range(1981, date.today().year))
    results, done = [], 0
    for i in range(0, len(years), 5):
        batch = years[i:i + 5]
        async def wrapped(y):
            nonlocal done
            r = await one(y)
            done += 1
            print(f"[{done}/{len(years)}] {r['year']}: {r['mean_mm']} مم", flush=True)
            return r
        results += await asyncio.gather(*[wrapped(y) for y in batch])
    results.sort(key=lambda r: -r["mean_mm"])
    with open("/data/season_history.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("=== أغزر 10 ===")
    for r in results[:10]:
        print(f"{r['year']}: {r['mean_mm']} مم (أراضٍ ≥10مم: {r['wet_area_pct']}٪)")


asyncio.run(main())
