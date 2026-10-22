"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import MapboxDraw from "@mapbox/mapbox-gl-draw";
import * as turf from "@turf/turf";
import "maplibre-gl/dist/maplibre-gl.css";
import "@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css";
import { wasmWindow, fetchPointWindows, fetchGrid, gridToCanvas, gridToCanvasHighlight, vmaxOf, fetchForecast7d, fetchRadarLatest, GRID } from "./rain";
import rahalStyle from "../lib/rahal-style.json";

maplibregl.setRTLTextPlugin(`${process.env.NEXT_PUBLIC_BASEPATH ?? ""}/vendor/rtl-text.js`, true); // تشكيل العربية واتجاهها الصحيح

// يشتق تلقائياً من اسم المضيف: يعمل محلياً وعبر الشبكة المنزلية دون إعداد
const HOST = typeof window !== "undefined" ? window.location.hostname : "localhost";
const API = process.env.NEXT_PUBLIC_API_URL ?? `http://${HOST}:8080/api/v1`;
// مسار القاعدة عند النشر تحت username.github.io/<repo> — فارغ محلياً
const BASE = process.env.NEXT_PUBLIC_BASEPATH ?? "";
// النسخة الساكنة العامة (GitHub Pages): شبكات مسبقة الحساب، بلا خادم
const STATIC = process.env.NEXT_PUBLIC_STATIC_GRIDS === "1";

// إن عُيّن NEXT_PUBLIC_RAIN_GRID_URL → الشبكة من Worker، وإلا من /rain/grid محلياً.
// النوافذ دائماً من Open-Meteo مباشرة (بلا وسيط تخزين).
const GRID_URL = process.env.NEXT_PUBLIC_RAIN_GRID_URL ?? `${API}/rain/grid`;
const GRID_DIRECT = true;

const QUICK: { key: string; label: string; days: number }[] = [
  { key: "3days", label: "3 أيام", days: 3 },
  { key: "7days", label: "7 أيام", days: 7 },
  { key: "10days", label: "10 أيام", days: 10 },
  { key: "20days", label: "20 يوم", days: 20 },
  { key: "30days", label: "30 يوم", days: 30 },
  { key: "40days", label: "40 يوم", days: 40 },
  { key: "60days", label: "60 يوم", days: 60 },
  { key: "90days", label: "90 يوم", days: 90 },
  { key: "120days", label: "120 يوم", days: 120 },
  { key: "180days", label: "180 يوم", days: 180 },
];

type WasmInfo = { start: string; end: string; year: number; ongoing: boolean };
type Presets = { wasm: WasmInfo };
type PointData = {
  sums_mm: Record<string, number | null>;
  wasm: { sum_mm: number | null; year: number; ongoing: boolean };
  last_rain_day: string | null;
  disclaimer: string;
  cell?: { approx_km: number };
};
type SearchResult = { name: string; kind: string; lon: number; lat: number };

// مجموعات طبقات الخريطة الجديدة (خرائط الصحراء / Rahal) — كل مفتاح يتحكم بعدة طبقات
const LAYER_GROUPS: { group: string; items: { key: string; label: string; ids: string[] }[] }[] = [
  { group: "المياه", items: [
    { key: "wadis", label: "الأودية والمجاري", ids: ["desert-wadi", "desert-wadi-label"] },
    { key: "water", label: "المياه السطحية", ids: ["desert-water-fill", "desert-water-line"] },
    { key: "wetland", label: "السباخ والأراضي الرطبة", ids: ["desert-wetland"] },
    { key: "fayda", label: "الفياض (الأسماء)", ids: ["desert-naturallabel"] },
  ]},
  { group: "التضاريس والنبات", items: [
    { key: "scrub", label: "الشجيرات", ids: ["desert-scrub"] },
    { key: "farmland", label: "الأراضي الزراعية", ids: ["desert-farmland"] },
  ]},
  { group: "المعالم", items: [
    { key: "peaks", label: "القمم الجبلية", ids: ["desert-peak", "desert-peak-label"] },
    { key: "wells", label: "آبار المياه", ids: ["desert-well", "desert-well-label"] },
    { key: "fuel", label: "محطات الوقود", ids: ["desert-fuel", "desert-fuel-label"] },
    { key: "antennas", label: "أبراج الاتصالات", ids: ["desert-antenna", "desert-antenna-label"] },
  ]},
  { group: "الأماكن", items: [
    { key: "places", label: "المحليات الصحراوية", ids: ["desert-locality"] },
  ]},
];
const ALL_LAYER_KEYS = LAYER_GROUPS.flatMap(g => g.items.map(i => i.key));

