// منطق المطر المباشر (Serverless): Open-Meteo بلا خادم ولا تخزين.
// يغطي كامل السعودية (ERA5 شبكي) بلا محطات أرضية، و bbox سعودي حصرياً.

export const BBOX = { west: 34.4, south: 15.0, east: 55.6, north: 32.3 };

// نفس منطق SQL wasm_window: 52 يوماً من 16 أكتوبر (افتراضي، قابل للضبط)
export function wasmWindow(today: Date, startMd = "10-16", lengthDays = 52) {
  const [m, d] = startMd.split("-").map(Number);
  const sy = today.getFullYear();
  const s = new Date(Date.UTC(sy, m - 1, d));
  const e = new Date(s.getTime() + (lengthDays - 1) * 864e5);
  if (today >= s) return { start: iso(s), end: iso(today), year: sy, ongoing: today <= e };
  const ps = new Date(Date.UTC(sy - 1, m - 1, d));
  return { start: iso(ps), end: iso(new Date(ps.getTime() + (lengthDays - 1) * 864e5)), year: sy - 1, ongoing: false };
}

export function iso(d: Date) {
  return d.toISOString().slice(0, 10);
}

export function daysAgo(n: number, from = new Date()) {
  return iso(new Date(from.getTime() - n * 864e5));
}

const ARCHIVE = "https://archive-api.open-meteo.com/v1/archive";

/** نقطة واحدة: طلب واحد يغطي كل النوافذ (10/20/40/90/365/وسم + آخر مطر + ارتفاع). */
export async function fetchPointWindows(lat: number, lon: number, wasm: ReturnType<typeof wasmWindow>) {
  const today = new Date();
  const start365 = daysAgo(365, today);
  const start = start365 < wasm.start ? start365 : wasm.start;
  const end = daysAgo(1, today); // آخر يوم مكتمل
  const url = `${ARCHIVE}?latitude=${lat.toFixed(4)}&longitude=${lon.toFixed(4)}` +
    `&start_date=${start}&end_date=${end}&daily=precipitation_sum&timezone=UTC`;
  const r = await fetch(url);
  if (!r.ok) throw new Error("Open-Meteo " + r.status);
  const j = await r.json();
  const days: string[] = j.daily.time;
  const vals: number[] = j.daily.precipitation_sum;
  const sum = (d1: string, d2: string) => {
    let s = 0;
    for (let i = 0; i < days.length; i++) if (days[i] > d2) break;
    else if (days[i] >= d1) s += vals[i] || 0;
    return r1(s);
  };
  let lastRain: string | null = null;
  for (let i = days.length - 1; i >= 0; i--) if ((vals[i] || 0) >= 0.1) { lastRain = days[i]; break; }
  const t = iso(today);
  return {
    sums_mm: {
      last_10d: sum(daysAgo(10, today), t), last_20d: sum(daysAgo(20, today), t),
      last_40d: sum(daysAgo(40, today), t), last_90d: sum(daysAgo(90, today), t),
      last_365d: sum(start365, t),
    },
    wasm: { sum_mm: sum(wasm.start, wasm.end), year: wasm.year, ongoing: wasm.ongoing },
    last_rain_day: lastRain,
    elevation_m: typeof j.elevation === "number" ? Math.round(j.elevation) : null,
    disclaimer: "تقدير ERA5 لخلية بيانات (~10 كم) — ليس قياساً في النقطة",
  };
}

// شبكة المملكة بدقة 0.1° (مطابقة لشبكة IMERG لدينا)
export const GRID = { nx: 212, ny: 173, res: 0.1, ...BBOX };

/** يجلب شبكة الفترة من endpoint تجميعي (Worker في الإنتاج أو /rain/grid محلياً). */
// إن عُيّن NEXT_PUBLIC_STATIC_GRIDS=1 (بناء GitHub Pages) تُقرأ الشبكات من ملفات
// ثابتة data/grids/<key>.json تولّدها GitHub Actions — وإلا من الـ API المحلي الكامل.
const STATIC_GRIDS = process.env.NEXT_PUBLIC_STATIC_GRIDS === "1";

export async function fetchGrid(baseUrl: string, from: string, to: string, key = ""): Promise<{ arr: Float32Array; partial: boolean; missing: number; gfs: number }> {
  if (STATIC_GRIDS && key) {
    let path: string | null = null;
    if (key === "wasm") path = "wasm.json";
    else if (/^\d+days$/.test(key)) path = `${key}.json`;
    else if (/^day:\d{4}-\d{2}-\d{2}$/.test(key)) path = `day/${key.slice(4)}.json`;
    if (path) {
      const r = await fetch(`${process.env.NEXT_PUBLIC_BASEPATH ?? ""}/data/grids/${path}`);
      if (!r.ok) throw new Error("static-grid-missing");
      const j = await r.json();
      return { arr: new Float32Array(j.data), partial: !!j.partial, missing: j.missing ?? 0, gfs: j.gfs ?? 0 };
    }
    throw new Error("static-custom-unsupported");
  }
  const sep = baseUrl.includes("?") ? "&" : "?";
  const r = await fetch(`${baseUrl}${sep}from=${from}&to=${to}`);
  if (!r.ok) throw new Error("grid " + r.status);
  const j = await r.json();
  return { arr: new Float32Array(j.data), partial: !!j.partial, missing: j.missing ?? 0, gfs: j.gfs ?? 0 };
}

