#!/usr/bin/env python3
"""Build a single combined Atom feed from per-subreddit top posts.

Reads config/subreddits.json (name, cadence: "daily"|"weekly", limit),
fetches Reddit's public, unauthenticated top/.rss endpoint per subreddit
(no API key needed — Reddit's official Data API is approval-gated and
was confirmed unobtainable; .rss survived the 2026-05-30 shutdown of the
unauthenticated .json endpoint), and writes a combined feed to docs/feed.xml
for GitHub Pages to serve.

Weekly-cadence subreddits are only fetched on WEEKLY_RUN_WEEKDAY (default
Monday) — not every day. Earlier design fetched them daily too, relying on
readers deduping by entry GUID to keep them feeling "weekly." That doesn't
hold up: r/<sub>/top/.rss?t=week is a rolling 7-day window, recalculated on
every request, and for anything with decent post volume the #1 post can
change value daily as new posts out-score the current leader — it only
looks stable for genuinely quiet subreddits. Fetching just once a week is
the only mechanism that actually guarantees "weekly" behavior regardless of
how active a given subreddit is.
"""
from __future__ import annotations

import datetime as dt
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
FEED_URL = "https://cyberwildcard.github.io/reddit-digest/feed.xml"

CADENCE_TO_TIMEFRAME = {"daily": "day", "weekly": "week"}
WEEKLY_RUN_WEEKDAY = 0  # Monday (datetime.weekday(): Monday=0 .. Sunday=6)

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
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def load_existing_entries_by_subreddit() -> dict[str, list[ET.Element]]:
    """Group entries in the currently-published feed by which subreddit they
    came from, so a skipped weekly subreddit's last-fetched post can be
    carried forward instead of vanishing from the feed on non-run days."""
    if not OUTPUT_PATH.exists():
        return {}
    root = ET.fromstring(OUTPUT_PATH.read_bytes())
    by_sub: dict[str, list[ET.Element]] = {}
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        category = entry.find(f"{{{ATOM_NS}}}category")
        label = category.get("term") if category is not None else None
        if label:
            by_sub.setdefault(label, []).append(entry)
    return by_sub


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text())
    existing_by_sub = load_existing_entries_by_subreddit()

    today_weekday = dt.datetime.now(dt.timezone.utc).weekday()
    is_weekly_run_day = today_weekday == WEEKLY_RUN_WEEKDAY

    all_entries: list[ET.Element] = []
    to_fetch = []
    for sub in config:
        cadence = sub.get("cadence", "daily")
        if cadence == "weekly" and not is_weekly_run_day:
            carried = existing_by_sub.get(sub["name"], [])
            if carried:
                print(f"r/{sub['name']} (weekly): carrying forward {len(carried)} from last run (not the weekly run day)")
                all_entries.extend(carried)
            else:
                print(f"r/{sub['name']} (weekly): nothing to carry forward yet, will fetch on the next weekly run day")
            continue
        to_fetch.append(sub)

    for i, sub in enumerate(to_fetch):
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