export default function MapClient() {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const rainCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const searchIndexRef = useRef<SearchResult[]>([]);
  const drawRef = useRef<MapboxDraw | null>(null);
  const [presets, setPresets] = useState<Presets | null>(null);
  const quickPeriod = (days: number) => {
    const to = new Date().toISOString().slice(0, 10);
    const from = new Date(Date.now() - days * 864e5).toISOString().slice(0, 10);
    return { key: `${days}days`, from, to };
  };
  const loadPeriod = (): { key: string; from: string; to: string } => {
    try {
      const raw = localStorage.getItem("rain_period");
      if (!raw) {                       // أول زيارة: الوسم افتراضياً
        const w0 = wasmWindow(new Date());
        return { key: "wasm", from: w0.start, to: w0.end };
      }
      const p = JSON.parse(raw);
      const m = /^(\d+)days$/.exec(p.key ?? "");
      if (m) return quickPeriod(+m[1]);            // فترات سريعة: تُجدَّد للآن
      if (p.key === "wasm") {                       // الوسم: نافذته الحالية
        const w = wasmWindow(new Date());
        return { key: "wasm", from: w.start, to: w.end };
      }
      if (p.key === "custom" && p.from && p.to) return { key: "custom", from: p.from, to: p.to };
    } catch { /* تجاهل */ }
    return { key: "", from: "", to: "" };
  };
  const [period, setPeriodState] = useState<{ key: string; from: string; to: string }>(loadPeriod);
  const setPeriod = useCallback((p: { key: string; from: string; to: string }) => {
    try { localStorage.setItem("rain_period", JSON.stringify(p)); } catch { /* تجاهل */ }
    setPeriodState(p);
  }, []);
  const [source, setSource] = useState<"imerg_v07" | "chirps_v3">("imerg_v07");
  const [visible, setVisible] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(ALL_LAYER_KEYS.map(k => [k, true])));
  const [point, setPoint] = useState<{ lat: number; lon: number; data: PointData | null; elev: number | null } | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [dark, setDark] = useState(false);
  const [measure, setMeasure] = useState<"off" | "line" | "area">("off");
  const [measureResult, setMeasureResult] = useState("");
  const [customOpen, setCustomOpen] = useState(false);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [toast, setToast] = useState("");
  const [vmax, setVmax] = useState(80);
  const [layersOpen, setLayersOpen] = useState(false);   // لوحة الطبقات مغلقة افتراضياً
  const [seasonOpen, setSeasonOpen] = useState(false);
  const [season, setSeason] = useState<any>(null);
  const [topOpen, setTopOpen] = useState(false);
  const [topList, setTopList] = useState<any[]>([]);
  const [radarOn, setRadarOn] = useState(false);
  const [rainMode, setRainMode] = useState<"gradient" | "highlight">("gradient");
  const [rainThr, setRainThr] = useState(10);
  const [rawdatOpen, setRawdatOpen] = useState(false);
  const [rawdatList, setRawdatList] = useState<any[]>([]);
  const [ndviOn, setNdviOn] = useState(false);
  const [ndviMeta, setNdviMeta] = useState<any>(null);
  const [notesOpen, setNotesOpen] = useState(false);
  const [notes, setNotes] = useState<any[]>(() => {
    try { return JSON.parse(localStorage.getItem("rain_notes") ?? "[]"); } catch { return []; }
  });
  const [noteText, setNoteText] = useState("");
  const [pendingNote, setPendingNote] = useState(false);
  const [picker, setPicker] = useState(false);           // مؤشر الفأرة
  const pickerRef = useRef<HTMLDivElement | null>(null);
  const pickerBadgeRef = useRef<HTMLDivElement | null>(null);
  const rainDataRef = useRef<Float32Array | null>(null);

  const say = useCallback((msg: string) => { setToast(msg); setTimeout(() => setToast(""), 2500); }, []);

  useEffect(() => {
    if (!container.current || mapRef.current) return;
    // MapLibre يتطلب عناوين مطلقة لقوالب البلاطات — نبنيها من أصل الصفحة
    const style = JSON.parse(JSON.stringify(rahalStyle)) as typeof rahalStyle & {
      sources: Record<string, any> };
    if (style.sources.desert?.tiles)
      style.sources.desert.tiles = [`${window.location.origin}${BASE}/desert-tiles/{z}/{x}/{y}.pbf`];
    const map = new maplibregl.Map({
      container: container.current,
      style: style as unknown as maplibregl.StyleSpecification,
      center: [45.0, 24.0],
      zoom: 6,
      hash: true,
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "bottom-left");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    map.on("error", (e: any) => console.log("[map-error]", JSON.stringify(e.error ?? e).slice(0, 250)));
    mapRef.current = map;
    (window as unknown as { __map?: maplibregl.Map }).__map = map; // لتشخيصات المتصفح

    const draw = new MapboxDraw({
      displayControlsDefault: false,
      controls: {},
      styles: [
        { id: "gl-draw-line", type: "line", filter: ["all", ["==", "$type", "LineString"], ["!=", "mode", "static"]],
          paint: { "line-color": "#e11d48", "line-width": 2, "line-dasharray": [0.2, 2] } },
        { id: "gl-draw-polygon-fill", type: "fill", filter: ["all", ["==", "$type", "Polygon"], ["!=", "mode", "static"]],
          paint: { "fill-color": "#e11d48", "fill-opacity": 0.12 } },
        { id: "gl-draw-polygon-stroke", type: "line", filter: ["all", ["==", "$type", "Polygon"], ["!=", "mode", "static"]],
          paint: { "line-color": "#e11d48", "line-width": 2 } },
        { id: "gl-draw-vertices", type: "circle", filter: ["all", ["==", "meta", "vertex"], ["==", "$type", "Point"]],
          paint: { "circle-radius": 4, "circle-color": "#e11d48", "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } },
      ],
    });
    drawRef.current = draw;
    map.addControl(draw as unknown as maplibregl.IControl, "top-left");

    map.on("draw.create", (e: { features: GeoJSON.Feature[] }) => {
      const f = e.features[0];
      if (!f) return;
      if (f.geometry.type === "LineString") {
        const km = turf.length(f as never, { units: "kilometers" });
        setMeasureResult(`${km.toFixed(1)} كم`);
      } else if (f.geometry.type === "Polygon") {
        const km2 = turf.area(f as never) / 1e6;
        setMeasureResult(`${km2.toFixed(1)} كم²`);
      }
      draw.deleteAll();
    });

    map.on("load", () => {
      // نقاط خرائط الصحراء (50 ألف معلم) إلى مصدر النمط + فهرس البحث الداخلي
      fetch(`${BASE}/desert-points.ndjson`).then(r => r.text()).then(txt => {
        const feats = txt.split("\n").filter(l => l.trim()).map(l => JSON.parse(l));
        const src = map.getSource("desert-points") as maplibregl.GeoJSONSource | undefined;
        src?.setData({ type: "FeatureCollection", features: feats });
        searchIndexRef.current = feats.filter((f: any) => f.properties?.name).map((f: any) => {
          const p = f.properties;
          const kind = p.place === "locality" ? "محلية"
            : p.place === "hamlet" ? "هجرة"
            : p.place === "village" ? "قرية"
            : p.place === "town" ? "بلدة"
            : p.place === "city" ? "مدينة"
            : p.waterway ? "وادٍ"
            : p.natural_label ? "فيضة/سبخة"
            : p.natural === "peak" ? "قمة"
            : p.amenity === "fuel" ? "وقود"
            : p.man_made === "water_well" ? "بئر"
            : p.man_made ? "برج" : "معلم";
          return { name: p.name, kind, lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1] };
        });
      }).catch(() => {});
    });

    map.on("click", async (e) => {
      if (measure !== "off") return; // أثناء القياس لا نفتح البطاقة
      if (pendingNoteRef.current) {  // وضع الملاحظة: احفظ هنا واخرج
        pendingNoteRef.current = false;
        setPendingNote(false);
        const data = rainDataRef.current;
        let mm: number | null = null;
        if (data) {
          const ix = Math.floor((e.lngLat.lng - GRID.west) / GRID.res);
          const iyN = Math.floor((GRID.north - e.lngLat.lat) / GRID.res);
          if (ix >= 0 && ix < GRID.nx && iyN >= 0 && iyN < GRID.ny)
            mm = Math.round(data[iyN * GRID.nx + ix] * 10) / 10;
        }
        addNote({ type: "note", text: noteTextRef.current || "ملاحظة",
                  lat: e.lngLat.lat, lon: e.lngLat.lng, mm,
                  period: periodKeyRef.current });
        setNoteText("");
        say("حُفظت الملاحظة 📝");
        return;
      }
      const { lng, lat } = e.lngLat;
      setPoint({ lat, lon: lng, data: null, elev: null });
      if (GRID_DIRECT) {
        // نمط Serverless: طلب واحد لـ Open-Meteo يغطي كل النوافذ + الارتفاع
        try {
          const d = await fetchPointWindows(lat, lng, wasmWindow(new Date()));
          setPoint({ lat, lon: lng, data: d, elev: d.elevation_m });
        } catch { /* صامت */ }
        return;
      }
      try {
        const r = await fetch(`${API}/rain/point?lat=${lat.toFixed(4)}&lon=${lng.toFixed(4)}&source=imerg_v07`);
        if (r.ok) setPoint({ lat, lon: lng, data: (await r.json()).sources.imerg_v07, elev: null });
      } catch { /* صامت */ }
      try {
        const er = await fetch(`${API}/elevation?lat=${lat.toFixed(4)}&lon=${lng.toFixed(4)}`);
        if (er.ok) {
          const ed = await er.json();
          setPoint(p => p && p.lat === lat ? { ...p, elev: ed.elevation_m } : p);
        }
      } catch { /* الارتفاع اختياري */ }
    });

    return () => { map.remove(); mapRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [measure]);

  const pendingNoteRef = useRef(false);
  useEffect(() => { pendingNoteRef.current = pendingNote; }, [pendingNote]);
  const noteTextRef = useRef("");
  useEffect(() => { noteTextRef.current = noteText; }, [noteText]);
  const periodKeyRef = useRef("");
  useEffect(() => { periodKeyRef.current = period.key; }, [period]);

  useEffect(() => {
    fetch(`${API}/rain/presets`).then(r => (r.ok ? r.json() : null)).then(setPresets).catch(() => {});
  }, []);

  // ── دفتر ملاحظات المختبرين ──
  const persistNotes = useCallback((ns: any[]) => {
    setNotes(ns);
    try { localStorage.setItem("rain_notes", JSON.stringify(ns)); } catch { /* تجاهل */ }
  }, []);

  const addNote = useCallback((n: Omit<any, "id" | "ts">) => {
    persistNotes([{ ...n, id: Date.now(), ts: new Date().toISOString() }, ...notesRef.current]);
  }, [persistNotes]);
  const notesRef = useRef(notes);
  useEffect(() => { notesRef.current = notes; }, [notes]);

  const removeNote = useCallback((id: number) => {
    persistNotes(notesRef.current.filter((n: any) => n.id !== id));
  }, [persistNotes]);

  // علامات الملاحظات على الخريطة
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const geo: any = { type: "FeatureCollection",
      features: notes.map(n => ({ type: "Feature",
        geometry: { type: "Point", coordinates: [n.lon, n.lat] },
        properties: { kind: n.type } })) };
    const src = map.getSource("notes") as maplibregl.GeoJSONSource | undefined;
    if (src) src.setData(geo);
    else if (notes.length) {
      map.addSource("notes", { type: "geojson", data: geo });
      map.addLayer({ id: "notes", type: "circle", source: "notes",
        filter: ["==", ["get", "kind"], "note"],
        paint: { "circle-color": "#eab308", "circle-radius": 6, "circle-opacity": 0.9,
                 "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
      map.addLayer({ id: "flags", type: "circle", source: "notes",
        filter: ["==", ["get", "kind"], "flag"],
        paint: { "circle-color": "#dc2626", "circle-radius": 6, "circle-opacity": 0.9,
                 "circle-stroke-color": "#fff", "circle-stroke-width": 2 } });
    }
  }, [notes]);

  // تصدير الملاحظات (نسخ + تنزيل)
  const exportNotes = useCallback(async () => {
    const data = JSON.stringify(notesRef.current, null, 1);
    try { await navigator.clipboard.writeText(data); say(`نُسخت ${notesRef.current.length} ملاحظة`); }
    catch { say("تعذر النسخ"); }
    const blob = new Blob([data], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `rain-notes-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
  }, [say]);

  // طبقة NDVI (Sentinel-2)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!ndviOn) {
      if (map.getLayer("ndvi")) map.removeLayer("ndvi");
      if (map.getSource("ndvi")) map.removeSource("ndvi");
      return;
    }
    fetch(`${API}/../..`).catch(() => {});
    fetch("http://" + window.location.hostname + ":8000/cog/info?url=file:///data/ndvi_meta.json").catch(() => {});
    fetch("http://" + window.location.hostname + ":8000/cog/info?url=file:///data/ndvi_cog.tif")
      .then(r => (r.ok ? r.json() : null)).then(j => {
        if (j) setNdviMeta({ date: j?.meta?.datetime ?? "" });
      }).catch(() => {});
    const cmap = encodeURIComponent(JSON.stringify({
      "0": "#8c510a", "40": "#d8b365", "70": "#f6e8c3", "100": "#a6d96a",
      "140": "#1a9850", "170": "#006837", "200": "#004529", "255": "#00000000" }));
    const url = `http://${window.location.hostname}:8000/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png` +
      `?url=file:///data/ndvi_cog.tif&rescale=100,170&colormap=${cmap}`;
    if (map.getSource("ndvi")) {
      (map.getSource("ndvi") as maplibregl.RasterTileSource).setTiles([url]);
    } else {
      map.addSource("ndvi", { type: "raster", tiles: [url], tileSize: 256, maxzoom: 15 });
      map.addLayer({ id: "ndvi", type: "raster", source: "ndvi",
        paint: { "raster-opacity": 0.75, "raster-fade-duration": 0 } });
    }
  }, [ndviOn]);

  // ── لوحة الوسم ──
  useEffect(() => {
    if (!seasonOpen) return;
    fetch(`${API}/rain/season?years=5`).then(r => (r.ok ? r.json() : null)).then(setSeason).catch(() => {});
  }, [seasonOpen]);

  // أعلى مناطق الفترة
  useEffect(() => {
    if (!topOpen || !period.from) return;
    fetch(`${API}/rain/grid/top?from=${period.from}&to=${period.to}`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => d && setTopList(d.top)).catch(() => {});
  }, [topOpen, period]);

  // رادار RainViewer
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!radarOn) {
      if (map.getLayer("radar")) map.removeLayer("radar");
      if (map.getSource("radar")) map.removeSource("radar");
      return;
    }
    fetchRadarLatest().then(fr => {
      if (!fr || !mapRef.current) return;
      const map2 = mapRef.current;
      if (map2.getSource("radar")) {
        (map2.getSource("radar") as maplibregl.RasterTileSource).setTiles([fr.urlTemplate]);
      } else {
        map2.addSource("radar", { type: "raster", tiles: [fr.urlTemplate], tileSize: 512, maxzoom: 12 });
        map2.addLayer({ id: "radar", type: "raster", source: "radar",
          paint: { "raster-opacity": 0.55, "raster-fade-duration": 0 } });
      }
    }).catch(() => {});
  }, [radarOn]);

  useEffect(() => {
    document.body.style.background = dark ? "#1c1917" : "#f5f1e8";
  }, [dark]);

  // رفع رسم المطر إلى مصدر الصور داخل النمط (فوق الأرضية وتحت الطرق)
  const pushRainImage = useCallback(() => {
    const map = mapRef.current;
    const rc = rainCanvasRef.current;
    if (!map || !rc) return;
    const src = map.getSource("rain") as maplibregl.ImageSource | undefined;
    src?.updateImage({ url: rc.toDataURL("image/png") });
  }, []);

  // روضات الفترة
  useEffect(() => {
    if (!rawdatOpen || !period.from) return;
    fetch(`${API}/rain/rawdat?from=${period.from}&to=${period.to}&min_mm=${rainThr}`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => d && setRawdatList(d.rawdat)).catch(() => {});
  }, [rawdatOpen, period, rainThr]);

  // إعادة رسم الطبقة عند تغيير النمط/العتبة دون إعادة جلب
  useEffect(() => {
    const data = rainDataRef.current;
    if (!data) return;
    rainCanvasRef.current = rainMode === "highlight"
      ? gridToCanvasHighlight(data, rainThr)
      : gridToCanvas(data, vmaxOf(data));
    pushRainImage();
  }, [rainMode, rainThr, pushRainImage]);

  // وضع المطر اليومي: تاريخ محدد + سهما تنقل بين الأيام
  const yesterday = () => new Date(Date.now() - 864e5).toISOString().slice(0, 10);
  const [daily, setDaily] = useState<{ on: boolean; date: string }>({ on: false, date: yesterday() });
  // أول يوم ثبت عدم نشر بياناته (CHIRPS يتأخر ~4 أيام) — يوقف سهم «التالي»
  const [pubBound, setPubBound] = useState<string | null>(null);
  const shiftDay = useCallback((delta: number) => {
    setDaily(d => {
      if (!d.on) return d;
      const t = new Date(d.date + "T00:00:00Z");
      t.setUTCDate(t.getUTCDate() + delta);
      const iso = t.toISOString().slice(0, 10);
      if (iso > yesterday() || iso < "1981-01-01") return d;   // حدود CHIRPS
      return { ...d, date: iso };
    });
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const from = daily.on ? daily.date : period.from;
    const to = daily.on ? daily.date : period.to;
    if (!map || !from || !to) return;
    let cancelled = false;
    say(daily.on ? `جارٍ تحميل مطر يوم ${from}…` : "جارٍ تجميع بيانات المطر…");
    fetchGrid(GRID_URL, from, to, daily.on ? `day:${from}` : period.key).then(res => {
      if (cancelled) return;
      const data = res.arr;
      rainDataRef.current = data;
      setVmax(vmaxOf(data));
      if (daily.on) {
        if (res.partial) setPubBound(b => (b === null || from < b) ? from : b);
        else if (pubBound === from) setPubBound(null);   // نُشرت البيانات لاحقاً
      }
      say(res.partial
        ? daily.on ? `بيانات يوم ${from} لم تُنشر بعد (CHIRPS يتأخر ~4 أيام)`
          : `تم — بيانات جزئية (تعذر جلب ${res.missing} جزء)`
        : daily.on ? (res.gfs ? `مطر يوم ${from} (تقدير GFS)` : `مطر يوم ${from}`)
          : res.gfs ? `تم تحديث المطر (${res.gfs} أيام تقدير GFS)` : "تم تحديث طبقة المطر");
      rainCanvasRef.current = rainMode === "highlight"
        ? gridToCanvasHighlight(data, rainThr)
        : gridToCanvas(data, vmaxOf(data));
      pushRainImage();
    }).catch((e) => {
      if (cancelled) return;
      if (STATIC && String(e?.message).startsWith("static-"))
        say("هذه الفترة غير متاحة في النسخة العامة (جرّب التطبيق المحلي)");
    });
    return () => { cancelled = true; };
  }, [period, daily, pushRainImage]);

  useEffect(() => {
    const d = drawRef.current;
    if (!d) return;
    d.deleteAll();
    setMeasureResult("");
    if (measure === "line") d.changeMode("draw_line_string");
    else if (measure === "area") d.changeMode("draw_polygon");
    else d.changeMode("simple_select");
  }, [measure]);

  // أداة المؤشر: يبدأ من المنتصف ويتبع الفأرة، ويقرأ قيمة المطر من الشبكة مباشرة
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const mk = pickerRef.current;
    const badge = pickerBadgeRef.current;
    if (!picker) {
      mk?.remove();
      badge?.remove();
      pickerRef.current = null;
      pickerBadgeRef.current = null;
      return;
    }
    if (!mk && container.current) {
      const el = document.createElement("div");
      el.innerHTML = `<div style="width:22px;height:22px;border:2.5px solid #0ea5e9;border-radius:50%;background:rgba(14,165,233,.15);box-shadow:0 0 0 2px #fff, 0 2px 8px rgba(0,0,0,.3)"></div>`;
      el.style.cssText = "position:absolute;transform:translate(-50%,-50%);pointer-events:none;z-index:15;";
      const bg = document.createElement("div");
      bg.style.cssText = "position:absolute;transform:translate(14px,-50%);background:#0c4a6e;color:#fff;font-size:12px;font-weight:700;padding:3px 8px;border-radius:8px;pointer-events:none;z-index:15;white-space:nowrap;font-family:Tahoma;";
      container.current.appendChild(el);
      container.current.appendChild(bg);
      pickerRef.current = el;
      pickerBadgeRef.current = bg;
    }
    let fcTimer: ReturnType<typeof setTimeout> | null = null;
    let lastFc: [number, number] | null = null;
    const place = (lng: number, lat: number, px: number, py: number) => {
      const e = pickerRef.current, b = pickerBadgeRef.current;
      if (!e || !b) return;
      e.style.left = `${px}px`; e.style.top = `${py}px`;
      b.style.left = `${px}px`; b.style.top = `${py}px`;
      const data = rainDataRef.current;
      let cur = "—";
      if (data) {
        const ix = Math.floor((lng - GRID.west) / GRID.res);
        const iyN = Math.floor((GRID.north - lat) / GRID.res);
        if (ix >= 0 && ix < GRID.nx && iyN >= 0 && iyN < GRID.ny) {
          const v = data[iyN * GRID.nx + ix];
          cur = v > 0.05 ? `${v.toFixed(1)} مم` : "0 مم";
        }
      }
      // توقعات 7 أيام (مهذبة بالوقت والمسافة)
      if (!lastFc || Math.abs(lng - lastFc[0]) + Math.abs(lat - lastFc[1]) > 0.1) {
        if (fcTimer) clearTimeout(fcTimer);
        fcTimer = setTimeout(async () => {
          lastFc = [lng, lat];
          const fc = await fetchForecast7d(lat, lng);
          const bb = pickerBadgeRef.current;
          if (bb) bb.textContent = fc
            ? `${cur} · قادم: ${fc.total_mm} مم${fc.rainy_days ? ` (${fc.rainy_days} أيام)` : ""}`
            : cur;
        }, 600);
      }
      b.textContent = cur;
    };
    const onMove = (e: maplibregl.MapMouseEvent) => { lastMouseAt = Date.now(); place(e.lngLat.lng, e.lngLat.lat, e.point.x, e.point.y); };
    // على الشاشات اللمسية لا تُطلق أحداث الفأرة أثناء السحب — نتبع مركز الشاشة مع كل حركة خريطة
    const onMapMove = () => {
      if (Date.now() - lastMouseAt < 1500) return;   // الفأرة نشطة حديثاً — الأولوية لها
      const c = map.getCenter();
      const p = map.project([c.lng, c.lat]);
      place(c.lng, c.lat, p.x, p.y);
    };
    let lastMouseAt = 0;
    const c = map.getCenter();
    const p0 = map.project([c.lng, c.lat]);
    place(c.lng, c.lat, p0.x, p0.y);
    map.on("mousemove", onMove);
    map.on("move", onMapMove);
    return () => { map.off("mousemove", onMove); map.off("move", onMapMove); };
  }, [picker]);

  const pickQuick = useCallback((days: number) => {
    setDaily(d => ({ ...d, on: false }));
    setPeriod(quickPeriod(days));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setPeriod]);

  const localWasm = wasmWindow(new Date());
  const wasmLabel = presets?.wasm?.start ? presets.wasm : localWasm;
  const pickWasm = useCallback(() => {
    setDaily(d => ({ ...d, on: false }));
    const w = presets?.wasm?.start ? presets.wasm : wasmWindow(new Date());
    setPeriod({ key: "wasm", from: w.start, to: w.end });
  }, [presets]);

  const applyCustom = useCallback(() => {
    if (STATIC) { say("الفترة المخصصة متاحة في التطبيق المحلي فقط"); return; }
    if (customFrom && customTo && customFrom <= customTo) {
      setDaily(d => ({ ...d, on: false }));
      setPeriod({ key: "custom", from: customFrom, to: customTo });
      setCustomOpen(false);
    }
  }, [customFrom, customTo, say]);

  const toggleLayer = useCallback((key: string, on: boolean) => {
    setVisible(v => ({ ...v, [key]: on }));
    const item = LAYER_GROUPS.flatMap(g => g.items).find(i => i.key === key);
    for (const id of item?.ids ?? [key]) {
      if (mapRef.current?.getLayer(id))
        mapRef.current.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    }
  }, []);

  const setAllLayers = useCallback((on: boolean) => {
    setVisible(Object.fromEntries(ALL_LAYER_KEYS.map(k => [k, on])));
    for (const id of LAYER_GROUPS.flatMap(g => g.items).flatMap(i => i.ids)) {
      if (mapRef.current?.getLayer(id))
        mapRef.current.setLayoutProperty(id, "visibility", on ? "visible" : "none");
    }
  }, []);

  const doSearch = useCallback((q: string) => {
    setQuery(q);
    const t = q.trim();
    // إحداثيات مباشرة: "24.7,46.7"
    const m = /^(-?\d+(?:\.\d+)?)[,\s]+(-?\d+(?:\.\d+)?)$/.exec(t);
    if (m && Math.abs(+m[1]) <= 90 && Math.abs(+m[2]) <= 180) {
      mapRef.current?.flyTo({ center: [+m[2], +m[1]], zoom: 10 });
      setResults(null);
      return;
    }
    if (t.length < 2) { setResults(null); return; }
    const needle = t;
    const out: SearchResult[] = [];
    for (const r of searchIndexRef.current) {
      if (r.name.includes(needle)) { out.push(r); if (out.length >= 25) break; }
    }
    setResults(out);
  }, []);

  const share = useCallback(async () => {
    const url = window.location.href;
    try { await navigator.clipboard.writeText(url); say("نُسخ الرابط"); }
    catch { say(url.slice(0, 40) + "…"); }
  }, [say]);

  const panel = dark ? "bg-stone-900/95 text-stone-100" : "bg-white/95";
  const chip = dark ? "bg-stone-800 hover:bg-stone-700 text-stone-100" : "bg-stone-100 hover:bg-stone-200";

  return (
    <div className="w-full relative overflow-hidden" style={{ height: "100vh" }}>
      <div ref={container} className="absolute inset-0" style={{ minHeight: "100vh", zIndex: 2 }} />

      {/* أدوات عائمة: قياس/مشاركة/ليلي */}
      <div className="absolute bottom-28 right-3 z-10 flex flex-col gap-1.5">
        <button onClick={() => setMeasure(m => m === "line" ? "off" : "line")}
          title="قياس مسافة"
          className={`w-9 h-9 rounded-xl shadow-lg text-lg ${panel} ${measure === "line" ? "ring-2 ring-rose-500" : ""}`}>📏</button>
        <button onClick={() => setMeasure(m => m === "area" ? "off" : "area")}
          title="قياس مساحة"
          className={`w-9 h-9 rounded-xl shadow-lg text-lg ${panel} ${measure === "area" ? "ring-2 ring-rose-500" : ""}`}>⬠</button>
        <button onClick={share} title="مشاركة الرابط"
          className={`w-9 h-9 rounded-xl shadow-lg text-lg ${panel}`}>🔗</button>
        <button onClick={() => setDark(d => !d)} title="الوضع الليلي"
          className={`w-9 h-9 rounded-xl shadow-lg text-lg ${panel}`}>{dark ? "☀️" : "🌙"}</button>
        <button onClick={() => setPicker(v => !v)} title="مؤشر المطر (يتحرك مع الفأرة)"
          className={`w-9 h-9 rounded-xl shadow-lg text-lg ${panel} ${picker ? "ring-2 ring-sky-500" : ""}`}>🎯</button>
        <button onClick={() => setLayersOpen(o => !o)} title="الطبقات"
          className={`w-9 h-9 rounded-xl shadow-lg text-lg ${panel} ${layersOpen ? "ring-2 ring-sky-500" : ""}`}>🗂️</button>
        <button onClick={() => setRadarOn(v => !v)} title="رادار المطر (آخر ساعة)"
          className={`w-9 h-9 rounded-xl shadow-lg text-lg ${panel} ${radarOn ? "ring-2 ring-sky-500" : ""}`}>🌧️</button>
        <button onClick={() => setSeasonOpen(o => !o)} title="متابعة الوسم"
          className={`w-9 h-9 rounded-xl shadow-lg text-lg ${panel} ${seasonOpen ? "ring-2 ring-emerald-500" : ""} ${STATIC ? "hidden" : ""}`}>📈</button>
        <button onClick={() => setTopOpen(o => !o)} title="أعلى المناطق مطراً في الفترة"
          className={`w-9 h-9 rounded-xl shadow-lg text-lg ${panel} ${topOpen ? "ring-2 ring-amber-500" : ""} ${STATIC ? "hidden" : ""}`}>🏆</button>
        <button onClick={() => setNdviOn(v => !v)} title="الخضرة الفعلية NDVI (Sentinel-2)"
          className={`w-9 h-9 rounded-xl shadow-lg text-lg ${panel} ${ndviOn ? "ring-2 ring-green-600" : ""} ${STATIC ? "hidden" : ""}`}>🌿</button>
        <button onClick={() => setRawdatOpen(o => !o)} title="روضات وفيضات أمطرت في الفترة"
          className={`w-9 h-9 rounded-xl shadow-lg text-lg ${panel} ${rawdatOpen ? "ring-2 ring-green-500" : ""} ${STATIC ? "hidden" : ""}`}>🌱</button>
        <button onClick={() => setNotesOpen(o => !o)} title={`دفتر الملاحظات (${notes.length})`}
          className={`w-9 h-9 rounded-xl shadow-lg text-lg ${panel} ${notesOpen ? "ring-2 ring-yellow-500" : ""} relative`}>
          📝{notes.length > 0 && <span className="absolute -top-1 -left-1 bg-yellow-500 text-white text-[9px] rounded-full px-1">{notes.length}</span>}
        </button>
      </div>

      {/* روضات الفترة */}
      {rawdatOpen && (
        <div className={`absolute top-[19rem] right-3 z-20 ${panel} rounded-2xl shadow-lg p-3 w-[min(16rem,86vw)] text-sm max-h-[46vh] overflow-auto`}>
          <button className="float-left opacity-50" onClick={() => setRawdatOpen(false)}>✕</button>
          <h3 className="font-bold mb-2">روضات وفيضات الفترة</h3>
          <div className="flex gap-1 mb-2">
            {[5, 10, 20, 40].map(t => (
              <button key={t} onClick={() => setRainThr(t)}
                className={`px-2 py-0.5 rounded-full text-[11px] ${rainThr === t ? "bg-green-700 text-white" : chip}`}>
                ≥{t}مم
              </button>
            ))}
          </div>
          {rawdatList.length === 0 && <div className="opacity-60 text-xs">لا روضات/فيضات مسمّاة بلغت العتبة — خفّضها أو غيّر الفترة.</div>}
          {rawdatList.map((r: any, i: number) => (
            <button key={i} className="w-full text-right flex justify-between items-center py-1 border-b border-stone-500/10 last:border-0 hover:opacity-70"
              onClick={() => mapRef.current?.flyTo({ center: [r.lon, r.lat], zoom: 12 })}>
              <span className="truncate">{r.kind === 'فيضة' ? '💧' : '🌿'} {r.name}</span>
              <span className="font-bold text-green-700">{r.mm} مم</span>
            </button>
          ))}
        </div>
      )}

      {/* دفتر ملاحظات المختبرين */}
      {notesOpen && (
        <div className={`absolute top-[19rem] right-3 z-20 ${panel} rounded-2xl shadow-lg p-3 w-[min(16rem,86vw)] text-sm max-h-[50vh] overflow-auto`}>
          <div className="flex items-center justify-between mb-2">
            <h3 className="font-bold">دفتر التجربة</h3>
            <div className="flex gap-1">
              <button className="text-[11px] px-1.5 py-0.5 rounded bg-stone-200 hover:bg-stone-300" onClick={exportNotes}>تصدير ⬇</button>
              <button className="opacity-50" onClick={() => setNotesOpen(false)}>✕</button>
            </div>
          </div>
          <div className="flex gap-1 mb-2">
            <input value={noteText} onChange={e => setNoteText(e.target.value)}
              placeholder="ملاحظة… (مثال: الربيع ظهر هنا)"
              className={`flex-1 border rounded-lg px-2 py-1 text-xs ${panel}`} />
            <button disabled={!noteText.trim()} onClick={() => setPendingNote(true)}
              title="ثم انقر على الخريطة"
              className="bg-yellow-500 text-white px-2 rounded-lg text-xs disabled:opacity-40">➕ موضع</button>
          </div>
          {pendingNote && <div className="text-[11px] text-yellow-600 mb-2">انقر الآن على موضع الملاحظة في الخريطة…</div>}
          {notes.length === 0 && <div className="opacity-50 text-xs">لا ملاحظات بعد — اكتب ملاحظة ثم اضغط «➕ موضع» وانقر الخريطة.</div>}
          {notes.map(n => (
            <div key={n.id} className={`border-b border-stone-500/10 py-1.5 ${n.type === "flag" ? "bg-red-500/5" : ""}`}>
              <div className="text-xs">{n.type === "flag" ? "⚠️ " : "📝 "}{n.text}</div>
              <div className="flex items-center justify-between mt-0.5">
                <span className="text-[10px] opacity-50" dir="ltr">
                  {n.lat.toFixed(3)},{n.lon.toFixed(3)}{n.mm != null ? ` · ${n.mm}مم` : ""}
                </span>
                <span className="flex gap-1">
                  <button className="text-[10px] opacity-60 hover:opacity-100" title="اذهب إليها"
                    onClick={() => mapRef.current?.flyTo({ center: [n.lon, n.lat], zoom: 11 })}>✈️</button>
                  <button className="text-[10px] opacity-60 hover:opacity-100" title="حذف"
                    onClick={() => removeNote(n.id)}>🗑</button>
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* لوحة الوسم */}
      {seasonOpen && season && (
        <div className={`absolute top-3 left-3 mt-11 z-20 ${panel} rounded-2xl shadow-lg p-3 w-[min(16rem,86vw)] text-sm`}>
          <button className="float-left opacity-50" onClick={() => setSeasonOpen(false)}>✕</button>
          <h3 className="font-bold mb-2">موسم الوسم {new Date().getFullYear()}</h3>
          {!season.current.started ? (
            <div className="text-sm mb-2">لم يبدأ بعد — ينطلق {season.window.start} (متوسط السنوات: {season.normal_avg_mm} مم)</div>
          ) : (<>
          <div className="flex justify-between items-baseline mb-1">
            <span className="opacity-70">الموسم الحالي (متوسط المملكة)</span>
            <span className="text-xl font-bold text-emerald-700">{season.current.mean_mm} مم</span>
          </div>
          <div className="text-xs opacity-70 mb-2">اليوم {season.current.days_in} من {season.window.length} · {season.current.wet_pct}٪ من الأراضي أمطرت ≥5مم</div>
          </>)}
          {season.normal_avg_mm && (
            <div className="mb-2">
              <div className="flex justify-between text-xs mb-1">
                <span>مقابل متوسط {season.years} سنوات ({season.normal_avg_mm} مم)</span>
                <span className="font-bold">{season.pct_of_normal}٪</span>
              </div>
              <div className="h-2.5 rounded-full bg-stone-200 overflow-hidden">
                <div className="h-full rounded-full" style={{
                  width: `${Math.min(season.pct_of_normal ?? 0, 100)}%`,
                  background: (season.pct_of_normal ?? 0) >= 80 ? "#16a34a" : (season.pct_of_normal ?? 0) >= 50 ? "#d97706" : "#dc2626"
                }} />
              </div>
            </div>
          )}
          <div className="text-[11px] opacity-60">أوسمة سابقة (متوسط): {season.history.map((h: any) => `${h.year}: ${h.mean_mm}`).join(" | ")}</div>
        </div>
      )}

      {/* لوحة أعلى المناطق */}
      {topOpen && (
        <div className={`absolute top-[19rem] left-3 z-20 ${panel} rounded-2xl shadow-lg p-3 w-[min(16rem,86vw)] text-sm max-h-[46vh] overflow-auto`}>
          <button className="float-left opacity-50" onClick={() => setTopOpen(false)}>✕</button>
          <h3 className="font-bold mb-2">أعلى المناطق ({period.key === "wasm" ? "الوسم" : "الفترة"})</h3>
          {topList.length === 0 && <div className="opacity-60 text-xs">جارٍ الحساب…</div>}
          {topList.map((t: any, i: number) => (
            <button key={i} className="w-full text-right flex justify-between items-center py-1 border-b border-stone-500/10 last:border-0 hover:opacity-70"
              onClick={() => mapRef.current?.flyTo({ center: [t.lon, t.lat], zoom: 9 })}>
              <span className="truncate">{i + 1}) {t.near ? `${t.near}${t.near_km ? ` (${t.near_km} كم)` : ""}` : `${t.lat}، ${t.lon}`}</span>
              <span className="font-bold text-sky-700">{t.mm} مم</span>
            </button>
          ))}
        </div>
      )}

      {measure !== "off" && (
        <div className={`absolute top-16 left-1/2 -translate-x-1/2 z-20 ${panel} rounded-xl shadow-lg px-4 py-2 text-sm`}>
          {measure === "line" ? "انقر على نقاط المسار — انقر نقطة أخيرة مرتين للإنهاء" : "انقر رؤوس المضلع — انقر النقطة الأولى مرة أخيرة للإغلاق"}
          {measureResult && <span className="font-bold mr-3 text-rose-600">{measureResult}</span>}
        </div>
      )}
      {toast && (
        <div className="absolute top-16 left-1/2 -translate-x-1/2 z-20 bg-emerald-700 text-white rounded-xl shadow-lg px-4 py-2 text-sm">{toast}</div>
      )}

      {/* البحث */}
      <div className="absolute top-3 left-3 z-20 w-[min(16rem,70vw)]">
        <input value={query} onChange={e => doSearch(e.target.value)}
          placeholder="مدينة، واد، جبل، فيضة… أو 24.7,46.7"
          className={`w-full ${panel} rounded-xl shadow-lg px-3 py-2 text-sm outline-none focus:ring-2 ring-sky-500`} />
        {results && results.length > 0 && (
          <div className={`${panel} rounded-xl shadow-lg mt-1 max-h-56 overflow-auto text-sm`}>
            {results.map((r, i) => (
              <button key={i} className="w-full text-right px-3 py-1.5 hover:bg-stone-500/10 border-b border-stone-500/10 last:border-0"
                onClick={() => { mapRef.current?.flyTo({ center: [r.lon, r.lat], zoom: 11 }); setResults(null); setQuery(r.name); }}>
                {r.name} <span className="text-stone-400 text-xs">{r.kind}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* وسيلة الإيضاح */}
      {!point && (
        <div className={`absolute top-3 left-3 mt-11 z-10 ${panel} rounded-xl shadow p-2 text-[11px]`}>
          <div className="font-semibold mb-1">{daily.on ? `مطر يوم ${daily.date} (مم)` : "مجموع المطر (مم)"}</div>
          {[["#d9f0a3", 0.02], ["#78c679", 0.12], ["#31a354", 0.25], ["#fec44f", 0.5], ["#f03b20", 0.75], ["#bd0026", 1]].map(([c, t]) => (
            <div key={String(t)} className="flex items-center gap-1.5">
              <span className="inline-block w-4 h-3 rounded-sm" style={{ background: c }} />
              {t === 1 ? `${Math.round(vmax)}+` : `~${Math.round(vmax * Number(t))}`}
            </div>
          ))}
          <div className="mt-1 text-stone-400">{source === "imerg_v07" ? "NASA IMERG ≈10 كم" : "CHIRPS v3 ≈5 كم"}</div>
          {ndviOn && (
            <div className="mt-2 pt-2 border-t border-stone-300">
              <div className="font-semibold mb-1">NDVI خضرة فعلية 🌿</div>
              <div className="flex items-center gap-1">
                <span className="text-[10px]">عراء</span>
                <span className="flex-1 h-2.5 rounded" style={{ background: "linear-gradient(90deg,#8c510a,#d8b365,#a6d96a,#1a9850,#006837)" }} />
                <span className="text-[10px]">كثيف</span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* لوحة الطبقات (تظهر عند الطلب فقط) */}
      {layersOpen && (
      <div className={`absolute top-3 right-3 ${panel} rounded-2xl shadow-lg p-3 w-56 max-h-[70vh] overflow-auto z-10 text-sm`}>
        <div className="flex items-center justify-between mb-2">
          <h2 className="font-bold">الطبقات</h2>
          <button className="opacity-50 hover:opacity-100" onClick={() => setLayersOpen(false)}>✕</button>
          <div className="flex gap-1 text-[11px]">
            <button className={`px-1.5 py-0.5 rounded ${chip}`} onClick={() => setAllLayers(true)}>الكل</button>
            <button className={`px-1.5 py-0.5 rounded ${chip}`} onClick={() => setAllLayers(false)}>بدون</button>
          </div>
        </div>
        {LAYER_GROUPS.map(g => (
          <details key={g.group} open className="mb-1">
            <summary className="font-semibold opacity-70 cursor-pointer">{g.group}</summary>
            {g.items.map(it => (
              <label key={it.key} className="flex items-center gap-2 pr-3 py-0.5">
                <input type="checkbox" checked={!!visible[it.key]} onChange={e => toggleLayer(it.key, e.target.checked)} />
                {it.label}
              </label>
            ))}
          </details>
        ))}
      </div>
      )}

      {/* شريط الفترات */}
      <div className="absolute bottom-4 inset-x-0 flex justify-center z-10">
        <div className={`${panel} rounded-2xl shadow-lg px-3 py-2 flex flex-wrap gap-1.5 max-w-[96vw] items-center`}>
          {QUICK.map(q => (
            <button key={q.key} onClick={() => pickQuick(q.days)}
              className={`px-2.5 py-1 rounded-full text-xs ${period.key === q.key ? "bg-sky-700 text-white" : chip} ${daily.on ? "opacity-40" : ""}`}>
              {q.label}
            </button>
          ))}
          <button onClick={pickWasm}
            className={`px-2.5 py-1 rounded-full text-xs font-bold ${period.key === "wasm" ? "bg-emerald-700 text-white" : dark ? "bg-emerald-900 text-emerald-200" : "bg-emerald-100 hover:bg-emerald-200"} ${daily.on ? "opacity-40" : ""}`}>
            الوسم{(() => {
              const t = new Date();
              const [m, d] = wasmLabel.start.slice(5).split("-").map(Number);
              const s0 = new Date(t.getFullYear(), m - 1, d);
              const diff = Math.floor((t.getTime() - s0.getTime()) / 864e5) + 1;
              const inside = diff >= 1 && diff <= 52;
              return inside ? ` (اليوم ${diff}/52)` : ` (${wasmLabel.start} → ${wasmLabel.end})`;
            })()}
          </button>
          {!STATIC && (
          <button onClick={() => setCustomOpen(o => !o)}
            className={`px-2.5 py-1 rounded-full text-xs ${period.key === "custom" ? "bg-sky-700 text-white" : chip} ${daily.on ? "opacity-40" : ""}`}>مخصص…</button>
          )}
          <button onClick={() => setDaily(d => ({ ...d, on: !d.on }))}
            title="عرض مطر يوم محدد مع التنقل بين الأيام"
            className={`px-2.5 py-1 rounded-full text-xs font-bold ${daily.on ? "bg-indigo-700 text-white" : chip}`}>
            🗓 يوم
          </button>
          {daily.on && (
            <span className="flex items-center gap-0.5" dir="ltr">
              <button onClick={() => shiftDay(-1)} disabled={daily.date <= "1981-01-01"}
                title="اليوم السابق"
                className={`w-7 h-7 rounded-full text-base font-bold leading-none ${daily.date <= "1981-01-01" ? "opacity-30" : chip}`}>‹</button>
              <input type="date" value={daily.date} min="1981-01-01" max={yesterday()}
                onChange={e => e.target.value && setDaily(d => ({ ...d, date: e.target.value }))}
                className={`text-xs border rounded-lg px-1.5 py-1 ${panel}`} />
              <button onClick={() => shiftDay(1)} disabled={daily.date >= yesterday()}
                title="اليوم التالي"
                className={`w-7 h-7 rounded-full text-base font-bold leading-none ${daily.date >= yesterday() ? "opacity-30" : chip}`}>›</button>
            </span>
          )}
          <select value={source} onChange={e => setSource(e.target.value as typeof source)}
            className={`text-xs border rounded-full px-2 py-1 ${panel}`}>
            <option value="imerg_v07">IMERG ≈10كم</option>
            <option value="chirps_v3">CHIRPS ≈5كم</option>
          </select>
          <button onClick={() => setRainMode(m => m === "highlight" ? "gradient" : "highlight")}
            className={`px-2.5 py-1 rounded-full text-xs font-bold ${rainMode === "highlight" ? "bg-cyan-700 text-white" : chip}`}
            title="إبراز الخلايا فوق عتبة بدل التدرج">
            💧 أين أمطرت؟
          </button>
          {rainMode === "highlight" && [5, 10, 20, 40].map(t => (
            <button key={t} onClick={() => setRainThr(t)}
              className={`px-2 py-1 rounded-full text-[11px] ${rainThr === t ? "bg-cyan-900 text-white" : chip}`}>
              ≥{t}
            </button>
          ))}
        </div>
      </div>

      {customOpen && (
        <div className={`absolute bottom-24 inset-x-0 flex justify-center z-20`}>
          <div className={`${panel} rounded-2xl shadow-lg px-4 py-3 flex items-center gap-2 text-sm`}>
            <label>من <input type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)}
              className={`mr-1 border rounded px-1.5 py-0.5 ${panel}`} /></label>
            <label>إلى <input type="date" value={customTo} onChange={e => setCustomTo(e.target.value)}
              className={`mr-1 border rounded px-1.5 py-0.5 ${panel}`} /></label>
            <button onClick={applyCustom} disabled={!customFrom || !customTo || customFrom > customTo}
              className="bg-sky-700 text-white px-3 py-1 rounded-lg disabled:opacity-40">اعرض</button>
          </div>
        </div>
      )}

      {/* نافذة النقطة */}
      {point && (
        <div className={`absolute top-3 left-3 ${panel} rounded-2xl shadow-lg p-3 w-[min(16rem,86vw)] z-20 text-sm`}>
          <button className="float-left opacity-50" onClick={() => setPoint(null)}>✕</button>
          <div className="font-mono text-[11px] mb-1 opacity-70" dir="ltr">{point.lat.toFixed(4)}, {point.lon.toFixed(4)}</div>
          <div className="text-xs mb-2 opacity-80">
            الارتفاع: {point.elev !== null ? `${point.elev} م` : "—"}
          </div>
          {!point.data && <div>جارِ التحميل…</div>}
          {point.data && (
            <>
              {[["10 أيام", point.data.sums_mm.last_10d], ["20 يوم", point.data.sums_mm.last_20d],
                ["40 يوم", point.data.sums_mm.last_40d], ["90 يوم", point.data.sums_mm.last_90d],
                [`الوسم ${point.data.wasm.year}`, point.data.wasm.sum_mm],
                ["365 يوم", point.data.sums_mm.last_365d]].map(([label, v]) => (
                <div key={label as string} className="flex justify-between border-b border-stone-500/10 py-0.5">
                  <span>{label}</span><span className="font-bold">{v ?? "—"} مم</span>
                </div>
              ))}
              <div className="mt-1 opacity-80">
                آخر مطر في خلية البيانات: {point.data.last_rain_day ?? "—"}
              </div>
              <div className="text-[10px] opacity-50 mt-1">{point.data.disclaimer}</div>
              <button className="mt-2 w-full text-[11px] text-red-600 border border-red-300 rounded-lg py-1 hover:bg-red-50"
                onClick={() => {
                  if (!point.data) return;
                  addNote({ type: "flag", text: `الرقم لا يطابق الواقع (${point.data.sums_mm.last_10d ?? "؟"} مم/10أيام)`,
                            lat: point.lat, lon: point.lon, mm: point.data.sums_mm.last_10d, period: period.key });
                  say("سُجلت ملاحظة الفرق ⚠️");
                }}>
                ⚠️ بلّغ عن فرق بين الرقم والواقع
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
