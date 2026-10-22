// يولّد lib/rahal-style.json: نمط OpenFreeMap Liberty مُعاد تلوينه بألوان Rahal
// + بلاطات الصحراء المحلية + فتحة طبقة المطر + مصدر النقاط.
// أعد التشغيل بعد أي تعديل: node scripts/build-rahal-style.mjs
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const here = path.dirname(fileURLToPath(import.meta.url));
const style = JSON.parse(fs.readFileSync(path.join(here, "../public/liberty.json"), "utf8"));

// ── ألوان نمط Rahal_professional ──
const RAHAL = {
  background: "#F2F9F9",
  water: "#40A9FF",
  motorway: "#809BC0", motorwayCasing: "rgba(93,46,140,0.57)",
  trunk: "#8DCF8D",    trunkCasing: "#74b374",
  primary: "#FB805F",  primaryCasing: "#d96a4d",
  secondary: "#FFBA46", secondaryCasing: "#e0a03e",
  tertiary: "#FFFF88", tertiaryCasing: "#d9d970",
  residential: "#B9B9B9",
  service: "#8A9AB0",
  track: "#DF0000",
  wood: "#87cc70", grass: "#94d77b", sand: "#f5efdc",
  wetland: "#DBCDC4", scrub: "#A9D49B", farmland: "#EDEFD2",
  building: "#d6d3d0", residentialArea: "#ebe7e4",
  wadi: "#7479ec", wadiLabel: "#5a5fd0", localityLabel: "#DF5356",
  poiLabel: "#0080FF", peak: "#5c3a1e", fuel: "#E01B00", antenna: "#555555",
};

// زوم الظهور المركزي (من موقع rahalMap المرجعي)
const ZOOM = {
  motorway: 4, trunkPrimary: 5, secondary: 7,
  protectedArea: 5, sand: 5, baseWetland: 9, baseVillage: 8,
  wetland: 7, scrub: 9, farmland: 11, wadiLine: 8,
  locality: 7, fayda: 9, wadiLabel: 11,
  peak: 9, peakLabel: 12,
  fuel: 10, fuelLabel: 13,
  well: 11, wellLabel: 13,
  antenna: 12, antennaLabel: 14,
};

// ── تلوين طبقات الأساس ──
const colorMap = {
  background: { "background-color": RAHAL.background },
  water: { "fill-color": RAHAL.water },
  waterway_river: { "line-color": RAHAL.water },
  waterway_other: { "line-color": RAHAL.water },
  landcover_wood: { "fill-color": RAHAL.wood, "fill-opacity": 0.55 },
  landcover_grass: { "fill-color": RAHAL.grass, "fill-opacity": 0.5 },
  landcover_sand: { "fill-color": RAHAL.sand },
  landuse_residential: { "fill-color": RAHAL.residentialArea },
  building: { "fill-color": RAHAL.building },
};
const roadColors = {
  road_motorway: RAHAL.motorway,
  road_motorway_link: RAHAL.motorway,
  road_trunk_primary: ["match", ["get", "class"], "trunk", RAHAL.trunk, RAHAL.primary],
  road_secondary_tertiary: ["match", ["get", "class"], "secondary", RAHAL.secondary, RAHAL.tertiary],
  road_minor: RAHAL.residential,
  road_service_track: ["match", ["get", "class"], "track", RAHAL.track, RAHAL.service],
  road_link: ["match", ["get", "class"], "trunk", RAHAL.trunk, RAHAL.primary],
  road_path_pedestrian: "rgba(0,0,0,0.25)",
};
const casingColors = {
  road_motorway_casing: RAHAL.motorwayCasing,
  road_link_casing: RAHAL.primaryCasing,
  road_trunk_primary_casing: ["match", ["get", "class"], "trunk", RAHAL.trunkCasing, RAHAL.primaryCasing],
  road_secondary_tertiary_casing: ["match", ["get", "class"], "secondary", RAHAL.secondaryCasing, RAHAL.tertiaryCasing],
  road_minor_casing: "#a5a5a5",
  road_service_track_casing: "#c8ccd2",
};
const baseZoom = {
  road_motorway: ZOOM.motorway, road_motorway_casing: ZOOM.motorway,
  road_trunk_primary: ZOOM.trunkPrimary, road_trunk_primary_casing: ZOOM.trunkPrimary,
  road_secondary_tertiary: ZOOM.secondary, road_secondary_tertiary_casing: ZOOM.secondary,
  park: ZOOM.protectedArea, park_outline: ZOOM.protectedArea,
  landcover_sand: ZOOM.sand, landcover_wetland: ZOOM.baseWetland,
  label_village: ZOOM.baseVillage,
};

