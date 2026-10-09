"""Location-scoped public district feeds; timestamps describe checks, not publication."""
import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

POOL = ThreadPoolExecutor(max_workers=3)
LOCK = threading.Lock()
RUNNING = set()
TTL = 3600

def key_for(region):
    return hashlib.sha256(json.dumps({k: str(region.get(k) or "").strip().casefold() for k in ("state", "district", "block", "panchayat", "village")}, sort_keys=True).encode()).hexdigest()

def cache_path(region):
    root = Path(os.getenv("DATA_DIR", ".cache")) / "public-knowledge"
    root.mkdir(parents=True, exist_ok=True)
    return root / (key_for(region) + ".json")

def official(url):
    p = urlparse(url)
    return p.scheme == "https" and bool(p.hostname) and p.port in (None, 443) and p.hostname.endswith((".gov.in", ".nic.in"))

def page(url):
    if not official(url):
        raise ValueError("Only official HTTPS sources are supported")
    with httpx.Client(timeout=8, follow_redirects=False, headers={"User-Agent": "GRAAM-GYAAN/0.6 public-information-reader"}) as client:
        for _ in range(4):
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    if not official(url):
                        raise ValueError("Non-government redirect rejected")
                    continue
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 2_000_000:
                        raise ValueError("Source page too large")
                return url, BeautifulSoup(bytes(body), "html.parser")
    raise ValueError("Too many redirects")

def collect(region):
    district = str(region.get("district") or "").strip()
    slug = re.sub(r"[^a-z0-9]", "", district.casefold())
    if not slug or not region.get("state"):
        raise ValueError("Save a district and state, using the English district name for source discovery.")
    root = None
    for host in (f"https://{slug}.nic.in/", f"https://{slug}.gov.in/"):
        try:
            url, soup = page(host)
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            if district.casefold() in title.casefold() and str(region["state"]).casefold() in soup.get_text(" ", strip=True).casefold():
                root = (url, soup)
                break
        except (httpx.HTTPError, ValueError):
            continue
    if root is None:
        raise ValueError("Could not verify an official district website. Use the official portals below; no local works have been inferred.")
    root_url, soup = root
    # Prefer the site's own English link, when supplied, for matching and reading.
    english = next((urljoin(root_url, a["href"]) for a in soup.select("a[href]") if a.get_text(strip=True).lower() == "english" and official(urljoin(root_url,a["href"]))), None)
    if english:
        try:
            root_url, soup = page(english)
        except (httpx.HTTPError, ValueError):
            pass
    pages = [(root_url, soup)]
    targets = []
    for a in soup.select("a[href]"):
        href = urljoin(root_url, a["href"])
        if urlparse(href).hostname == urlparse(root_url).hostname and re.search(r"/(schemes|notice_category/tenders|notice_category/announcements)/?$", href):
            if href not in targets:
                targets.append(href)
    errors = []
    for href in targets[:3]:
        try:
            pages.append(page(href))
        except (httpx.HTTPError, ValueError):
            errors.append("A district listing could not be refreshed.")
    schemes, projects, seen = [], [], set()
    for page_url, doc in pages:
        main = doc.select_one("main") or doc.select_one("#SkipContent") or doc
        for a in main.select("a[href]"):
            title = " ".join((a.get("aria-label") or a.get_text(" ", strip=True)).split()).removesuffix(", View Details")
            href = urljoin(page_url, a["href"])
            if href in seen or len(title) < 18 or not official(href):
                continue
            if urlparse(href).hostname != urlparse(root_url).hostname:
                continue
            kind = "scheme" if "/scheme/" in href else "notice"
            if kind != "scheme" and not re.search(r"project|construction|road|water supply|development|tender|acquisition|action plan|परियोजना|निर्माण|विकास|निविदा", title, re.I):
                continue
            if re.search(r"^[\s]*((ongoing|completed|all) projects|tenders|development department)$", title, re.I):
                continue
            seen.add(href)
            parent = a.find_parent("tr") or a.parent
            full_text = " ".join(parent.get_text(" ", strip=True).split())
            excerpt = full_text[:650]
            dates = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", full_text)
            item = {"id": hashlib.sha256(href.encode()).hexdigest()[:16], "title": title[:350], "url": href, "excerpt": excerpt, "type": kind, "scope": "district", "district": district, "state": region.get("state"), "publishedDate": dates[0] if dates else None, "status": "Official listing; implementation status not verified"}
            (schemes if kind == "scheme" else projects).append(item)
    return {"schemes": schemes[:30], "projects": projects[:40], "sourceUrl": root_url, "errors": errors, "coverage": "District website listings. Village-specific works are not confirmed by this feed."}

def refresh(region):
    key = key_for(region)
    path = cache_path(region)
    now = datetime.now(timezone.utc).isoformat()
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    try:
        result = {**collect(region), "checkedAt": now, "attemptedAt": now, "status": "available"}
    except Exception as exc:
        result = {**old, "attemptedAt": now, "status": "stale" if old.get("checkedAt") else "unavailable", "errors": [str(exc)]}
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    finally:
        with LOCK:
            RUNNING.discard(key)
    return result

def feed(region, force=False):
    path = cache_path(region)
    cached = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    when = cached.get("attemptedAt")
    stale = not when or (datetime.now(timezone.utc) - datetime.fromisoformat(when)).total_seconds() > TTL
    key = key_for(region)
    with LOCK:
        if (force or stale) and key not in RUNNING:
            RUNNING.add(key)
            POOL.submit(refresh, dict(region))
        running = key in RUNNING
    return {"schemes": [], "projects": [], **cached, "region": {k:region.get(k) for k in ("village","panchayat","block","tehsil","district","state","village_code")}, "refreshing": running, "status": cached.get("status", "refreshing" if running else "unavailable"), "portals": [{"title":"myScheme — official scheme discovery", "url":"https://www.myscheme.gov.in/"}, {"title":"eGramSwaraj — select your state, district, block and panchayat for works", "url":"https://egramswaraj.gov.in/ongoingActivityReport.do"}], "freshnessNote":"Automatically rechecked when viewed after one hour. Checked time is not publication time or a guarantee that the authority has updated its records."}
