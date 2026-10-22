#!/usr/bin/env python3
"""بروكسي محلي لمضيف ماكنتوش يمرر طلبات CHIRPS فقط (عبر curl).

لماذا: UCSB يحظر بصمة TLS لطلبات بايثون (httpx/urllib) لدى CrowdSec بينما
curl نظيف. الخلفية (API داخل Docker) توجه طلباتها إلى
http://host.docker.internal:8891/chirps/<path> فيمررها هذا البروكسي إلى
https://data.chc.ucsb.edu/<path> عبر curl من شبكة المضيف.

التشغيل: يُشغَّل تلقائياً من start.sh — أو يدوياً:
    nohup python3 tools/chirps_proxy.py > /tmp/chirps_proxy.log 2>&1 &
"""
import http.server
import socketserver
import subprocess
import threading
import time

UPSTREAM = "https://data.chc.ucsb.edu"
ALLOWED_PREFIX = "/products/CHIRPS/"
PORT = 8891
UA = "raintracker-local/1.0 (personal rain viewer)"
_lock = threading.Lock()          # تسلسل الطلبات: لا دفعات إطلاقاً


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith("/chirps" + ALLOWED_PREFIX):
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"only /chirps/products/CHIRPS/* allowed")
            return
        upstream_url = UPSTREAM + self.path[len("/chirps"):]
        try:
            with _lock:
                p = subprocess.run(
                    ["curl", "-sS", "-m", "120", "-A", UA, "-w", "\n%{http_code}", upstream_url],
                    capture_output=True, timeout=150)
                time.sleep(1.0)          # فاصل إلزامي بين الطلبات upstream
            out = p.stdout
            body, _, code = out.rpartition(b"\n")
            status = int(code or 502)
            self.send_response(status)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self.send_response(502)
            self.end_headers()

    def log_message(self, *args):
        pass


socketserver.ThreadingTCPServer.allow_reuse_address = True
with socketserver.ThreadingTCPServer(("0.0.0.0", PORT), Handler) as srv:
    print(f"chirps proxy on :{PORT} -> {UPSTREAM} (via curl)", flush=True)
    srv.serve_forever()