for (const layer of style.layers) {
  if (baseZoom[layer.id] !== undefined) layer.minzoom = baseZoom[layer.id];
  if (colorMap[layer.id]) Object.assign(layer.paint || (layer.paint = {}), colorMap[layer.id]);
  if (roadColors[layer.id]) (layer.paint || (layer.paint = {}))["line-color"] = roadColors[layer.id];
  if (casingColors[layer.id]) (layer.paint || (layer.paint = {}))["line-color"] = casingColors[layer.id];
  // أسماء عربية عند توفرها (مع استبدال تسمية الكيان الصهيوني)
  if (layer.type === "symbol" && /^(label_|water_)/.test(layer.id)) {
    layer.layout = layer.layout || {};
    layer.layout["text-field"] = ["match", ["get", "name:ar"],
      "إسرائيل", "فلسطين",
      ["coalesce", ["get", "name:ar"], ["get", "name:latin"], ["get", "name"]]];
  }
}

// الأودية الموسمية في الأساس: متقطعة بلون Rahal
const waterwayIdxs = [];
style.layers.forEach((l, i) => { if (/^waterway_(river|other)$/.test(l.id)) waterwayIdxs.push(i); });
for (const i of waterwayIdxs.reverse()) {
  const wl = style.layers[i];
  const interm = JSON.parse(JSON.stringify(wl));
  interm.id = wl.id + "_intermittent";
  interm.filter = ["all", wl.filter || true, ["==", ["get", "intermittent"], 1]];
  interm.paint = Object.assign({}, wl.paint, {
    "line-color": RAHAL.wadi,
    "line-dasharray": [3.5, 2.5],
  });
  wl.filter = ["all", wl.filter || true, ["!=", ["get", "intermittent"], 1]];
  style.layers.splice(i + 1, 0, interm);
}

// المسارات البرية: حمراء متقطعة من z12
const svcIdx = style.layers.findIndex(l => l.id === "road_service_track");
if (svcIdx >= 0) {
  const svc = style.layers[svcIdx];
  const trackLayer = JSON.parse(JSON.stringify(svc));
  trackLayer.id = "road_track_rahal";
  trackLayer.filter = ["all", ["==", ["get", "class"], "track"],
    ["match", ["get", "brunnel"], ["bridge", "tunnel"], false, true]];
  trackLayer.paint = Object.assign({}, svc.paint, {
    "line-color": RAHAL.track,
    "line-dasharray": [2, 1.2],
    "line-width": ["interpolate", ["exponential", 1.2], ["zoom"], 12, 0, 13, 1.1, 16, 2.4, 20, 7],
  });
  style.layers.splice(svcIdx + 1, 0, trackLayer);
  svc.paint["line-width"] = ["interpolate", ["exponential", 1.2], ["zoom"], 12.5, 0, 13.5, 1.5, 16, 2.5, 20, 7.5];
}

// ── مصادرنا الإضافية ──
const GRID = { west: 34.4, south: 15.0, east: 55.6, north: 32.3 }; // مطابق لـ BBOX في rain.ts
const PIXEL_1X1 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGNgAAIAAAUAAXpeqz8AAAAASUVORK5CYII=";

style.sources.desert = { type: "vector", tiles: ["/desert-tiles/{z}/{x}/{y}.pbf"], maxzoom: 13, attribution: "خرائط الصحراء — OsmAnd OBF / OpenStreetMap" };
style.sources["desert-points"] = { type: "geojson", data: { type: "FeatureCollection", features: [] } };
style.sources.rain = {
  type: "image",
  url: PIXEL_1X1,
  coordinates: [
    [GRID.west, GRID.north], [GRID.east, GRID.north],
    [GRID.east, GRID.south], [GRID.west, GRID.south],
  ],
};

// ── طبقات الصحراء (من موقع rahalMap) تُدرج تحت الطرق، فوق المطر ──
const desertLayers = [
  { id: "desert-wetland", type: "fill", filter: ["==", ["get", "natural"], "wetland"], minzoom: ZOOM.wetland,
    paint: { "fill-color": RAHAL.wetland, "fill-opacity": 0.8 } },
  { id: "desert-scrub", type: "fill", filter: ["==", ["get", "natural"], "scrub"], minzoom: ZOOM.scrub,
    paint: { "fill-color": RAHAL.scrub, "fill-opacity": 0.5 } },
  { id: "desert-farmland", type: "fill", filter: ["==", ["get", "landuse"], "farmland"], minzoom: ZOOM.farmland,
    paint: { "fill-color": RAHAL.farmland, "fill-opacity": 0.75 } },
  { id: "desert-water-fill", type: "fill",
    filter: ["any", ["==", ["get", "natural"], "water"], ["==", ["get", "waterway"], "riverbank"]],
    paint: { "fill-color": RAHAL.water, "fill-opacity": 0.85 } },
  { id: "desert-water-line", type: "line",
    filter: ["all", ["match", ["get", "waterway"], ["river", "stream", "drain", "dam"], true, false],
      ["!=", ["get", "intermittent"], "yes"]],
    layout: { "line-cap": "round" },
    paint: { "line-color": RAHAL.water,
      "line-width": ["interpolate", ["linear"], ["zoom"], 8, 1, 13, 3, 16, 4] } },
  { id: "desert-wadi", type: "line",
    filter: ["any", ["==", ["get", "intermittent"], "yes"], ["==", ["get", "waterway"], "wadi"]],
    minzoom: ZOOM.wadiLine,
    layout: { "line-cap": "round" },
    paint: { "line-color": RAHAL.wadi, "line-dasharray": [3.5, 2.5],
      "line-width": ["interpolate", ["linear"], ["zoom"], 8, 0.5, 11, 1.0, 13, 1.5, 16, 2.2],
      "line-opacity": 0.9 } },
];

