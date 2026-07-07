"""Read configured RSS feeds and print keyword-matched entries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import feedparser
import yaml

BASE_DIR = Path(__file__).resolve().parent
SOURCES_FILE = BASE_DIR / "sources.yaml"
KEYWORDS_FILE = BASE_DIR / "keywords.yaml"
KEYWORD_GROUPS = ("high_priority", "medium_priority", "korean")


def load_sources(path: Path = SOURCES_FILE) -> list[dict[str, str]]:
    """Load RSS source definitions from a YAML file."""
    with path.open("r", encoding="utf-8") as file:
        data: dict[str, Any] = yaml.safe_load(file) or {}

    rss_sources = data.get("rss", [])
    if not isinstance(rss_sources, list):
        raise ValueError("sources.yaml must contain an 'rss' list")

    return rss_sources


def load_keywords(path: Path = KEYWORDS_FILE) -> list[str]:
    """Load and flatten configured keyword groups from a YAML file."""
    with path.open("r", encoding="utf-8") as file:
        data: dict[str, Any] = yaml.safe_load(file) or {}

    keywords: list[str] = []
    for group in KEYWORD_GROUPS:
        group_keywords = data.get(group, [])
        if not isinstance(group_keywords, list):
            raise ValueError(f"keywords.yaml '{group}' must be a list")
        keywords.extend(str(keyword) for keyword in group_keywords)

    return keywords


def find_matched_keywords(entry: Any, keywords: list[str]) -> list[str]:
    """Return keywords found in an RSS entry's title, summary, or link."""
    searchable_text = " ".join(
        [
            entry.get("title", ""),
            entry.get("summary", ""),
            entry.get("link", ""),
        ]
    ).lower()

    return [keyword for keyword in keywords if keyword.lower() in searchable_text]


def process_source(
    source: dict[str, str], keywords: list[str], seen_links: set[str]
) -> tuple[int, int]:
    """Print matched RSS entries for one source and return checked/matched counts."""
    name = source.get("name", "Unnamed source")
    url = source.get("url")

    if not url:
        print(f"\nSource: {name}")
        print("  Error: missing RSS url")
        return 0, 0

    checked_entries = 0
    matched_entries = 0

    try:
        feed = feedparser.parse(url)
        if getattr(feed, "bozo", False):
            raise ValueError(getattr(feed, "bozo_exception", "failed to parse RSS feed"))

        for entry in feed.entries:
            checked_entries += 1
            link = entry.get("link", "")
            if link in seen_links:
                continue

            matched_keywords = find_matched_keywords(entry, keywords)
            if not matched_keywords:
                continue

            seen_links.add(link)
            matched_entries += 1
            title = entry.get("title", "No title")

            print(f"\nSource: {name}")
            print(f"Title: {title}")
            print(f"Link: {link or 'No link'}")
            print(f"Matched keywords: {', '.join(matched_keywords)}")

        return checked_entries, matched_entries
    except Exception as exc:
        print(f"\nSource: {name}")
        print(f"  Error reading RSS source: {exc}")
        return checked_entries, matched_entries


def main() -> None:
    """Read RSS sources and print keyword-matched news entries."""
    sources = load_sources()
    keywords = load_keywords()
    seen_links: set[str] = set()
    total_checked_entries = 0
    total_matched_entries = 0

    for source in sources:
        checked_entries, matched_entries = process_source(source, keywords, seen_links)
        total_checked_entries += checked_entries
        total_matched_entries += matched_entries

    print("\nSummary")
    print(f"RSS sources read: {len(sources)}")
    print(f"Entries checked: {total_checked_entries}")
    print(f"Entries matched: {total_matched_entries}")


if __name__ == "__main__":
    main()
