import puppeteer from "puppeteer-core";
const b = await puppeteer.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: "new", args: ["--no-sandbox"] });
const p = await b.newPage();
await p.setViewport({ width: 1400, height: 900 });
await p.goto("http://localhost:3100/#6/24/45", { waitUntil: "networkidle2", timeout: 90000 });
await new Promise(r => setTimeout(r, 15000));
const res = await p.evaluate(() => {
  const m = window.__map;
  // الشبكة: west 34.4, north 32.3, res 0.1, nx 212, ny 173 — كل خلية 4 بكسل
  const c = document.createElement("canvas");
  c.width = 212 * 4; c.height = 173 * 4;
  const x = c.getContext("2d");
  // خط أحمر عمودي عند خط طول الرياض 46.7 → العمود 123
  x.fillStyle = "rgba(255,0,0,0.85)";
  x.fillRect(123 * 4, 0, 4, c.height);
  // خط أخضر أفقي عند خط عرض الرياض 24.4 → الصف (32.3-24.4)/0.1 = 79
  x.fillStyle = "rgba(0,200,0,0.85)";
  x.fillRect(0, 79 * 4, c.width, 4);
  // علامة زرقاء عند الخلية الشمالية الغربية (0,0)
  x.fillStyle = "rgba(0,0,255,0.9)";
  x.fillRect(0, 0, 20, 20);
  m.getSource("rain").updateImage({ url: c.toDataURL("image/png") });
  // المقارنة: أين يجب أن يظهر كل خط على الشاشة؟
  const pr = m.project([46.7, 24.0]);
  const prLat = m.project([45.0, 24.4]);
  const prNW = m.project([34.4, 32.3]);
  return { riyadhLonX: pr.x, riyadhLatY: prLat.y, nwCorner: prNW, zoom: m.getZoom() };
});
console.log(JSON.stringify(res));
await new Promise(r => setTimeout(r, 2500));
await p.screenshot({ path: "/tmp/align.png", clip: { x: 500, y: 300, width: 400, height: 300 } });
await p.screenshot({ path: "/tmp/align-full.png" });
await b.close();
