#!/usr/bin/env python3
"""NDVI وطني من Sentinel-2 L2A عبر STAC (Earth Search) — تركيب آخر-بكسل-صالح بقناع SCL.

الخرج: /data/ndvi_cog.tif (uint8 = NDVI*100+100، 255=nodata) + /data/ndvi_meta.json
"""
import asyncio
import json
import os
import re
import sys

import httpx
import numpy as np

STAC = "https://earth-search.aws.element84.com/v1/search"
WEST, SOUTH, EAST, NORTH = 34.4, 15.0, 55.6, 32.3
RES = 0.001
NX = int((EAST - WEST) / RES)
NY = int((NORTH - SOUTH) / RES)

argv = " ".join(sys.argv)
DAYS = int(re.search(r"--days (\d+)", argv).group(1)) if "--days" in argv else 120
SCENES_PER_TILE = int(re.search(r"--per-tile (\d+)", argv).group(1)) if "--per-tile" in argv else 2
MAX_TILES = int(re.search(r"--max-tiles (\d+)", argv).group(1)) if "--max-tiles" in argv else 70


async def collect(client):
    from datetime import date, timedelta
    start = (date.today() - timedelta(days=DAYS)).isoformat()
    end = date.today().isoformat()
    body = {"collections": ["sentinel-2-l2a"],
            "bbox": [WEST, SOUTH, EAST, NORTH],
            "datetime": f"{start}T00:00:00Z/{end}T00:00:00Z",
            "limit": 200,
            "query": {"eo:cloud_cover": {"lt": 60}}}
    feats, url, method = [], STAC, "post"
    for page in range(6):
        for attempt in range(5):
            try:
                if method == "post":
                    r = await client.post(url, json=body, timeout=90)
                else:
                    r = await client.get(url, timeout=90)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            r = None
            await asyncio.sleep(4 * (attempt + 1))
        if r is None or r.status_code != 200:
            raise RuntimeError(f"STAC فشل ص {page}: {r.status_code if r else 'شبكة'}")
        j = r.json()
        feats += j.get("features", [])
        nxt = next((l for l in j.get("links", []) if l.get("rel") == "next"), None)
        if not nxt or not j.get("features"):
            break
        if nxt.get("method", "GET").upper() == "GET" and nxt.get("href"):
            url, method = nxt["href"], "get"
        elif nxt.get("body"):
            body.update(nxt["body"])
        else:
            break
    print(f"STAC: {len(feats)} مشهداً", flush=True)
    by_tile = {}
    for f in feats:
        code = f["properties"].get("grid:code") or f["id"]
        by_tile.setdefault(code, []).append(f)
    picked, n_codes = [], 0
    for code, lst in by_tile.items():
        n_codes += 1
        if n_codes > MAX_TILES:
            break
        lst.sort(key=lambda f: f["properties"]["datetime"], reverse=True)
        # الأفضل سحابياً ضمن أحدث 4 ثم الأحدث تاريخاً
        best = sorted(lst[:4], key=lambda f: (f["properties"].get("eo:cloud_cover") or 0))[:SCENES_PER_TILE]
        for f in best:
            a = f["assets"]
            if all(k in a for k in ("red", "nir08", "scl")):
                picked.append({"code": code,
                               "date": f["properties"]["datetime"][:10],
                               "cloud": round(f["properties"].get("eo:cloud_cover") or 0),
                               "red": a["red"]["href"], "nir08": a["nir08"]["href"],
                               "scl": a["scl"]["href"]})
    print(f"مربعات: {len(by_tile)} — مشاهد مختارة: {len(picked)}", flush=True)
    return picked


async def process_tile(client, scene, comp, valid):
    import rasterio
    from rasterio.transform import from_origin
    from rasterio.warp import reproject, Resampling
    try:
        # روابط COG تنتهي بمسار المشهد — نجرب الملف المباشر أولاً
        async def band_url(href, band):
            for cand in (href, f"{href}/{band}.tif", f"{href.split('/L2A')[0]}/L2A{href.split('L2A')[-1]}/{band}.tif"):
                try:
                    rr = await client.head(cand, timeout=20)
                    if rr.status_code == 200:
                        return cand
                except Exception:
                    continue
            return None
        u_red = await band_url(scene["red"], "B04")
        u_nir = await band_url(scene["nir08"], "B8A")
        u_scl = await band_url(scene["scl"], "SCL")
        if not (u_red and u_nir and u_scl):
            print(f"  ✗ روابط ناقصة {scene['code']} {scene['date']}", flush=True)
            return False
        with rasterio.open(u_red) as b4, rasterio.open(u_nir) as b8a, rasterio.open(u_scl) as scl:
            red = b4.read(1).astype(np.float32)
            nir = b8a.read(1, out_shape=(b4.height, b4.width),
                           resampling=Resampling.nearest).astype(np.float32)
            sc = scl.read(1, out_shape=(b4.height, b4.width),
                          resampling=Resampling.nearest)
            ok = (sc == 4) | (sc == 5)
            ndvi = np.full(red.shape, np.nan, dtype=np.float32)
            denom = nir + red
            good = ok & (denom > 0) & (nir > 0) & (red >= 0)
            ndvi[good] = (nir[good] - red[good]) / denom[good]
            scaled = ((ndvi + 1.0) * 100).clip(0, 200).astype(np.uint8)
            scaled[~good] = 255
            dst = np.full((NY, NX), 255, dtype=np.uint8)
            reproject(source=scaled, destination=dst,
                      src_transform=b4.transform, src_crs=b4.crs, src_nodata=255,
                      dst_transform=from_origin(WEST, NORTH, RES, RES),
                      dst_crs="EPSG:4326", dst_nodata=255,
                      resampling=Resampling.nearest)
    except Exception as e:
        print(f"  ✗ {scene['code']} {scene['date']}: {str(e)[:80]}", flush=True)
        return False
    fill = (dst != 255) & ~valid
    comp[fill] = dst[fill]
    valid |= fill
    return True


async def main():
    comp = np.full((NY, NX), 255, dtype=np.uint8)
    valid = np.zeros((NY, NX), dtype=bool)
    sem = asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
        scenes = await collect(client)

        async def one(s):
            async with sem:
                ok = await process_tile(client, s, comp, valid)
                print(f"  {'✓' if ok else '✗'} {s['code']} {s['date']} غيوم {s['cloud']}٪", flush=True)
        await asyncio.gather(*[one(s) for s in scenes])

    cov = float(valid.mean() * 100)
    print(f"تغطية وطنية: {cov:.1f}٪", flush=True)
    import rasterio
    from rasterio.transform import from_origin
    out = "/data/ndvi_cog.tif"
    with rasterio.open(out, "w", driver="GTiff", height=NY, width=NX, count=1,
                       dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(WEST, NORTH, RES, RES),
                       nodata=255, compress="deflate") as ds:
        ds.write(comp, 1)
        ds.build_overviews([2, 4, 8, 16], rasterio.enums.Resampling.nearest)
    with open("/data/ndvi_meta.json", "w") as f:
        json.dump({"generated": __import__("datetime").datetime.now().isoformat(),
                   "scenes": len(scenes), "coverage_pct": round(cov, 1),
                   "days_window": DAYS}, f)
    print(f"تم: {out} ({os.path.getsize(out)/1e6:.0f}MB)", flush=True)


asyncio.run(main())
