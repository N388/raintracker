#!/usr/bin/env python3
"""تحويل مخرجات OSM الخام إلى طبقات GeoJSON نظيفة للاستيراد.

يخرج في مجلد واحد: tracks.geojson, fords.geojson, ridgelines.geojson,
springs.geojson, caves.geojson, helipads.geojson, passes.geojson,
dunes.geojson, bedrock.geojson
"""
import json
import os
import re
import sys

TAG_RE = re.compile(r'"([^"]+)"=>"([^"]*)"')
OUT = sys.argv[1] if len(sys.argv) > 1 else "data/processed/osm_new"
os.makedirs(OUT, exist_ok=True)


def tags_of(props):
    t = dict(TAG_RE.findall(props.get("other_tags", "")))
    if props.get("highway"):
        t["highway"] = props["highway"]
    return t


def dump(name, features):
    if not features:
        print(f"  {name}: 0 — تُركت");
        return
    gj = {"type": "FeatureCollection", "features": features}
    with open(os.path.join(OUT, f"{name}.geojson"), "w", encoding="utf-8") as f:
        json.dump(gj, f, ensure_ascii=False)
    print(f"  {name}: {len(features):,}")


GRADE_RANK = {"grade1": 1, "grade2": 2, "grade3": 3, "grade4": 4, "grade5": 5}


def quality_class(t):
    """تصنيف جودة الدرب من tracktype ثم smoothness ثم surface."""
    tt = t.get("tracktype")
    if tt in GRADE_RANK:
        return GRADE_RANK[tt]
    sm = t.get("smoothness")
    if sm in ("excellent", "good"):
        return 2
    if sm == "intermediate":
        return 3
    if sm == "bad":
        return 4
    if sm in ("very_bad", "horrible", "impassable"):
        return 5
    sf = t.get("surface")
    if sf in ("asphalt", "paved", "concrete"):
        return 1
    if sf in ("compacted", "gravel", "paving_stones"):
        return 2
    if sf in ("unpaved", "dirt", "soil", "ground"):
        return 3
    if sf == "sand":
        return 5
    return 0  # غير مصنّف


# ── الخطوط ─────────────────────────────────────────────
tracks, fords, ridges = [], [], []
d = json.load(open("data/newtracks.json", encoding="utf-8"))
for f in d.get("features", []):
    t = tags_of(f["properties"])
    g = f.get("geometry")
    if not g:
        continue
    if t.get("natural") == "ridge" or t.get("natural") == "arete":
        ridges.append({"type": "Feature", "geometry": g,
                       "properties": {"name": f["properties"].get("name") or t.get("name")}})
        continue
    if t.get("highway") not in ("track", "path"):
        if t.get("ford") == "yes":
            fords.append({"type": "Feature", "geometry": g,
                          "properties": {"name": f["properties"].get("name")}})
        continue
    q = quality_class(t)
    if t.get("ford") == "yes":
        fords.append({"type": "Feature", "geometry": g,
                      "properties": {"name": f["properties"].get("name")}})
        # مقطع العبور لا يدخل شبكة الدروب الرئيسة (يُظهر كطبقة مستقلة)
        continue
    tracks.append({"type": "Feature", "geometry": g, "properties": {
        "name": f["properties"].get("name"),
        "quality": q,
        "surface": t.get("surface", ""),
        "tracktype": t.get("tracktype", ""),
        "smoothness": t.get("smoothness", ""),
        "sandy": 1 if t.get("surface") == "sand" else 0,
        "abandoned": 1 if t.get("abandoned:aeroway") or t.get("abandoned:highway") else 0,
    }})

print("الخطوط:")
dump("tracks", tracks)
dump("fords", fords)
dump("ridgelines", ridges)

# ── النقاط ─────────────────────────────────────────────
springs, caves, helipads, passes = [], [], [], []
d = json.load(open("data/newpoints.json", encoding="utf-8"))
for f in d.get("features", []):
    t = tags_of(f["properties"])
    g = f.get("geometry")
    if not g:
        continue
    nm = f["properties"].get("name") or t.get("name")
    kind = None
    if t.get("natural") == "spring":
        kind = "عين"
    elif t.get("amenity") == "drinking_water":
        kind = "مياه شرب"
    if kind:
        springs.append({"type": "Feature", "geometry": g,
                        "properties": {"name": nm, "kind": kind}})
        continue
    if t.get("natural") == "cave_entrance":
        caves.append({"type": "Feature", "geometry": g, "properties": {"name": nm}})
        continue
    if t.get("aeroway") == "helipad" or t.get("abandoned:aeroway") == "helipad":
        helipads.append({"type": "Feature", "geometry": g, "properties": {"name": nm}})
        continue
    if t.get("mountain_pass") == "yes" or t.get("natural") == "saddle":
        passes.append({"type": "Feature", "geometry": g, "properties": {"name": nm}})
        continue
    if t.get("tourism") in ("wilderness_hut", "cabin"):
        caves.append({"type": "Feature", "geometry": g,
                      "properties": {"name": nm, "hut": 1}})  # مبيت ضمن كنوز

print("النقاط:")
dump("springs", springs)
dump("caves", caves)
dump("helipads", helipads)
dump("passes", passes)

# ── المضلعات ───────────────────────────────────────────
dunes, bedrock = [], []
d = json.load(open("data/newpolys.json", encoding="utf-8"))
for f in d.get("features", []):
    t = tags_of(f["properties"])
    g = f.get("geometry")
    if not g:
        continue
    nm = f["properties"].get("name") or t.get("name")
    if t.get("natural") == "dune":
        dunes.append({"type": "Feature", "geometry": g, "properties": {"name": nm}})
    elif t.get("natural") == "bare_rock":
        bedrock.append({"type": "Feature", "geometry": g, "properties": {"name": nm}})

print("المضلعات:")
dump("dunes", dunes)
dump("bedrock", bedrock)
print("تم في:", OUT)
