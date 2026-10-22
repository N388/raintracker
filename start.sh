#!/usr/bin/env bash
# تشغيل منصة مطر بأمر واحد: الخدمات + المتصفح
set -e
cd "$(dirname "$0")"
export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin"
echo "==> إقلاع الخدمات..."
docker compose up -d
# بروكسي CHIRPS على المضيف (شبكة المضيف أثبت من NAT الحاوية لدى UCSB/CrowdSec)
if ! lsof -ti :8891 -sTCP:LISTEN >/dev/null 2>&1; then
  nohup python3 tools/chirps_proxy.py > /tmp/chirps_proxy.log 2>&1 &
  echo "==> بروكسي CHIRPS يعمل على :8891"
fi
echo "==> انتظار الجاهزية..."
for i in $(seq 1 30); do
  if curl -s -o /dev/null http://localhost:8080/api/v1/health 2>/dev/null; then break; fi
  sleep 2
done
# إعادة تشغيل الواجهة دائماً: خادم قديم قد يقدم بناءً ميتاً (صفحة بيضاء)
echo "==> إعادة تشغيل الواجهة ببناء حديث..."
cd apps/web
for pid in $(lsof -ti :3100 -sTCP:LISTEN 2>/dev/null); do kill -9 $pid 2>/dev/null; done
sleep 2
nohup npx next start -p 3100 > /tmp/next.log 2>&1 &
sleep 6
cd ../..
echo "✓ جاهز: http://localhost:3100"
open http://localhost:3100 2>/dev/null || true
