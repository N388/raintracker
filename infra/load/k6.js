// اختبار حمل k6 — معيار M4: 500 مستخدم متزامن
// التشغيل: k6 run infra/load/k6.js
import http from "k6/http";
import { check } from "k6";

export const options = {
  vus: 500,
  duration: "60s",
  thresholds: {
    http_req_duration: ["p(95)<500"],
    http_req_failed: ["rate<0.01"],
  },
};

const API = __ENV.API_URL ?? "http://localhost:8080/api/v1";
const POINTS = [
  [24.71, 46.68], [26.42, 43.97], [21.49, 39.19], [28.38, 36.57],
  [24.63, 46.72], [17.49, 44.13], [29.97, 40.2], [25.9, 44.2],
];

export default function () {
  const [lat, lon] = POINTS[Math.floor(Math.random() * POINTS.length)];
  const r = http.get(`${API}/rain/point?lat=${lat}&lon=${lon}&source=imerg_v07`);
  check(r, { "point 200": (x) => x.status === 200, "point fast": (x) => x.timings.duration < 200 });
  const z = 9, n = 512;
  const x = Math.floor(((lon + 180) / 360) * n);
  const latR = (lat * Math.PI) / 180;
  const y = Math.floor(((1 - Math.log(Math.tan(latR) + 1 / Math.cos(latR)) / Math.PI) / 2) * n);
  const t = http.get(`${API}/rain/tiles/${z}/${x}/${y}.png?from=2026-09-15&to=2026-09-18&source=imerg_v07`, { redirects: 5 });
  check(t, { "tile ok": (x2) => x2.status === 200 });
}
