#!/usr/bin/env python3
"""Build a single combined Atom feed from per-subreddit top posts.

Reads config/subreddits.json (name, cadence: "daily"|"weekly", limit),
fetches Reddit's public, unauthenticated top/.rss endpoint per subreddit
(no API key needed — Reddit's official Data API is approval-gated and
was confirmed unobtainable; .rss survived the 2026-05-30 shutdown of the
unauthenticated .json endpoint), and writes a combined feed to docs/feed.xml
for GitHub Pages to serve.

Deliberately stateless: readers (Feedly etc.) dedupe by entry <id>/GUID, so
weekly-cadence subreddits can be refetched every run without any local
"last shown" tracking — a post reappearing in the source feed every day
until it drops out of the week's top doesn't cause a reader to show it
more than once.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "subreddits.json"
OUTPUT_PATH = ROOT / "docs" / "feed.xml"

ATOM_NS = "http://www.w3.org/2005/Atom"
MEDIA_NS = "http://search.yahoo.com/mrss/"
# Reddit rate-limits unauthenticated requests aggressively (hit a 429 in
# testing after two back-to-back fetches) — a descriptive UA plus a fixed
# delay between requests avoids it in practice.
USER_AGENT = "reddit-digest/1.0 (personal single-user RSS aggregator; not for scraping at scale)"
REQUEST_DELAY_SECONDS = 3
# TODO: fill in the real GitHub Pages URL once the repo is created and Pages is enabled.
FEED_URL = "https://REPLACE-ME.github.io/reddit-digest/feed.xml"

CADENCE_TO_TIMEFRAME = {"daily": "day", "weekly": "week"}

ET.register_namespace("", ATOM_NS)
ET.register_namespace("media", MEDIA_NS)


def fetch_subreddit_entries(name: str, cadence: str, limit: int) -> list[ET.Element]:
    timeframe = CADENCE_TO_TIMEFRAME[cadence]
    url = f"https://www.reddit.com/r/{name}/top/.rss?t={timeframe}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    data = None
    for attempt in range(2):  # one retry — Reddit's 429s are common but short-lived
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                print(f"r/{name}: rate-limited, waiting 20s before retry", file=sys.stderr)
                time.sleep(20)
                continue
            print(f"WARNING: failed to fetch r/{name}: {e}", file=sys.stderr)
            return []
        except Exception as e:
            print(f"WARNING: failed to fetch r/{name}: {e}", file=sys.stderr)
            return []

    if data is None:
        return []

    root = ET.fromstring(data)
    return root.findall(f"{{{ATOM_NS}}}entry")


def build_combined_feed(entries: list[ET.Element]) -> ET.Element:
    feed = ET.Element(f"{{{ATOM_NS}}}feed")
    ET.SubElement(feed, f"{{{ATOM_NS}}}title").text = "Reddit Digest"
    ET.SubElement(feed, f"{{{ATOM_NS}}}id").text = FEED_URL
    ET.SubElement(feed, f"{{{ATOM_NS}}}link", href=FEED_URL, rel="self")
    ET.SubElement(feed, f"{{{ATOM_NS}}}updated").text = _now_iso()

    def sort_key(entry: ET.Element) -> str:
        updated = entry.find(f"{{{ATOM_NS}}}updated")
        return updated.text if updated is not None else ""

    for entry in sorted(entries, key=sort_key, reverse=True):
        feed.append(entry)

    return feed


def _now_iso() -> str:
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text())

    all_entries: list[ET.Element] = []
    for i, sub in enumerate(config):
        if i > 0:
            time.sleep(REQUEST_DELAY_SECONDS)
        name = sub["name"]
        cadence = sub.get("cadence", "daily")
        limit = sub.get("limit", 1)
        entries = fetch_subreddit_entries(name, cadence, limit)
        print(f"r/{name} ({cadence}): {len(entries)} entr{'y' if len(entries) == 1 else 'ies'}")
        all_entries.extend(entries)

    feed = build_combined_feed(all_entries)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(feed).write(OUTPUT_PATH, encoding="UTF-8", xml_declaration=True)
    print(f"Wrote {len(all_entries)} entries to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
