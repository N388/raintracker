/** @type {import('next').NextConfig} */
const nextConfig = {
  // محلي: standalone (خادم كامل) — النشر على GitHub Pages: export ساكن
  output: process.env.STATIC_EXPORT === "1" ? "export" : "standalone",
  reactStrictMode: true,
  // مسار القاعدة عند النشر تحت username.github.io/<repo>
  basePath: process.env.PAGES_BASE || undefined,
  assetPrefix: process.env.PAGES_BASE || undefined,
};
module.exports = nextConfig;
