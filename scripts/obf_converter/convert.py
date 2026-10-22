#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
محوّل OsmAnd OBF → GeoJSON (إنتاجي، بدون اعتماديات خارجية).

يفك تنسيق OsmAnd Binary v2 بالكامل (متوافق مع OsmandOdb.proto ومنطق
BinaryMapIndexReader الرسمي) ويصدّر طبقات GIS نظيفة:

  - هندسة كاملة: خطوط، نقاط، مضلعات (خواتم خارجية/داخلية)، إحداثيات 31-زوم.
  - السمات: name (عربي من stringTable)، intermittent، religion، osm_id.
  - تصنيف مجاري المياه (فيضة/وادي/شعب/روضة/سبخة/أخرى) من الاسم العربي.

الاستخدام:  python3 convert.py <ملف.obf> <مجلد الإخراج>
"""
import json
import math
import os
import sys
import time
from collections import defaultdict

# ─────────────────────────── فك binary الأساسي ───────────────────────────

def rv(buf, pos):
    """varint غير موقّع."""
    r = 0
    s = 0
    while True:
        b = buf[pos]
        pos += 1
        r |= (b & 0x7F) << s
        if not (b & 0x80):
            break
        s += 7
    return r, pos


def rsint(buf, pos):
    """sint32/sint64 (zigzag)."""
    v, pos = rv(buf, pos)
    return (v >> 1) ^ -(v & 1), pos


def rlen(buf, pos):
    """OsmAnd readInt: big-endian 4 بايت (أو 8 إذا البايت الأول > 0x7f)."""
    f = buf[pos]
    pos += 1
    if f > 0x7f:
        l = f & 0x7F
        for _ in range(7):
            l = (l << 8) + buf[pos]
            pos += 1
        return l, pos
    l = f
    for _ in range(3):
        l = (l << 8) + buf[pos]
        pos += 1
    return l, pos


SHIFT = 5
MASK_TO_READ = ~((1 << SHIFT) - 1) & 0xFFFFFFFF

def x31_to_lon(x):
    return x / 2147483648.0 * 360.0 - 180.0


def y31_to_lat(y):
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2.0 * y / 2147483648.0))))

# ─────────────────────────── قراءة الرأس والفهارس ───────────────────────────

def read_header(data):
    """يرجع dict: version, date_created, indexes{field:(offset,length)}."""
    pos = 0
    size = len(data)
    indexes = {}
    version = date_created = None
    while pos < size:
        key, pos = rv(data, pos)
        f = key >> 3
        w = key & 7
        if w == 0:
            v, pos = rv(data, pos)
            if f == 1:
                version = v
            elif f == 18:
                date_created = v
        elif w == 6:
            ln, pos = rlen(data, pos)
            indexes[f] = (pos, ln)
            pos += ln
        elif w == 2:
            ln, pos = rv(data, pos)
            pos += ln
        else:
            break
    return {"version": version, "date_created": date_created, "indexes": indexes}

# ─────────────────────── قواعد الترميز (34 قاعدة في ملف الصحراء) ───────────────────────

def read_map_rules(data, start, end):
    """يرجع قائمة (tag, value) بترتيب الظهور؛ المعرف = الترتيب (يبدأ من 1)."""
    rules = []
    p = start
    while p < end:
        key, p = rv(data, p)
        f = key >> 3
        w = key & 7
        if w == 0:
            _, p = rv(data, p)
        elif w == 2:
            l2, p = rv(data, p)
            if f == 4:  # MapEncodingRule
                tag = val = None
                q = p
                while q < p + l2:
                    k2, q = rv(data, q)
                    f2 = k2 >> 3
                    w2 = k2 & 7
                    if w2 == 0:
                        _, q = rv(data, q)
                    elif w2 == 2:
                        l3, q = rv(data, q)
                        if f2 == 3:
                            tag = data[q:q + l3].decode("utf-8", "replace")
                        elif f2 == 5:
                            val = data[q:q + l3].decode("utf-8", "replace")
                        q += l3
                    else:
                        break
                rules.append((tag, val))
            p += l2
        elif w == 6:
            l2, p = rlen(data, p)
            p += l2
        elif w == 5:
            p += 4
        elif w == 1:
            p += 8
        else:
            break
    return rules

# ─────────────────────────── فك كائنات الخريطة ───────────────────────────

def decode_coord_ring(buf, start, end, ox, oy):
    """حلقة إحداثيات: x=(sint32<<5)+px متسلسلة؛ ترجع قائمة [x31,y31,...]."""
    out = []
    px, py = ox, oy
    p = start
    while p < end:
        dx, p = rsint(buf, p)
        dy, p = rsint(buf, p)
        px = ((dx << SHIFT) + px) & 0xFFFFFFFF
        py = ((dy << SHIFT) + py) & 0xFFFFFFFF
        out.append(px)
        out.append(py)
    return out


def decode_packed_varints(buf, start, end):
    vals = []
    p = start
    while p < end:
        v, p = rv(buf, p)
        vals.append(v)
    return vals


def decode_map_object(buf, start, end, origin_x, origin_y, base_id, rules):
    """يفك MapData واحداً ويرجع dict هندسة + سمات، أو None."""
    p = start
    coords = None      # خط/نقطة
    area = None        # خارجي مضلع
    inners = []
    types = []
    additional = []
    name_pairs = []    # (ruleId, stringIdx)
    obj_delta_id = 0
    while p < end:
        key, p = rv(buf, p)
        f = key >> 3
        w = key & 7
        if w == 0:
            v, p = rv(buf, p)
            if f == 12:
                obj_delta_id = (v >> 1) ^ -(v & 1)
        elif w == 2:
            l2, p = rv(buf, p)
            if f == 1:
                coords = decode_coord_ring(buf, p, p + l2, origin_x, origin_y)
            elif f == 2:
                area = decode_coord_ring(buf, p, p + l2, origin_x, origin_y)
            elif f == 4:
                inners.append(decode_coord_ring(buf, p, p + l2, origin_x, origin_y))
            elif f == 6:
                additional = decode_packed_varints(buf, p, p + l2)
            elif f == 7:
                types = decode_packed_varints(buf, p, p + l2)
            elif f == 10:
                q = p
                while q < p + l2:
                    rid, q = rv(buf, q)
                    idx, q = rv(buf, q)
                    name_pairs.append((rid, idx))
            p += l2
        elif w == 5:
            p += 4
        elif w == 1:
            p += 8
        else:
            return None
    if not types:
        return None

    props = {"osm_id": base_id + obj_delta_id}
    # الأنواع الإضافية → سمات (intermittent=yes، religion=muslim)
    for aid in additional:
        if 0 < aid <= len(rules):
            t, v = rules[aid - 1]
            if v is not None:
                props[t] = v
            else:
                props[t] = True
    props["_types"] = types
    props["_name_pairs"] = name_pairs

    if area is not None:
        geom = {"type": "Polygon",
                "coordinates": [ring_to_lonlat(area)] + [ring_to_lonlat(r) for r in inners]}
    elif coords is not None:
        n = len(coords) // 2
        if n == 1:
            geom = {"type": "Point",
                    "coordinates": [round(x31_to_lon(coords[0]), 6),
                                    round(y31_to_lat(coords[1]), 6)]}
        else:
            geom = {"type": "LineString",
                    "coordinates": ring_to_lonlat_pairs(coords)}
    else:
        return None
    return {"geometry": geom, "properties": props}


def ring_to_lonlat(flat):
    """[x31,y31,...] → [[lon,lat],...] مضمّنة (مضلعات: بدون تقريب لضبط الخواتم)."""
    return [[x31_to_lon(flat[i]), y31_to_lat(flat[i + 1])]
            for i in range(0, len(flat) - 1, 2)]


def ring_to_lonlat_pairs(flat):
    return [[round(x31_to_lon(flat[i]), 6), round(y31_to_lat(flat[i + 1]), 6)]
            for i in range(0, len(flat) - 1, 2)]


def scan_block_objects(buf, start, end, origin, rules, emit):
    """يفك كتلة MapDataBlock ويصدّر الكائنات عبر callback emit(obj, string_table)."""
    p = start
    base_id = 0
    objs = []
    strs = []
    while p < end:
        key, p = rv(buf, p)
        f = key >> 3
        w = key & 7
        if w == 0:
            v, p = rv(buf, p)
            if f == 10:
                base_id = v
        elif w == 2:
            l2, p = rv(buf, p)
            if f == 12:
                objs.append((p, p + l2))
            elif f == 15:  # StringTable
                q = p
                while q < p + l2:
                    k2, q = rv(buf, q)
                    f2 = k2 >> 3
                    w2 = k2 & 7
                    if w2 == 0:
                        _, q = rv(buf, q)
                    elif w2 == 2:
                        l3, q = rv(buf, q)
                        if f2 == 1:
                            strs.append(buf[q:q + l3].decode("utf-8", "replace"))
                        q += l3
                    else:
                        break
            p += l2
        elif w == 5:
            p += 4
        elif w == 1:
            p += 8
        else:
            return
    for (os_, oe) in objs:
        obj = decode_map_object(buf, os_, oe, origin[0], origin[1], base_id, rules)
        if obj is not None:
            # فك الأسماء من stringTable
            names = {}
            for rid, idx in obj["properties"].pop("_name_pairs"):
                if 0 < rid <= len(rules) and idx < len(strs):
                    tag, _ = rules[rid - 1]
                    names[tag] = strs[idx]
            if names:
                obj["properties"]["name"] = names.get("name")
                for k, v in names.items():
                    if k != "name":
                        obj["properties"][k] = v
            emit(obj)


def walk_map_box(buf, start, end, parent, rules, emit):
    p = start
    b = [parent[0], parent[1], parent[2], parent[3]]
    shifts = []
    subs = []
    while p < end:
        key, p = rv(buf, p)
        f = key >> 3
        w = key & 7
        if w == 0:
            v, p = rv(buf, p)
            if 1 <= f <= 4:
                d = (v >> 1) ^ -(v & 1)
                b[f - 1] = parent[f - 1] + d
        elif w == 5:
            if f == 5:
                s, p = rlen(buf, p)
                shifts.append(s)
            else:
                p += 4
        elif w == 6:
            ln, p = rlen(buf, p)
            if f == 5:
                shifts.append(ln)
            elif f == 7:
                subs.append((p, p + ln))
            p += ln
        elif w == 2:
            ln, p = rv(buf, p)
            p += ln
        elif w == 1:
            p += 8
        else:
            return
    # ترتيب الصندوق: b = [left, right, top, bottom] → أصل الإحداثيات = (left, top)
    origin = (b[0] & MASK_TO_READ, b[2] & MASK_TO_READ)
    for s in shifts:
        bp = start + s
        ln, p2 = rv(buf, bp)
        scan_block_objects(buf, p2, p2 + ln, origin, rules, emit)
    for s, e in subs:
        walk_map_box(buf, s, e, b, rules, emit)


# ─────────────────────────── تصنيف مجاري المياه ───────────────────────────

CLASS_RULES = [
    ("فيضة", ["فيض", "فياض", "فضة", "فضاء", "فضيه"]),
    ("سبخة", ["سبخ", "سباخ", "سبخه"]),
    ("روضة", ["روض", "رواض", "رياض", "ريضه", "رضه", "رضى"]),
    ("شعب",  ["شعب", "شعبان", "شعيب", "شعاب"]),
    ("وادي", ["وادي", "الوادي", "ودي", "اوديه", "أودية", "وديان"]),
]

def classify_waterway(name):
    if not name:
        return "أخرى"
    n = name.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    n = n.replace("ة", "ه")
    for cls, keys in CLASS_RULES:
        for k in keys:
            if k in n:
                return cls
    return "أخرى"

# ─────────────────────────── تعيين الطبقات ───────────────────────────

LAYER_BY_PRIMARY = {
    ("waterway", "river"): "waterways",
    ("place", "locality"): "settlements",
    ("place", "hamlet"): "settlements",
    ("place", "village"): "settlements",
    ("place", "city"): "settlements",
    ("natural", "scrub"): "scrub",
    ("natural", "wetland"): "wetlands",
    ("natural", "peak"): "peaks",
    ("natural", "water"): "water_bodies",
    ("natural", "crater"): "craters",
    ("natural", "slope"): "slopes",
    ("amenity", "fuel"): "fuel_stations",
    ("amenity", "college"): "education",
    ("amenity", "university"): "education",
    ("man_made", "water_well"): "wells",
    ("man_made", "antenna"): "antennas",
    ("man_made", "cairn"): "cairns",
    ("man_made", "works"): "utilities",
    ("tourism", "viewpoint"): "viewpoints",
    ("landuse", "farmland"): "farmland",
    ("landuse", "military"): "military_areas",
    ("landuse", "cemetery"): "cemeteries",
    ("landuse", "industrial"): "industrial_areas",
    ("boundary", "protected_area"): "protected_areas",
    ("waterway", "dam"): "dams",
    ("office", "telecommunication"): "telecom_offices",
    ("barrier", "fence"): "fences",
    ("leisure", "park"): "parks",
    ("historic", "archaeological_site"): "archaeology",
    ("historic", "ruins"): "archaeology",
    ("pipeline", "substation"): "utilities",
}

PLACE_KIND = {"city": "مدينة", "village": "قرية", "hamlet": "هجرة", "locality": "تجمع"}

# ─────────────────────────── الكاتب (streaming GeoJSON) ───────────────────────────

class LayerWriter:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.files = {}
        self.counts = defaultdict(int)

    def _fh(self, layer):
        if layer not in self.files:
            path = os.path.join(self.out_dir, f"{layer}.geojson")
            fh = open(path, "w", encoding="utf-8")
            fh.write('{"type":"FeatureCollection","features":[\n')
            self.files[layer] = {"fh": fh, "first": True, "path": path}
        return self.files[layer]

    def emit(self, layer, feature):
        st = self._fh(layer)
        if not st["first"]:
            st["fh"].write(",\n")
        st["first"] = False
        json.dump(feature, st["fh"], ensure_ascii=False, separators=(",", ":"))
        self.counts[layer] += 1

    def close(self):
        for st in self.files.values():
            st["fh"].write("\n]}\n")
            st["fh"].close()


def convert(obf_path, out_dir):
    t0 = time.time()
    data = open(obf_path, "rb").read()
    header = read_header(data)
    if 6 not in header["indexes"]:
        raise SystemExit("لا يوجد mapIndex في الملف")
    mstart, mlen = header["indexes"][6]
    rules = read_map_rules(data, mstart, mstart + mlen)
    print(f"قواعد الترميز: {len(rules)} | نسخة OBF: {header['version']}")

    os.makedirs(out_dir, exist_ok=True)
    writer = LayerWriter(out_dir)
    skipped = defaultdict(int)

    def emit(obj):
        props = obj["properties"]
        primary = rules[props["_types"][0] - 1] if props.get("_types") else (None, None)
        layer = LAYER_BY_PRIMARY.get(primary)
        if layer is None:
            skipped[f"{primary[0]}={primary[1]}"] += 1
            return
        props.pop("_types", None)
        tag, val = primary
        props["kind"] = PLACE_KIND.get(val, val) if tag == "place" else val
        if layer == "waterways":
            props["class"] = classify_waterway(props.get("name"))
        feat = {"type": "Feature", "geometry": obj["geometry"], "properties": props}
        writer.emit(layer, feat)

    # المشي على المستويات والصناديق
    p = mstart
    mend = mstart + mlen
    n_levels = 0
    while p < mend:
        key, p = rv(data, p)
        f = key >> 3
        w = key & 7
        if w == 0:
            _, p = rv(data, p)
        elif w == 2:
            l2, p = rv(data, p)
            p += l2
        elif w == 6:
            l2, p = rlen(data, p)
            if f == 5:
                lvl = {}
                q = p
                while q < p + l2:
                    k2, q = rv(data, q)
                    f2 = k2 >> 3
                    w2 = k2 & 7
                    if w2 == 0:
                        v2, q = rv(data, q)
                        if f2 in (1, 2, 3, 4, 5, 6):
                            lvl[f2] = v2
                    elif w2 == 6:
                        l3, q = rlen(data, q)
                        if f2 == 7:
                            bbox = [lvl.get(3, 0), lvl.get(4, 0), lvl.get(5, 0), lvl.get(6, 0)]
                            walk_map_box(data, q, q + l3, bbox, rules, emit)
                        q += l3
                    elif w2 == 2:
                        l3, q = rv(data, q)
                        q += l3
                    elif w2 == 5:
                        q += 4
                    elif w2 == 1:
                        q += 8
                n_levels += 1
            p += l2
        elif w == 5:
            p += 4
        elif w == 1:
            p += 8
        else:
            break

    writer.close()
    total = sum(writer.counts.values())
    print(f"\nالمستويات: {n_levels} | إجمالي المعالم: {total:,} | الزمن: {time.time()-t0:.1f}ث")
    print(f"المخرجات في: {out_dir}")
    for layer, cnt in sorted(writer.counts.items(), key=lambda x: -x[1]):
        print(f"  {cnt:>10,}  {layer}.geojson")
    if skipped:
        print("مُتجاهَل (بلا طبقة معروفة):", dict(skipped))
    return writer.counts


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])
