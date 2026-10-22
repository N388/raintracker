// لقطة تشخيصية مضبوطة: تنتظر فعلياً، وتطبع سجلات وحدة التحكم
import puppeteer from "puppeteer-core";

const url = process.argv[2] ?? "http://localhost:3100/test-map";
const out = process.argv[3] ?? "/tmp/pp.png";

const browser = await puppeteer.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: "new",
  args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--no-sandbox"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1400, height: 900 });
page.on("console", m => console.log("[console]", m.type(), m.text().slice(0, 200)));
page.on("pageerror", e => console.log("[pageerror]", e.message.slice(0, 300)));
page.on("requestfailed", r => console.log("[reqfail]", r.url().slice(0, 120), r.failure()?.errorText));

await page.goto(url, { waitUntil: "networkidle2", timeout: 60000 });
await new Promise(r => setTimeout(r, 12000));

const diag = await page.evaluate(() => {
  const c = document.querySelector("canvas");
  const gl = c?.getContext("webgl2") || c?.getContext("webgl");
  return {
    canvas: !!c, size: c ? `${c.width}x${c.height}` : null,
    glVersion: gl ? gl.getParameter(gl.VERSION) : null,
    status: document.getElementById("st")?.textContent ?? null,
  };
});
console.log("[diag]", JSON.stringify(diag));
await page.screenshot({ path: out });
await browser.close();
console.log("saved", out);
