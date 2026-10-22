"""مطر اليوم من نماذج GFS (NOAA/NOMADS) — تغطية الأيام الأخيرة قبل نشر CHIRPS.

CHIRPS يتأخر ~4 أيام؛ GFS يغطيها بنماذج 0.25° تُنشر بعد ~6 ساعات.
لكل يوم D نأخذ دورة D 00Z وساعة التوقع f024 = تراكم المطر بين 00Z و24Z.
"""
import gzip
import os
import tempfile
from datetime import date

import httpx
import numpy as np

from .config import get_settings

GRID_NX, GRID_NY = 212, 173
WEST, NORTH, RES = 34.4, 32.3, 0.1

FILTER_URL = ("https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
              "?dir=%2Fgfs.{y}{m:02d}{d:02d}%2F00%2Fatmos"
              "&file=gfs.t00z.pgrb2.0p25.f024&var_APCP=on&lev_surface=on"
              "&subregion=&leftlon=30&rightlon=60&toplat=35&bottomlat=12")


async def gfs_day_grid(day: date) -> "np.ndarray | None":
    """شبكة 212×173 (مم) لمطر يوم محدد من GFS، أو None إن تعذر."""
    s = get_settings()
    cache_dir = os.path.join(s.data_dir, "cache", "gfs")
    os.makedirs(cache_dir, exist_ok=True)
    fp = os.path.join(cache_dir, f"{day}.npy.gz")
    if os.path.exists(fp):
        with gzip.open(fp, "rb") as f:
            return np.load(f)

    url = FILTER_URL.format(y=day.year, m=day.month, d=day.day)
    try:
        async with httpx.AsyncClient(timeout=150) as c:
            r = await c.get(url)
        if r.status_code != 200 or len(r.content) < 1000:
            return None

        import xarray as xr
        tmp = tempfile.NamedTemporaryFile(suffix=".grb", delete=False)
        try:
            tmp.write(r.content)
            tmp.close()
            ds = xr.open_dataset(tmp.name, engine="cfgrib")
            tp = ds["tp"]
            vals = tp.values.astype("float32")
            if tp.attrs.get("units") == "m":          # cfgrib يحول أحياناً إلى أمتار
                vals *= 1000.0
        finally:
            os.unlink(tmp.name)

        lats = ds["latitude"].values
        lons = ds["longitude"].values
        lons = np.where(lons > 180, lons - 360, lons)
        lat_desc = lats[0] > lats[-1]                 # GFS عادة من الشمال للجنوب
        if lat_desc:
            vals = vals[::-1, :]
            lats = lats[::-1]
        lat0, lon0 = float(lats[0]), float(lons[0])
        step = float(lats[1] - lats[0]) or 0.25

        out = np.zeros((GRID_NY, GRID_NX), dtype=np.float32)
        for iy in range(GRID_NY):
            lat_t = NORTH - (iy + 0.5) * RES
            sy = int(round((lat_t - lat0) / step))
            if sy < 0 or sy >= vals.shape[0]:
                continue
            row = vals[sy]
            for ix in range(GRID_NX):
                lon_t = WEST + (ix + 0.5) * RES
                sx = int(round((lon_t - lon0) / step))
                if 0 <= sx < row.shape[0]:
                    out[iy, ix] = row[sx]
        with gzip.open(fp, "wb") as f:
            np.save(f, out)
        return out
    except Exception:
        return None
