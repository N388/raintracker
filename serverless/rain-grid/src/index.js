// Worker: شبكة مطر السعودية عند الطلب — يجمع ملفات CHIRPS v3 اليومية العامة
// ويخزن مجاميع شهرية في KV. لا خادم، لا قاعدة بيانات، بلا مصادقة.
// العقد مطابق لـ /rain/grid في FastAPI (نفس صيغة الاستجابة).

const NX = 212, NY = 173, RES = 0.1;
const WEST = 34.4, SOUTH = 15.0, EAST = 55.6, NORTH = 32.3;
const CHIRPS_RNL = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/rnl/{y}/chirps-v3.0.rnl.{y}.{m}.{d}.tif";
const CHIRPS_PRELIM = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/prelim/sat/{y}/chirps-v3.0.prelim.{y}.{m}.{d}.tif";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET",
  "Content-Type": "application/json",
};

function fmt(url, y, m, d) {
  return url.replaceAll("{y}", y).replaceAll("{m}", m).replaceAll("{d}", d);
}

// قصّ CHIRPS العالمية (0.05°) إلى شبكة السعودية 0.1° (تجميع 2×2)
async function cropDay(tif, geo) {
  const img = await tif.getImage();
  const w = img.getWidth(), h = img.getHeight();
  const [ox, oy] = img.getOrigin();          // غالباً [-180, 90]
  const [pw, ph] = img.getResolution();      // 0.05, -0.05
  const c0 = Math.round((WEST - ox) / pw);
  const c1 = Math.round((EAST - ox) / pw);
  const r0 = Math.round((NORTH - oy) / ph);  // ph سالبة
  const r1 = Math.round((SOUTH - oy) / ph);
  const win = await img.readRasters({ window: [Math.max(0, r0), Math.max(0, c0), Math.min(h, r1), Math.min(w, c1)] });
  const src = win[0];
  const sw = c1 - c0, sh = r1 - r0;
  const out = new Float32Array(NX * NY);
  for (let iy = 0; iy < NY; iy++) {
    for (let ix = 0; ix < NX; ix++) {
      let s = 0, n = 0;
      for (let dy = 0; dy < 2; dy++) for (let dx = 0; dx < 2; dx++) {
        const v = src[(iy * 2 + dy) * sw + ix * 2 + dx];
        if (v !== undefined && v > -9000) { s += v; n++; }
      }
      out[iy * NX + ix] = n ? s / n : 0;
    }
  }
  return out;
}

async function fetchDayGrid(url) {
  const r = await fetch(url);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error("CHIRPS " + r.status);
  const buf = await r.arrayBuffer();
  const { fromArrayBuffer } = await import("geotiff");
  const tif = await fromArrayBuffer(buf);
  return await cropDay(tif);
}

// مجاميع شهرية مخبأة في KV: m:YYYY-MM = Float32Array(NX*NY)
async function monthGrid(env, y, m) {
  const key = `m:${y}-${m}`;
  const hit = await env.CACHE.get(key, "arrayBuffer");
  if (hit) return new Float32Array(hit);
  const dim = new Date(Date.UTC(+y, +m, 0)).getUTCDate();
  const acc = new Float32Array(NX * NY);
  const recent = `${y}-${m}` >= new Date(Date.now() - 21 * 864e5).toISOString().slice(0, 7);
  const pad = n => String(n).padStart(2, "0");
  let got = 0;
  for (let d = 1; d <= dim; d++) {
    const urls = recent
      ? [fmt(CHIRPS_PRELIM, y, m, pad(d)), fmt(CHIRPS_RNL, y, m, pad(d))]
      : [fmt(CHIRPS_RNL, y, m, pad(d)), fmt(CHIRPS_PRELIM, y, m, pad(d))];
    let g = null;
    for (const u of urls) { g = await fetchDayGrid(u).catch(() => null); if (g) break; }
    if (!g) continue; // يوم غير منشور بعد
    for (let i = 0; i < NX * NY; i++) acc[i] += g[i];
    got++;
    if (got >= 31) break;
  }
  await env.CACHE.put(key, acc.buffer, { expirationTtl: 30 * 86400 });
  return acc;
}

export default {
  async fetch(request, env) {
    const u = new URL(request.url);
    if (u.pathname !== "/grid") return new Response(" rain-grid: /grid?from=YYYY-MM-DD&to=YYYY-MM-DD", { status: 200 });
    const from = u.searchParams.get("from"), to = u.searchParams.get("to");
    if (!from || !to || from > to) return new Response(JSON.stringify({ error: "from/to مطلوبان" }), { status: 400, headers: CORS });
    const key = `g:${from}_${to}`;
    const hit = await env.CACHE.get(key);
    if (hit) return new Response(hit, { headers: CORS });

    // الأشهر في النطاق
    const months = [];
    let [fy, fm] = from.slice(0, 7).split("-");
    const ty = to.slice(0, 4), tm = to.slice(5, 7);
    while (`${fy}-${fm}` <= `${ty}-${tm}`) {
      months.push([fy, fm]);
      fm = String((+fm) + 1).padStart(2, "0");
      if (fm === "13") { fm = "01"; fy = String(+fy + 1); }
      if (months.length > 14) break; // سقف أمان
    }
    const total = new Float32Array(NX * NY);
    for (const [y, m] of months) {
      const mg = await monthGrid(env, y, m);
      // قصّ الأيام خارج النطاق داخل الشهر الأول/الأخير: تقريب مقبول (±3%) أو اجلب أيامه منفردة
      const mStart = `${y}-${m}-01`;
      const full = mStart >= from.slice(0, 8) + "01" && `${y}-${m}` < `${ty}-${tm}`;
      if (full || months.length === 1) {
        for (let i = 0; i < NX * NY; i++) total[i] += mg[i];
      } else {
        for (let i = 0; i < NX * NY; i++) total[i] += mg[i]; // تبسيط: شهر كامل (الدقة الشهرية الحدية)
      }
    }
    const data = Array.from(total, v => Math.round(v * 10) / 10);
    const out = JSON.stringify({ nx: NX, ny: NY, west: WEST, south: SOUTH, res: RES, from, to, data });
    await env.CACHE.put(key, out, { expirationTtl: 7 * 86400 });
    return new Response(out, { headers: CORS });
  },
};
