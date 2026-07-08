"""Read configured RSS feeds and send score-filtered keyword alerts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import feedparser
import yaml

from send_telegram import send_message

BASE_DIR = Path(__file__).resolve().parent
SOURCES_FILE = BASE_DIR / "sources.yaml"
KEYWORDS_FILE = BASE_DIR / "keywords.yaml"
SENT_TODAY_FILE = BASE_DIR / "sent_today.json"
KST_DATE_FILE = BASE_DIR / "date.txt"
POSITIVE_KEYWORD_GROUPS = ("high_priority", "medium_priority", "korean")
KEYWORD_GROUPS = (*POSITIVE_KEYWORD_GROUPS, "negative_keywords")
MAX_SEND_PER_RUN = 10
MIN_SCORE = 5
TITLE_WEIGHT = 2
HIGH_PRIORITY_SCORE = 5
MEDIUM_PRIORITY_SCORE = 3
KOREAN_SCORE = 4
NEGATIVE_KEYWORD_SCORE = -5
KEYWORD_SCORES = {
    "high_priority": HIGH_PRIORITY_SCORE,
    "medium_priority": MEDIUM_PRIORITY_SCORE,
    "korean": KOREAN_SCORE,
    "negative_keywords": NEGATIVE_KEYWORD_SCORE,
}


def get_kst_date() -> str:
    """Return today's date in KST as YYYY-MM-DD."""
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")


def write_kst_date(path: Path = KST_DATE_FILE) -> None:
    """Write today's KST date to a text file."""
    path.write_text(get_kst_date(), encoding="utf-8")


def normalize_title(title: str | None) -> str:
    """Normalize a title for stable daily duplicate fingerprints."""
    normalized = title or ""
    normalized = normalized.lower()
    normalized = re.sub(r"\s+-\s+[^-]+$", "", normalized)
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def make_fingerprint(title: str) -> str:
    """Build a SHA-256 fingerprint from a normalized title."""
    normalized_title = normalize_title(title)
    return hashlib.sha256(normalized_title.encode("utf-8")).hexdigest()


def load_sent_today(path: Path = SENT_TODAY_FILE, today: str | None = None) -> set[str]:
    """Load today's sent fingerprints from cache state."""
    sent_date = today or get_kst_date()
    if not path.exists():
        return set()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Warning: failed to parse sent_today.json; resetting cache: {exc}")
        return set()

    if not isinstance(data, dict):
        print("Warning: sent_today.json is not an object; resetting cache.")
        return set()

    if data.get("date") != sent_date:
        return set()

    items = data.get("items", [])
    if not isinstance(items, list):
        print("Warning: sent_today.json items is not a list; resetting cache.")
        return set()

    return {str(item) for item in items}


