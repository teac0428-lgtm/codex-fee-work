"""Read configured RSS feeds and print recent entries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import feedparser
import yaml

SOURCES_FILE = Path(__file__).with_name("sources.yaml")
MAX_ENTRIES_PER_SOURCE = 5


def load_sources(path: Path = SOURCES_FILE) -> list[dict[str, str]]:
    """Load RSS source definitions from a YAML file."""
    with path.open("r", encoding="utf-8") as file:
        data: dict[str, Any] = yaml.safe_load(file) or {}

    rss_sources = data.get("rss", [])
    if not isinstance(rss_sources, list):
        raise ValueError("sources.yaml must contain an 'rss' list")

    return rss_sources


def print_latest_entries(source: dict[str, str]) -> int:
    """Print the latest RSS entries for one source and return entry count."""
    name = source.get("name", "Unnamed source")
    url = source.get("url")

    print(f"\nSource: {name}")

    if not url:
        print("  Error: missing RSS url")
        return 0

    try:
        feed = feedparser.parse(url)
        if getattr(feed, "bozo", False):
            raise ValueError(getattr(feed, "bozo_exception", "failed to parse RSS feed"))

        entries = list(feed.entries[:MAX_ENTRIES_PER_SOURCE])
        for entry in entries:
            title = entry.get("title", "No title")
            link = entry.get("link", "No link")
            print(f"  - {title}")
            print(f"    {link}")

        if not entries:
            print("  No entries found.")

        return len(entries)
    except Exception as exc:
        print(f"  Error reading RSS source: {exc}")
        return 0


def main() -> None:
    """Read RSS sources and print recent news titles and links."""
    sources = load_sources()
    total_entries = 0

    for source in sources:
        total_entries += print_latest_entries(source)

    print("\nSummary")
    print(f"RSS sources checked: {len(sources)}")
    print(f"Total entries printed: {total_entries}")


if __name__ == "__main__":
    main()
