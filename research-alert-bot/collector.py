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
NOISE_KEYWORD_GROUPS = (
    "negative_keywords",
    "advertisement_noise",
    "market_noise",
    "ticker_noise",
)
KEYWORD_GROUPS = (*POSITIVE_KEYWORD_GROUPS, "industry_context", *NOISE_KEYWORD_GROUPS)
MAX_SEND_PER_RUN = 10
MAX_ALERTS = MAX_SEND_PER_RUN
MAX_ALERTS_PER_KEYWORD = 2
SEND_THRESHOLD = 15
MIN_SCORE = SEND_THRESHOLD
TITLE_WEIGHT = 2
SCORES = {
    "high_priority": 15,
    "medium_priority": 7,
    "korean": 10,
    "industry_context": 5,
    "ticker_noise": -8,
    "market_noise": -10,
    "advertisement_noise": -20,
    "negative_keywords": -10,
}
GROUP_PRIORITY = {
    "high_priority": 3,
    "korean": 2,
    "medium_priority": 1,
    "industry_context": 0,
}
INDUSTRY_CONTEXT_KEYWORDS = [
    "cloud contract",
    "GPU capacity",
    "data center",
    "datacenter",
    "capex",
    "backlog",
    "revenue backlog",
    "AI infrastructure",
    "AI infra",
    "GPU cloud",
    "Blackwell",
    "GB200",
    "GB300",
    "power capacity",
    "data center power",
    "power constraint",
    "lease agreement",
    "capacity expansion",
]
COREWEAVE_ALIAS = [
    "coreweave",
    "$crwv",
    "crwv stock",
    "crwv shares",
    "coreweave stock",
    "coreweave shares",
    "shares of coreweave",
]
COREWEAVE_GOOD_CONTEXT = [
    "cloud contract",
    "multi-year agreement",
    "GPU capacity",
    "data center",
    "datacenter",
    "data center expansion",
    "AI infrastructure",
    "AI infra",
    "capex",
    "revenue backlog",
    "backlog",
    "capacity sold out",
    "Nvidia GPU",
    "Blackwell",
    "GB200",
    "GB300",
    "Anthropic",
    "OpenAI",
    "Meta",
    "Microsoft",
    "power capacity",
    "lease agreement",
    "financing for data centers",
]
CANDIDATES: list[dict[str, Any]] = []
QUEUED_FINGERPRINTS: set[str] = set()


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


def split_keyword_tokens(keyword: Any) -> list[str]:
    """Split a raw keyword value into stripped pipe-delimited tokens."""
    return [token.strip() for token in str(keyword).split("|") if token.strip()]


def lower_tokens(keyword: Any) -> list[str]:
    """Return lower-case tokens for case-insensitive matching."""
    return [token.lower() for token in split_keyword_tokens(keyword)]


def keyword_matches(text: str, keyword: Any) -> bool:
    """Return whether any pipe-delimited keyword token exists in text."""
    return any(token in text for token in lower_tokens(keyword))


def find_keyword_matches(text: str, keywords: list[Any]) -> list[str]:
    """Return representative keywords that match a lower-case text blob."""
    matches: list[str] = []
    for raw_keyword in keywords:
        tokens = split_keyword_tokens(raw_keyword)
        if not tokens:
            continue
        if any(token.lower() in text for token in tokens):
            matches.append(tokens[0])
    return matches


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


def add_matched_keyword(
    matched_keywords: list[dict[str, str]], keyword: str, group: str
) -> None:
    """Append a matched keyword/group pair if it is not already present."""
    if {"keyword": keyword, "group": group} not in matched_keywords:
        matched_keywords.append({"keyword": keyword, "group": group})


