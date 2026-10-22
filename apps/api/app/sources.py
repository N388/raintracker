"""محوّلات مصادر المطر (نمط Adapter — إضافة مصدر جديد = محوّل + سطر إعداد).

كل محوّل يجلب يوماً واحداً ويعيد Grid موحّد: قيم mm/اليوم على شبكة
غرب=34.4 جنوب=15.0 بدقة المصدر الأصلية (لا إعادة أخذ عينات).
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

import numpy as np


@dataclass
class Grid:
    day: date
    values: np.ndarray  # [iy, ix] float32، الشمال أعلى الصفوف
    res: float
    west: float = 34.4
    south: float = 15.0

    @property
    def nx(self) -> int:
        return self.values.shape[1]

    @property
    def ny(self) -> int:
        return self.values.shape[0]


class RainSource(Protocol):
    key: str
    res: float
    product: str
    west: float
    south: float

    async def missing_days(self, have_up_to: date | None) -> list[date]: ...
    async def fetch_day(self, day: date) -> Grid: ...


class SourceBase:
    key = "base"
    res = 0.1
    product = "latest"
    west, south = 34.4, 15.0
    east, north = 55.6, 32.3

    @property
    def nx(self) -> int:
        return round((self.east - self.west) / self.res)

    @property
    def ny(self) -> int:
        return round((self.north - self.south) / self.res)


def crop_with_transform(arr: np.ndarray, transform, src: SourceBase, day: date) -> Grid:
    """اقصّ مصفوفة كاملة (مع تحويل أفين) على صندوق شبكتنا عبر rasterio.index."""
    # صفوف/أعمدة الزوايا
    r_n, c_w = 0, 0
    from affine import Affine
    inv = ~transform
    # إحداثيات البكسل: المركز = (col+0.5, row+0.5)
    def col_of(lon: float) -> int:
        return int(round(inv[2] + inv[0] * lon - 0.5))
    def row_of(lat: float) -> int:
        return int(round(inv[5] + inv[4] * lat - 0.5))
    c0, c1 = col_of(src.west), col_of(src.east - src.res) + 1
    r0, r1 = row_of(src.north - src.res) + 1, row_of(src.south)   # قد يكون معكوساً
    r_lo, r_hi = min(r0, r1), max(r0, r1)
    sub = arr[r_lo:r_hi, c0:c1]
    if r0 > r1:          # خط العرض تنازلي في المصدر
        sub = sub[::-1, :]
    # ضبط الأبعاد بالضبط (حماية من فروق التقريب)
    if sub.shape != (src.ny, src.nx):
        fixed = np.zeros((src.ny, src.nx), dtype=np.float32)
        h, w = min(src.ny, sub.shape[0]), min(src.nx, sub.shape[1])
        fixed[:h, :w] = sub[:h, :w]
        sub = fixed
    return Grid(day=day, values=sub.astype(np.float32), res=src.res,
                west=src.west, south=src.south)


class SampleSource(SourceBase):
    """مصدر اصطناعي deterministic لوضع التجربة (بلا أي اتصال خارجي)."""

    def __init__(self, key: str, res: float):
        self.key = key
        self.res = res
        self.product = f"{key}_sample"

    async def missing_days(self, have_up_to: date | None) -> list[date]:
        end = date.today() - timedelta(days=2)  # محاكاة مهلة النشر
        start = (have_up_to + timedelta(days=1)) if have_up_to else end - timedelta(days=3)
        if start > end:
            return []
        return [start + timedelta(days=i) for i in range((end - start).days + 1)]

    async def fetch_day(self, day: date) -> Grid:
        rng = np.random.default_rng(seed=day.toordinal() + (0 if self.res > 0.07 else 7))
        yy, xx = np.mgrid[0:self.ny, 0:self.nx]
        waves = (np.sin(xx / 17.0 + day.toordinal() / 5.0) * np.cos(yy / 23.0)
                 + 0.5 * np.sin((xx + yy) / 11.0 + day.toordinal() / 3.0))
        bursts = rng.exponential(0.4, size=(self.ny, self.nx)) * (waves > 0.35)
        vals = np.clip(bursts, 0, 90).astype(np.float32)
        vals[waves <= 0.35] = 0.0
        return Grid(day=day, values=vals, res=self.res)


class ImergV07(SourceBase):
    """NASA GPM IMERG V07 — المنتج اليومي (Late حديث، يُستبدل بـ Final عند نضجه)."""
    key = "imerg_v07"
    res = 0.1
    product = "imerg_late"
    URL_LATE = ("https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/GPM_3IMERGDL.07/"
                "{y}/{m}/3B-DAY-L.MS.MRG.3IMERG.{y}{m}{d}-S000000-E235959.V07B.nc4")
    URL_FINAL = ("https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/GPM_3IMERGDF.07/"
                 "{y}/{m}/3B-DAY.MS.MRG.3IMERG.{y}{m}{d}-S000000-E235959.V07B.nc4")

    def __init__(self, user: str, password: str):
        self.auth = (user, password)

    async def missing_days(self, have_up_to: date | None) -> list[date]:
        # استحقاق D-2 بعد 36 ساعة من منتصف الليل UTC (خطة §4.5)
        from .util import utcnow
        now = utcnow()
        due = (now.date() - timedelta(days=2)) if now.hour >= 12 else (now.date() - timedelta(days=3))
        start = (have_up_to + timedelta(days=1)) if have_up_to else due - timedelta(days=4)
        if start > due:
            return []
        return [start + timedelta(days=i) for i in range((due - start).days + 1)]

    async def fetch_day(self, day: date, product: str = "late") -> Grid:
        import httpx, rasterio, os
        tpl = self.URL_FINAL if product == "final" else self.URL_LATE
        url = tpl.format(y=f"{day.year:04d}", m=f"{day.month:02d}", d=f"{day.day:02d}")
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
            r = await c.get(url, auth=self.auth)
            r.raise_for_status()
        tmp = f"/tmp/imerg_{day}.nc4"
        with open(tmp, "wb") as f:
            f.write(r.content)
        try:
            with rasterio.open(tmp) as ds:
                sds = next(s for s in ds.subdatasets if "precipitationCal" in s)
            with rasterio.open(sds) as band:
                arr = band.read(1).astype("float32")
                arr[arr < 0] = 0.0
                t = band.transform
        finally:
            os.unlink(tmp)
        return crop_with_transform(arr, t, self, day)


class ChirpsV3(SourceBase):
    """CHIRPS v3 — يومي 0.05° عبر HTTP بلا مصادقة."""
    key = "chirps_v3"
    res = 0.05
    product = "chirps_v3_daily"
    URL = ("https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/tifs/p05/"
           "{y}/chirps-v3.0.{y}.{m}.{d}.tif")

    async def missing_days(self, have_up_to: date | None) -> list[date]:
        due = date.today() - timedelta(days=3)  # أولي ~3 أيام
        start = (have_up_to + timedelta(days=1)) if have_up_to else due - timedelta(days=4)
        if start > due:
            return []
        return [start + timedelta(days=i) for i in range((due - start).days + 1)]

    async def fetch_day(self, day: date) -> Grid:
        import httpx, rasterio, os
        url = self.URL.format(y=day.year, m=f"{day.month:02d}", d=f"{day.day:02d}")
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
            r = await c.get(url)
            r.raise_for_status()
        tmp = f"/tmp/chirps_{day}.tif"
        with open(tmp, "wb") as f:
            f.write(r.content)
        try:
            with rasterio.open(tmp) as ds:
                arr = ds.read(1).astype("float32")
                if ds.nodata is not None:
                    arr[arr == ds.nodata] = 0.0
                t = ds.transform
        finally:
            os.unlink(tmp)
        return crop_with_transform(arr, t, self, day)


def build_sources(settings) -> dict[str, RainSource]:
    """سجل المحوّلات المفعّلة. إضافة مصدر مستقبلي (ERA5/Open-Meteo/محطات) تتم هنا فقط."""
    registry: dict[str, RainSource] = {}
    for key in settings.sources_list:
        if settings.rain_dry_run:
            registry[key] = SampleSource(key, res=0.1 if key == "imerg_v07" else 0.05)
        elif key == "imerg_v07":
            registry[key] = ImergV07(settings.earthdata_username, settings.earthdata_password)
        elif key == "chirps_v3":
            registry[key] = ChirpsV3()
    return registry