// ── طبقة المطر: صورة الشبكة تحت الطرق مباشرة ──
const rainLayer = { id: "rain", type: "raster", source: "rain",
  paint: { "raster-opacity": 0.6, "raster-fade-duration": 0 } };

// إدراج: المطر ثم طبقات الصحراء قبل أول طبقة طرق
const anchor = style.layers.findIndex(l => l.id === "road_area_pattern");
style.layers.splice(anchor, 0, rainLayer, ...desertLayers.map(l => ({ ...l, source: "desert", "source-layer": "features" })));

// ── طبقات النقاط في القمة (الأولوية بالترتيب كما في rahalMap) ──
const FONT_R = ["Noto Sans Regular"];
const FONT_B = ["Noto Sans Bold"];
const FONT_I = ["Noto Sans Italic"];
const HALO = { "text-halo-color": "#ffffff", "text-halo-width": 1.4 };
const F_ANT = ["match", ["get", "man_made"], ["antenna", "mast", "communications_tower"], true, false];
const F_WELL = ["==", ["get", "man_made"], "water_well"];
const F_FUEL = ["==", ["get", "amenity"], "fuel"];
const F_PEAK = ["==", ["get", "natural"], "peak"];
const sym = (id, filter, minzoom, layout, paint) => ({ id, type: "symbol", source: "desert-points", minzoom, filter, layout, paint });
const circ = (id, filter, minzoom, color, r) => ({ id, type: "circle", source: "desert-points", minzoom, filter,
  paint: { "circle-color": color,
    "circle-radius": ["interpolate", ["linear"], ["zoom"], minzoom, r * 0.6, 16, r],
    "circle-stroke-color": "#fff", "circle-stroke-width": 1 } });
const labelLayout = (size, offset, font, extra) => Object.assign({
  "text-field": ["get", "name"], "text-font": font || FONT_R,
  "text-size": size, "text-offset": offset ? [0, offset] : [0, 0],
}, extra || {});

style.layers.push(
  circ("desert-antenna", F_ANT, ZOOM.antenna, RAHAL.antenna, 3.5),
  sym("desert-antenna-label", F_ANT, ZOOM.antennaLabel, labelLayout(10.5, 0.9), { "text-color": "#666666", ...HALO }),
  circ("desert-well", F_WELL, ZOOM.well, RAHAL.poiLabel, 3.5),
  sym("desert-well-label", F_WELL, ZOOM.wellLabel, labelLayout(11, 0.9), { "text-color": RAHAL.poiLabel, ...HALO }),
  circ("desert-fuel", F_FUEL, ZOOM.fuel, RAHAL.fuel, 4.5),
  sym("desert-fuel-label", F_FUEL, ZOOM.fuelLabel, labelLayout(11, 1.0), { "text-color": RAHAL.poiLabel, ...HALO }),
  sym("desert-wadi-label", ["has", "waterway"], ZOOM.wadiLabel,
    labelLayout(["interpolate", ["linear"], ["zoom"], ZOOM.wadiLabel, 10.5, 15, 13], 0, FONT_I),
    { "text-color": RAHAL.wadiLabel, ...HALO }),
  circ("desert-peak", F_PEAK, ZOOM.peak, RAHAL.peak, 4),
  sym("desert-peak-label", F_PEAK, ZOOM.peakLabel, labelLayout(11.5, 0.9), { "text-color": "#444444", ...HALO }),
  sym("desert-naturallabel", ["has", "natural_label"], ZOOM.fayda,
    labelLayout(["interpolate", ["linear"], ["zoom"], ZOOM.fayda, 10.5, 15, 13], 0, FONT_I),
    { "text-color": "#8a7a6c", ...HALO }),
  sym("desert-locality", ["==", ["get", "place"], "locality"], ZOOM.locality,
    labelLayout(["interpolate", ["linear"], ["zoom"], ZOOM.locality, 10, 12, 13, 16, 15]),
    { "text-color": RAHAL.localityLabel, ...HALO }),
);

fs.mkdirSync(path.join(here, "../lib"), { recursive: true });
fs.writeFileSync(path.join(here, "../lib/rahal-style.json"), JSON.stringify(style));
console.log("rahal-style.json:", style.layers.length, "layers,",
  Object.keys(style.sources).length, "sources");