def calculate_score(
    title: str, summary: str, keywords: dict[str, list[str]]
) -> tuple[int, list[dict[str, str]], list[str]]:
    """Calculate a keyword score from an RSS entry title and summary."""
    title_text = title.lower()
    summary_text = summary.lower()
    combined_text = f"{title} {summary}".lower()
    score = 0
    matched_keywords: list[dict[str, str]] = []
    excluded_keywords: list[str] = []
    coreweave_matched = any(alias in combined_text for alias in COREWEAVE_ALIAS)
    coreweave_good_context = any(
        context.lower() in combined_text for context in COREWEAVE_GOOD_CONTEXT
    )

    for group in POSITIVE_KEYWORD_GROUPS:
        base_score = SCORES[group]
        for raw_keyword in keywords.get(group, []):
            tokens = split_keyword_tokens(raw_keyword)
            if not tokens:
                continue

            keyword = tokens[0]
            title_matched = any(token.lower() in title_text for token in tokens)
            summary_matched = any(token.lower() in summary_text for token in tokens)

            if title_matched:
                score += base_score * TITLE_WEIGHT
            if summary_matched:
                score += base_score

            if title_matched or summary_matched:
                add_matched_keyword(matched_keywords, keyword, group)

    if coreweave_matched and not any(
        item["keyword"].lower() == "coreweave" for item in matched_keywords
    ):
        score += SCORES["high_priority"]
        add_matched_keyword(matched_keywords, "CoreWeave", "high_priority")

    industry_context_matches = find_keyword_matches(
        combined_text,
        [*INDUSTRY_CONTEXT_KEYWORDS, *keywords.get("industry_context", [])],
    )
    if industry_context_matches:
        score += SCORES["industry_context"]
        for keyword in industry_context_matches:
            add_matched_keyword(matched_keywords, keyword, "industry_context")

    for group in NOISE_KEYWORD_GROUPS:
        base_score = SCORES[group]
        for raw_keyword in keywords.get(group, []):
            tokens = split_keyword_tokens(raw_keyword)
            if not tokens:
                continue

            keyword = tokens[0]
            if not any(token.lower() in combined_text for token in tokens):
                continue

            if keyword not in excluded_keywords:
                excluded_keywords.append(f"{group}: {keyword}")

            if (
                coreweave_matched
                and coreweave_good_context
                and group in {"ticker_noise", "market_noise"}
            ):
                continue

            score += base_score

    return score, matched_keywords, excluded_keywords


def has_noise_group(excluded_keywords: list[str], group: str) -> bool:
    """Return whether a formatted noise match belongs to a group."""
    return any(keyword.startswith(f"{group}:") for keyword in excluded_keywords)


def has_coreweave_alias(text: str) -> bool:
    """Return whether CoreWeave or one of its ticker aliases appears."""
    return any(alias in text for alias in COREWEAVE_ALIAS)


def has_coreweave_good_context(text: str) -> bool:
    """Return whether CoreWeave appears with a strong industry context."""
    return any(context.lower() in text for context in COREWEAVE_GOOD_CONTEXT)


def has_industry_context(text: str, keywords: dict[str, list[str]]) -> bool:
    """Return whether text contains any configured or built-in industry context."""
    return bool(
        find_keyword_matches(
            text,
            [*INDUSTRY_CONTEXT_KEYWORDS, *keywords.get("industry_context", [])],
        )
    )


def build_skip_reason(
    title: str,
    summary: str,
    keywords: dict[str, list[str]],
    excluded_keywords: list[str],
) -> str | None:
    """Return a hard-filter skip reason, or None when the entry may pass."""
    text = f"{title} {summary}".lower()
    has_coreweave = has_coreweave_alias(text)
    has_good_context = has_coreweave_good_context(text)
    has_ticker_noise = has_noise_group(excluded_keywords, "ticker_noise")
    has_market_noise = has_noise_group(excluded_keywords, "market_noise")

    if has_noise_group(excluded_keywords, "advertisement_noise"):
        return "advertisement noise"
    if has_coreweave and (has_ticker_noise or has_market_noise) and not has_good_context:
        return "CoreWeave market noise"
    if has_ticker_noise and not has_industry_context(text, keywords):
        return "ticker-only noise"
    return None


def build_pass_reason(title: str, summary: str) -> str:
    """Return a concise reason for why an alert passed filtering."""
    text = f"{title} {summary}".lower()
    if has_coreweave_alias(text) and has_coreweave_good_context(text):
        return "CoreWeave + industry context"
    if any(context.lower() in text for context in INDUSTRY_CONTEXT_KEYWORDS):
        return "industry context"
    return "score threshold"


