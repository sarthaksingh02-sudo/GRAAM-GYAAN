import sys
import urllib.request
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "http://127.0.0.1:8000"

endpoints = [
    ("/", "PWA HTML Home"),
    ("/manifest.json", "PWA Web Manifest"),
    ("/sw.js", "Service Worker"),
    ("/style.css", "CSS Stylesheet"),
    ("/app.js", "Frontend Logic"),
    ("/api/home-tiles?lang=hi-IN", "Home Tiles (Hindi)"),
    ("/api/home-tiles?lang=en-IN", "Home Tiles (English)"),
    ("/api/schemes?lang=hi-IN", "Schemes Evaluator"),
    ("/api/projects?lang=hi-IN", "Regional Projects"),
    ("/api/guides", "Need Guides"),
    ("/api/export/pdf?lang=hi-IN", "Hindi PDF Export"),
    ("/api/export/text?lang=hi-IN", "Plain Text Export"),
    ("/api/export/json?lang=hi-IN", "JSON Export"),
]

print("=" * 65)
print("LIVE GRAAM-GYAAN ENDPOINT HEALTH CHECK")
print("=" * 65)

all_passed = True
for path, desc in endpoints:
    url = BASE_URL + path
    try:
        req = urllib.request.Request(url, headers={"X-User-Id": "1"})
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            data_len = len(resp.read())
            print(f" [PASS] {status} | {desc:<25} | {path:<30} ({data_len} bytes)")
    except Exception as e:
        print(f" [FAIL] ERR | {desc:<25} | {path:<30} -> {e}")
        all_passed = False

print("=" * 65)
if all_passed:
    print("ALL LIVE ENDPOINTS HEALTHY & RESPONDING 200 OK!")
else:
    print("SOME ENDPOINTS FAILED")
print("=" * 65)