// تدرّج المطر (مطابق للـ API/legend)
const STOPS: [number, [number, number, number]][] = [
  [0, [217, 240, 163]], [1, [217, 240, 163]], [5, [120, 198, 121]], [10, [49, 163, 84]],
  [20, [254, 196, 79]], [40, [240, 59, 32]], [80, [189, 0, 38]],
];

export function colorFor(v: number, vmax = 80): [number, number, number, number] {
  if (v < 0.3) return [0, 0, 0, 0];           // رذاذ/ضجيج → شفاف
  const t = Math.min(v / vmax, 1);
  if (t <= 0.02) return [217, 240, 163, 150];
  if (t <= 0.12) return [120, 198, 121, 190];
  for (let i = 1; i < STOPS.length; i++) {
    if (t * 80 <= STOPS[i][0]) {
      const [v0, c0] = STOPS[i - 1];
      const [v1, c1] = STOPS[i];
      const k = (t * 80 - v0) / (v1 - v0);
      return [Math.round(c0[0] + (c1[0] - c0[0]) * k),
              Math.round(c0[1] + (c1[1] - c0[1]) * k),
              Math.round(c0[2] + (c1[2] - c0[2]) * k), 200];
    }
  }
  return [189, 0, 38, 230];
}

/** أعلى قيمة مرجعية للفترة (الوسيط 98 — مقاوم للقيم الشاذة). */
export function vmaxOf(data: Float32Array): number {
  const arr = Array.from(data).filter(v => v > 0.3).sort((a, b) => a - b);
  if (!arr.length) return 80;
  return Math.max(10, arr[Math.floor(arr.length * 0.98)] || 80);
}

export function gridToCanvasHighlight(data: Float32Array, thr: number): HTMLCanvasElement {
  const { nx, ny } = GRID;
  const cv = document.createElement("canvas");
  cv.width = nx; cv.height = ny;
  const ctx = cv.getContext("2d")!;
  const img = ctx.createImageData(nx, ny);
  for (let i = 0; i < nx * ny; i++) {
    if (data[i] >= thr) {
      img.data[i * 4] = 8; img.data[i * 4 + 1] = 145; img.data[i * 4 + 2] = 178; img.data[i * 4 + 3] = 215;
    }
  }
  ctx.putImageData(img, 0, 0);
  return cv;
}

export function gridToCanvas(data: Float32Array, vmax = 80): HTMLCanvasElement {
  const { nx, ny } = GRID;
  const cv = document.createElement("canvas");
  cv.width = nx; cv.height = ny;
  const ctx = cv.getContext("2d")!;
  const img = ctx.createImageData(nx, ny);
  for (let i = 0; i < nx * ny; i++) {
    const [r, g, b, a] = colorFor(data[i], vmax);
    img.data[i * 4] = r; img.data[i * 4 + 1] = g; img.data[i * 4 + 2] = b; img.data[i * 4 + 3] = a;
  }
  ctx.putImageData(img, 0, 0);
  return cv;
}

function r1(x: number) { return Math.round(x * 10) / 10; }

/** توقعات 7 أيام قادمة لنقطة (Open-Meteo forecast — مجاني). */
export async function fetchForecast7d(lat: number, lon: number): Promise<{ total_mm: number; rainy_days: number } | null> {
  try {
    const r = await fetch(
      `https://api.open-meteo.com/v1/forecast?latitude=${lat.toFixed(4)}&longitude=${lon.toFixed(4)}` +
      `&daily=precipitation_sum&forecast_days=7&timezone=UTC`);
    if (!r.ok) return null;
    const j = await r.json();
    const vals: number[] = j.daily?.precipitation_sum ?? [];
    const total = vals.reduce((a, b) => a + (b || 0), 0);
    return { total_mm: r1(total), rainy_days: vals.filter(v => (v || 0) >= 0.5).length };
  } catch {
    return null;
  }
}

/** آخر إطار رادار من RainViewer (مجاني، بلا مفتاح). */
export async function fetchRadarLatest(): Promise<{ urlTemplate: string; time: number } | null> {
  try {
    const r = await fetch("https://api.rainviewer.com/public/weather-maps.json");
    const j = await r.json();
    const past = j.radar?.past ?? [];
    if (!past.length) return null;
    const last = past[past.length - 1];
    return { urlTemplate: `${j.host}${last.path}/512/{z}/{x}/{y}/2/1_1.png`, time: last.time };
  } catch {
    return null;
  }
}
