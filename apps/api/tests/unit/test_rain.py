"""اختبارات وحدية لمنطق المطر (بلا قاعدة بيانات)."""
import asyncio
from datetime import date

from app.rain_service import cell_of, COLORMAP
from app.sources import SampleSource


def test_cell_of_inside_bbox():
    ix, iy = cell_of(46.68, 24.71, 0.1)
    assert (ix, iy) == (int((46.68 - 34.4) // 0.1), int((24.71 - 15.0) // 0.1))


def test_cell_of_clamps_edges():
    s = 0.05
    nx = round((55.6 - 34.4) / s)
    ny = round((32.3 - 15.0) / s)
    assert cell_of(99.0, 99.0, s) == (nx - 1, ny - 1)
    assert cell_of(-99.0, -99.0, s) == (0, 0)


def test_sample_source_deterministic():
    src = SampleSource("imerg_v07", 0.1)
    g1 = asyncio.run(src.fetch_day(date(2026, 1, 15)))
    g2 = asyncio.run(src.fetch_day(date(2026, 1, 15)))
    assert g1.values.shape == (173, 212)
    assert (g1.values == g2.values).all()
    assert g1.values.min() >= 0


def test_sample_source_differs_by_day():
    src = SampleSource("imerg_v07", 0.1)
    a = asyncio.run(src.fetch_day(date(2026, 1, 15))).values
    b = asyncio.run(src.fetch_day(date(2026, 1, 16))).values
    assert not (a == b).all()


def test_chirps_grid_shape():
    src = SampleSource("chirps_v3", 0.05)
    g = asyncio.run(src.fetch_day(date(2026, 3, 1)))
    assert g.values.shape == (346, 424)


def test_colormap_buckets():
    keys = [float(k) for k in COLORMAP]
    assert 0.0 in keys and 40.0 in keys
