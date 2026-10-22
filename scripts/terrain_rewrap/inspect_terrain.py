#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""فكّ PNG مفهرس (colortype 3) بلا اعتماديات — لفحص بلاطات التضاريس."""
import sqlite3, zlib, struct

def decode_png_palette(data):
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    pos = 8
    w = h = None
    depth = ctype = None
    palette = None
    idat = b''
    while pos < len(data):
        ln, typ = struct.unpack('>I4s', data[pos:pos+8])
        chunk = data[pos+8:pos+8+ln]
        pos += 12 + ln
        if typ == b'IHDR':
            w, h, depth, ctype = struct.unpack('>IIBB', chunk[:10])
        elif typ == b'PLTE':
            palette = chunk
        elif typ == b'IDAT':
            idat += chunk
        elif typ == b'IEND':
            break
    raw = zlib.decompress(idat)
    if ctype != 3 or depth != 8:
        raise ValueError(f'ctype={ctype} depth={depth}')
    stride = w
    out = bytearray()
    prev = bytearray(stride)
    i = 0
    for y in range(h):
        f = raw[i]; i += 1
        line = bytearray(raw[i:i+stride]); i += stride
        if f == 1:   # Sub
            for x in range(1, stride):
                line[x] = (line[x] + line[x-1]) & 0xff
        elif f == 2: # Up
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xff
        elif f == 3: # Average
            for x in range(stride):
                a = line[x-1] if x > 0 else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 0xff
        elif f == 4: # Paeth
            for x in range(stride):
                a = line[x-1] if x > 0 else 0
                b = prev[x]
                c = prev[x-1] if x > 0 else 0
                p = a + b - c
                pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xff
        out += line
        prev = line
    return w, h, palette, bytes(out)

def edge_stats(px, w, h):
    """يعيد إحصاءات الحواف الأربع: (يسار, يمين, أعلى, أسفل) كمتوسط قيم الإضاءة."""
    def lum(i):
        r = palette[i*3]; g = palette[i*3+1]; b = palette[i*3+2]
        return 0.299*r + 0.587*g + 0.114*b
    left = [lum(px[y*w]) for y in range(h)]
    right = [lum(px[y*w + w-1]) for y in range(h)]
    top = [lum(px[x]) for x in range(w)]
    bot = [lum(px[(h-1)*w + x]) for x in range(w)]
    return (sum(left)/h, sum(right)/h, sum(top)/w, sum(bot)/w)

if __name__ == '__main__':
    con = sqlite3.connect('analysis/extracted/osf_unpacked/tiles/Terrain.sqlitedb')
    cur = con.cursor()
    cur.execute("SELECT x,y,z,image FROM tiles WHERE z=9 ORDER BY x,y LIMIT 40")
    rows = cur.fetchall()
    print(f'بلاطات z9 المحمّلة: {len(rows)}')
    stats = {}
    for (x, y, z, img) in rows[:6]:
        w, h, palette, px = decode_png_palette(img)
        L, R, T, B = edge_stats(px, w, h)
        print(f'tile(x={x},y={y}): lum يمين={R:.1f} يسار={L:.1f} | أعلى={T:.1f} أسفل={B:.1f}')
        stats[(x, y)] = (L, R, T, B)
    # اختبار الاستمرارية: بلاطات متجاورة أفقياً يجب أن يتطابق حرفاها المشتركان تقريباً
    pairs = 0
    for (x, y), (L, R, T, B) in stats.items():
        if (x+1, y) in stats:
            L2, R2, T2, B2 = stats[(x+1, y)]
            diff = abs(R - L2)
            print(f'زوج أفقي ({x},{y})→({x+1},{y}): فرق الحافة المشتركة = {diff:.1f} (صغير=متصل)')
            pairs += 1
    if not pairs:
        print('لا أزواج أفقية متجاورة في العينة — سأبحث في كامل z9')
        cur.execute("SELECT x,y FROM tiles WHERE z=9")
        allxy = set((r[0], r[1]) for r in cur.fetchall())
        for (x, y) in sorted(allxy):
            if (x+1, y) in allxy:
                print(f'زوج متجاور موجود: ({x},{y}) → ({x+1},{y})')
                break
        else:
            print('لا يوجد أي زوج أفقي متجاور في z9 كلها!')
