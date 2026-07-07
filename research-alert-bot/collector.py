"""Read configured RSS feeds and print keyword-matched entries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import feedparser
import yaml

from send_telegram import send_message

BASE_DIR = Path(__file__).resolve().parent
SOURCES_FILE = BASE_DIR / "sources.yaml"
KEYWORDS_FILE = BASE_DIR / "keywords.yaml"
KEYWORD_GROUPS = ("high_priority", "medium_priority", "korean")
MAX_SEND_PER_RUN = 10


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


def build_telegram_message(
    source_name: str, matched_keywords: list[str], title: str, link: str
) -> str:
    """Build a Telegram alert message for a matched RSS entry."""
    return (
        "[Research Alert]\n"
        f"Source: {source_name}\n"
        f"Matched: {', '.join(matched_keywords)}\n"
        f"Title: {title}\n"
        f"Link: {link}"
    )


def process_source(
    source: dict[str, str],
    keywords: list[str],
    seen_links: set[str],
    sends_remaining: int,
) -> tuple[int, int, int, int]:
    """Print and send matched RSS entries for one source and return counts."""
    name = source.get("name", "Unnamed source")
    url = source.get("url")

    if not url:
        print(f"\nSource: {name}")
        print("  Error: missing RSS url")
        return 0, 0, 0, 0

    checked_entries = 0
    matched_entries = 0
    send_successes = 0
    send_failures = 0

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

            if send_successes + send_failures >= sends_remaining:
                print("Telegram send skipped: MAX_SEND_PER_RUN limit reached")
                continue

            message = build_telegram_message(name, matched_keywords, title, link)
            if send_message(message):
                send_successes += 1
                print("Telegram send: success")
            else:
                send_failures += 1
                print("Telegram send: failed")

        return checked_entries, matched_entries, send_successes, send_failures
    except Exception as exc:
        print(f"\nSource: {name}")
        print(f"  Error reading RSS source: {exc}")
        return checked_entries, matched_entries, send_successes, send_failures


def main() -> None:
    """Read RSS sources and print keyword-matched news entries."""
    sources = load_sources()
    keywords = load_keywords()
    seen_links: set[str] = set()
    total_checked_entries = 0
    total_matched_entries = 0
    total_send_successes = 0
    total_send_failures = 0

    for source in sources:
        sends_remaining = MAX_SEND_PER_RUN - total_send_successes - total_send_failures
        checked_entries, matched_entries, send_successes, send_failures = process_source(
            source, keywords, seen_links, sends_remaining
        )
        total_checked_entries += checked_entries
        total_matched_entries += matched_entries
        total_send_successes += send_successes
        total_send_failures += send_failures

    print("\nSummary")
    print(f"RSS sources read: {len(sources)}")
    print(f"Entries checked: {total_checked_entries}")
    print(f"Entries matched: {total_matched_entries}")
    print(f"Telegram send successes: {total_send_successes}")
    print(f"Telegram send failures: {total_send_failures}")


if __name__ == "__main__":
    main()
