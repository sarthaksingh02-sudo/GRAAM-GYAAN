#!/usr/bin/env python3
"""
scripts/scrape_sources.py — Scraper and snapshot generator for official portal sources.

Reads scrape targets exclusively from config/sources.yaml.
Outputs dated snapshots to data/real/snapshots/ with source_url and verified_date.
No hardcoded URLs in script; all targets come from configuration.
"""

import argparse
import datetime
import json
import logging
import os
import sys
from pathlib import Path
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("scrape_sources")

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCES_CFG_PATH = BASE_DIR / "config" / "sources.yaml"
SNAPSHOTS_DIR = BASE_DIR / "data" / "real" / "snapshots"


def load_sources_config() -> list[dict]:
    if not SOURCES_CFG_PATH.exists():
        log.error("Sources config missing: %s", SOURCES_CFG_PATH)
        return []
    try:
        with open(SOURCES_CFG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data.get("sources", []) if isinstance(data, dict) else []
    except Exception as e:
        log.error("Error reading %s: %s", SOURCES_CFG_PATH, e)
        return []


def create_snapshot_for_source(src: dict, dry_run: bool = False, fetch: bool = False) -> Path | None:
    src_id = src.get("id", "source")
    source_url = src.get("url", "")
    target_file = src.get("target_file", "")
    verified_date = src.get("verified_date") or datetime.date.today().isoformat()
    now_date = datetime.date.today().isoformat()

    snapshot_filename = f"{src_id}_{now_date}.json"
    snapshot_path = SNAPSHOTS_DIR / snapshot_filename

    payload = {
        "source_id": src_id,
        "name": src.get("name"),
        "source_url": source_url,
        "verified_date": verified_date,
        "snapshot_date": now_date,
        "category": src.get("category"),
        "target_file": target_file,
        "status": "configured_not_verified",
        "selectors": src.get("selectors", {}),
    }

    if dry_run:
        log.info("[DRY-RUN] Would create snapshot at %s for %s (%s)", snapshot_path.name, src_id, source_url)
        return snapshot_path

    if fetch:
        import httpx
        import hashlib
        response = httpx.get(source_url, timeout=30, follow_redirects=True)
        response.raise_for_status()
        payload["status"] = "fetched_requires_review"
        payload["http_status"] = response.status_code
        payload["content_sha256"] = hashlib.sha256(response.content).hexdigest()
        payload["content"] = response.text
        # Fetching a webpage never verifies the rules or changes their verification date.
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Created snapshot: %s -> %s", src_id, snapshot_path.name)
    return snapshot_path


def main():
    parser = argparse.ArgumentParser(description="GRAAM-GYAAN Official Sources Scraper & Snapshot Generator")
    parser.add_argument("--source", type=str, help="Specific source ID to snapshot")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry run without writing files")
    parser.add_argument("--fetch", action="store_true", help="Fetch source pages for manual review; never automatically verify scheme rules")
    args = parser.parse_args()

    sources = load_sources_config()
    if not sources:
        log.error("No sources found in config/sources.yaml")
        return 1

    count = 0
    for src in sources:
        if args.source and src.get("id") != args.source:
            continue
        create_snapshot_for_source(src, dry_run=args.dry_run, fetch=args.fetch)
        count += 1

    log.info("Finished processing %d snapshot(s).", count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