def get_primary_keyword(matched_keywords: list[dict[str, str]]) -> str:
    """Return the highest-priority matched representative keyword."""
    if not matched_keywords:
        return "unknown"

    return max(
        matched_keywords,
        key=lambda item: GROUP_PRIORITY.get(item.get("group", ""), 0),
    ).get("keyword", "unknown")


def get_primary_group_priority(matched_keywords: list[dict[str, str]]) -> int:
    """Return the highest group priority from matched keyword metadata."""
    if not matched_keywords:
        return 0

    return max(GROUP_PRIORITY.get(item.get("group", ""), 0) for item in matched_keywords)


def format_matched_keywords(matched_keywords: list[dict[str, str]]) -> str:
    """Format matched keyword metadata for logs and Telegram messages."""
    return ", ".join(
        f"{item['keyword']}({item['group']})" for item in matched_keywords
    )


def format_matched_groups(matched_keywords: list[dict[str, str]]) -> str:
    """Format unique matched groups in first-seen order."""
    groups: list[str] = []
    for item in matched_keywords:
        group = item["group"]
        if group not in groups:
            groups.append(group)
    return ", ".join(groups)


def format_noise(excluded_keywords: list[str]) -> str:
    """Format noise matches for messages and logs."""
    return ", ".join(excluded_keywords) if excluded_keywords else "none"


def build_telegram_message(
    score: int,
    source_name: str,
    matched_keywords: list[dict[str, str]],
    excluded_keywords: list[str],
    reason: str,
    title: str,
    link: str,
) -> str:
    """Build a Telegram alert message for a scored RSS entry."""
    return (
        "[Research Alert]\n"
        f"Score: {score}\n"
        f"Source: {source_name}\n"
        f"Matched: {format_matched_keywords(matched_keywords)}\n"
        f"Matched Groups: {format_matched_groups(matched_keywords)}\n"
        f"Noise: {format_noise(excluded_keywords)}\n"
        f"Reason: {reason}\n"
        f"Title: {title}\n"
        f"Link: {link}"
    )


def process_source(
    source: dict[str, str],
    keywords: dict[str, list[str]],
    seen_links: set[str],
    sent_today: set[str],
    sends_remaining: int,
    feed_index: int,
) -> tuple[int, int, int, int, int, int, int, int, int]:
    """Collect scored RSS candidates for one source and return counts."""
    name = source.get("name", "Unnamed source")
    url = source.get("url")

    if not url:
        print(f"\nSource: {name}")
        print("  Error: missing RSS url")
        return 0, 0, 0, 0, 0, 0, 0, 0, feed_index

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
            current_feed_index = feed_index
            feed_index += 1
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
            summary = (
                f"{entry.get('summary', '')} {entry.get('description', '')}".strip()
            )
            score, matched_keywords, excluded_keywords = calculate_score(
                title, summary, keywords
            )
            skip_reason = build_skip_reason(title, summary, keywords, excluded_keywords)

            if excluded_keywords:
                negative_keyword_hits += 1
                print(
                    f"Negative keywords matched for '{title}': "
                    f"{', '.join(excluded_keywords)}"
                )

            if skip_reason:
                rejected_by_score += 1
                print(f"[SKIP] {skip_reason}: {title}")
                continue

            if not matched_keywords:
                continue

            matched_entries += 1
            print(f"\nSource: {name}")
            print(f"Score: {score}")
            print(f"Title: {title}")
            print(f"Link: {link or 'No link'}")
            print(f"Matched keywords: {format_matched_keywords(matched_keywords)}")
            if excluded_keywords:
                print(f"Negative keywords: {', '.join(excluded_keywords)}")

            if score < MIN_SCORE:
                rejected_by_score += 1
                print(f"Rejected by score: {score} < {MIN_SCORE}")
                continue

            fingerprint = make_fingerprint(title)
            if fingerprint in sent_today or fingerprint in QUEUED_FINGERPRINTS:
                daily_duplicate_count += 1
                print("Daily duplicate skipped: already sent today.")
                continue

            QUEUED_FINGERPRINTS.add(fingerprint)
            CANDIDATES.append(
                {
                    "feed_index": current_feed_index,
                    "fingerprint": fingerprint,
                    "link": link,
                    "matched_keywords": matched_keywords,
                    "excluded_keywords": excluded_keywords,
                    "primary_group_priority": get_primary_group_priority(matched_keywords),
                    "primary_keyword": get_primary_keyword(matched_keywords),
                    "reason": build_pass_reason(title, summary),
                    "score": score,
                    "source_name": name,
                    "title": title,
                }
            )

        return (
            checked_entries,
            matched_entries,
            send_successes,
            send_failures,
            duplicate_link_count,
            rejected_by_score,
            negative_keyword_hits,
            daily_duplicate_count,
            feed_index,
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
            feed_index,
        )