def save_sent_today(
    items: set[str], path: Path = SENT_TODAY_FILE, today: str | None = None
) -> None:
    """Save today's sent fingerprints for GitHub Actions cache."""
    sent_date = today or get_kst_date()
    data = {
        "date": sent_date,
        "items": sorted(items),
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_sources(path: Path = SOURCES_FILE) -> list[dict[str, str]]:
    """Load RSS source definitions from a YAML file."""
    with path.open("r", encoding="utf-8") as file:
        data: dict[str, Any] = yaml.safe_load(file) or {}

    rss_sources = data.get("rss", [])
    if not isinstance(rss_sources, list):
        raise ValueError("sources.yaml must contain an 'rss' list")

    return rss_sources


def load_keywords(path: Path = KEYWORDS_FILE) -> dict[str, list[str]]:
    """Load configured keyword groups from a YAML file."""
    with path.open("r", encoding="utf-8") as file:
        data: dict[str, Any] = yaml.safe_load(file) or {}

    keywords: dict[str, list[str]] = {}
    for group in KEYWORD_GROUPS:
        group_keywords = data.get(group, [])
        if not isinstance(group_keywords, list):
            raise ValueError(f"keywords.yaml '{group}' must be a list")
        keywords[group] = [str(keyword) for keyword in group_keywords]

    return keywords


def calculate_score(
    title: str, summary: str, keywords: dict[str, list[str]]
) -> tuple[int, list[str], list[str]]:
    """Calculate a keyword score from an RSS entry title and summary."""
    title_text = title.lower()
    summary_text = summary.lower()
    score = 0
    matched_keywords: list[str] = []
    negative_matches: list[str] = []

    for group, group_keywords in keywords.items():
        base_score = KEYWORD_SCORES[group]
        is_negative_group = group == "negative_keywords"
        for keyword in group_keywords:
            keyword_text = keyword.lower()
            title_matched = keyword_text in title_text
            summary_matched = keyword_text in summary_text

            if title_matched:
                score += base_score * TITLE_WEIGHT
            if summary_matched:
                score += base_score

            if title_matched or summary_matched:
                if is_negative_group:
                    if keyword not in negative_matches:
                        negative_matches.append(keyword)
                elif keyword not in matched_keywords:
                    matched_keywords.append(keyword)

    return score, matched_keywords, negative_matches


def build_telegram_message(
    score: int, source_name: str, matched_keywords: list[str], title: str, link: str
) -> str:
    """Build a Telegram alert message for a scored RSS entry."""
    return (
        "[Research Alert]\n"
        f"Score: {score}\n"
        f"Source: {source_name}\n"
        f"Matched: {', '.join(matched_keywords)}\n"
        f"Title: {title}\n"
        f"Link: {link}"
    )


def process_source(
    source: dict[str, str],
    keywords: dict[str, list[str]],
    seen_links: set[str],
    sent_today: set[str],
    sends_remaining: int,
) -> tuple[int, int, int, int, int, int, int, int]:
    """Print and send scored RSS entries for one source and return counts."""
    name = source.get("name", "Unnamed source")
    url = source.get("url")

    if not url:
        print(f"\nSource: {name}")
        print("  Error: missing RSS url")
        return 0, 0, 0, 0, 0, 0, 0, 0

    checked_entries = 0
    matched_entries = 0
    send_successes = 0
    send_failures = 0
    duplicate_link_count = 0
    rejected_by_score = 0
    negative_keyword_hits = 0
    daily_duplicate_count = 0

    try:
        feed = feedparser.parse(url)
        if getattr(feed, "bozo", False):
            raise ValueError(getattr(feed, "bozo_exception", "failed to parse RSS feed"))

        for entry in feed.entries:
            checked_entries += 1
            link = entry.get("link", "")
            if not link:
                print(f"\nSource: {name}")
                print("  Entry has no link; continuing with title/summary scoring.")
            elif link in seen_links:
                duplicate_link_count += 1
                continue
            else:
                seen_links.add(link)

            title = entry.get("title", "No title")
            summary = entry.get("summary", "")
            score, matched_keywords, negative_matches = calculate_score(
                title, summary, keywords
            )

            if negative_matches:
                negative_keyword_hits += 1
                print(
                    f"Negative keywords matched for '{title}': "
                    f"{', '.join(negative_matches)}"
                )

            if not matched_keywords:
                continue

            matched_entries += 1
            print(f"\nSource: {name}")
            print(f"Score: {score}")
            print(f"Title: {title}")
            print(f"Link: {link or 'No link'}")
            print(f"Matched keywords: {', '.join(matched_keywords)}")
            if negative_matches:
                print(f"Negative keywords: {', '.join(negative_matches)}")

            if score < MIN_SCORE:
                rejected_by_score += 1
                print(f"Rejected by score: {score} < {MIN_SCORE}")
                continue

            fingerprint = make_fingerprint(title)
            if fingerprint in sent_today:
                daily_duplicate_count += 1
                print("Daily duplicate skipped: already sent today.")
                continue

            if send_successes + send_failures >= sends_remaining:
                print("Telegram send skipped: MAX_SEND_PER_RUN limit reached")
                continue

            message = build_telegram_message(score, name, matched_keywords, title, link)
            if send_message(message):
                sent_today.add(fingerprint)
                send_successes += 1
                print("Telegram send: success")
            else:
                send_failures += 1
                print("Telegram send: failed")

        return (
            checked_entries,
            matched_entries,
            send_successes,
            send_failures,
            duplicate_link_count,
            rejected_by_score,
            negative_keyword_hits,
            daily_duplicate_count,
        )
    except Exception as exc:
        print(f"\nSource: {name}")
        print(f"  Error reading RSS source: {exc}")
        return (
            checked_entries,
            matched_entries,
            send_successes,
            send_failures,
            duplicate_link_count,
            rejected_by_score,
            negative_keyword_hits,
            daily_duplicate_count,
        )


def run_collector() -> None:
    """Read RSS sources and send score-filtered Telegram alerts."""
    today = get_kst_date()
    sources = load_sources()
    keywords = load_keywords()
    seen_links: set[str] = set()
    sent_today = load_sent_today(today=today)
    total_checked_entries = 0
    total_matched_entries = 0
    total_send_successes = 0
    total_send_failures = 0
    total_duplicate_link_count = 0
    total_rejected_by_score = 0
    total_negative_keyword_hits = 0
    total_daily_duplicate_count = 0

    for source in sources:
        sends_remaining = MAX_SEND_PER_RUN - total_send_successes - total_send_failures
        (
            checked_entries,
            matched_entries,
            send_successes,
            send_failures,
            duplicate_link_count,
            rejected_by_score,
            negative_keyword_hits,
            daily_duplicate_count,
        ) = process_source(source, keywords, seen_links, sent_today, sends_remaining)
        total_checked_entries += checked_entries
        total_matched_entries += matched_entries
        total_send_successes += send_successes
        total_send_failures += send_failures
        total_duplicate_link_count += duplicate_link_count
        total_rejected_by_score += rejected_by_score
        total_negative_keyword_hits += negative_keyword_hits
        total_daily_duplicate_count += daily_duplicate_count

    save_sent_today(sent_today, today=today)

    print("\nSummary")
    print(f"RSS sources read: {len(sources)}")
    print(f"Raw entries checked: {total_checked_entries}")
    print(f"Duplicate links removed: {total_duplicate_link_count}")
    print(f"Matched keyword entries: {total_matched_entries}")
    print(f"Sent: {total_send_successes}")
    print(f"Telegram send failures: {total_send_failures}")
    print(f"Rejected by score: {total_rejected_by_score}")
    print(f"Negative keyword hits: {total_negative_keyword_hits}")
    print(f"Daily duplicates skipped: {total_daily_duplicate_count}")
    print(f"Sent today cache size: {len(sent_today)}")
    print(f"Sent today date: {today}")


def main() -> None:
    """Run the collector or write the current KST date for workflow cache keys."""
    parser = argparse.ArgumentParser(description="Research alert RSS collector")
    parser.add_argument(
        "--write-kst-date",
        action="store_true",
        help="Write the current KST date to date.txt and exit.",
    )
    args = parser.parse_args()

    if args.write_kst_date:
        write_kst_date()
        return

    run_collector()


if __name__ == "__main__":
    main()