def send_candidates(candidates: list[dict[str, Any]], sent_today: set[str]) -> tuple[int, int, int]:
    """Send sorted alert candidates with global and per-keyword limits."""
    sent_count = 0
    send_failures = 0
    skipped_by_keyword_limit = 0
    keyword_counts: dict[str, int] = {}

    candidates.sort(
        key=lambda item: (
            -item["score"],
            -item["primary_group_priority"],
            item["feed_index"],
        )
    )

    for candidate in candidates:
        if sent_count >= MAX_ALERTS:
            break

        primary_keyword = candidate["primary_keyword"]
        if keyword_counts.get(primary_keyword, 0) >= MAX_ALERTS_PER_KEYWORD:
            skipped_by_keyword_limit += 1
            print(
                "Skipped by per-keyword limit: "
                f"primary_keyword={primary_keyword}, title={candidate['title']}"
            )
            continue

        message = build_telegram_message(
            candidate["score"],
            candidate["source_name"],
            candidate["matched_keywords"],
            candidate["excluded_keywords"],
            candidate["reason"],
            candidate["title"],
            candidate["link"],
        )
        if send_message(message):
            sent_count += 1
            keyword_counts[primary_keyword] = keyword_counts.get(primary_keyword, 0) + 1
            sent_today.add(candidate["fingerprint"])
            print(
                "Sent alert: "
                f"score={candidate['score']}, "
                f"primary_keyword={primary_keyword}, "
                f"group_priority={candidate['primary_group_priority']}, "
                f"title={candidate['title']}"
            )
        else:
            send_failures += 1
            print("Telegram send: failed")

    return sent_count, send_failures, skipped_by_keyword_limit


def run_collector() -> None:
    """Read RSS sources and send score-filtered Telegram alerts."""
    today = get_kst_date()
    sources = load_sources()
    keywords = load_keywords()
    seen_links: set[str] = set()
    sent_today = load_sent_today(today=today)
    CANDIDATES.clear()
    QUEUED_FINGERPRINTS.clear()
    total_checked_entries = 0
    total_matched_entries = 0
    total_duplicate_link_count = 0
    total_rejected_by_score = 0
    total_negative_keyword_hits = 0
    total_daily_duplicate_count = 0
    feed_index = 0

    for source in sources:
        sends_remaining = MAX_ALERTS
        (
            checked_entries,
            matched_entries,
            _send_successes,
            _send_failures,
            duplicate_link_count,
            rejected_by_score,
            negative_keyword_hits,
            daily_duplicate_count,
            feed_index,
        ) = process_source(source, keywords, seen_links, sent_today, sends_remaining, feed_index)
        total_checked_entries += checked_entries
        total_matched_entries += matched_entries
        total_duplicate_link_count += duplicate_link_count
        total_rejected_by_score += rejected_by_score
        total_negative_keyword_hits += negative_keyword_hits
        total_daily_duplicate_count += daily_duplicate_count

    sent_alerts, send_failures, skipped_by_keyword_limit = send_candidates(
        CANDIDATES, sent_today
    )
    save_sent_today(sent_today, today=today)

    print("\nSummary")
    print(f"RSS sources read: {len(sources)}")
    print(f"Raw entries checked: {total_checked_entries}")
    print(f"Duplicate links removed: {total_duplicate_link_count}")
    print(f"Matched keyword entries: {total_matched_entries}")
    print(f"Candidates above min score: {len(CANDIDATES)}")
    print(f"Sent alerts: {sent_alerts}")
    print(f"Telegram send failures: {send_failures}")
    print(f"Skipped by per-keyword limit: {skipped_by_keyword_limit}")
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
