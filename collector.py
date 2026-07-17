"""Collect Google News RSS entries and send K-beauty industry alerts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import feedparser
import yaml

from send_telegram import send_message

BASE_DIR = Path(__file__).resolve().parent
SOURCES_FILE = BASE_DIR / "sources.yaml"
KEYWORDS_FILE = BASE_DIR / "keywords.yaml"
STATE_FILE = BASE_DIR / "state" / "k_beauty_sent_today.json"
DEFAULT_THRESHOLD = 15
DEFAULT_MAX_SEND_PER_RUN = 10


@dataclass
class Evaluation:
    """Filtering and scoring result for one RSS entry."""

    score: int = 0
    send: bool = False
    excluded: bool = False
    exclusion_reason: str = ""
    matched_terms: dict[str, list[str]] = field(default_factory=dict)
    matched_entities: list[str] = field(default_factory=list)
    evidence_groups: list[str] = field(default_factory=list)
    noise_groups: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def load_sources(path: Path = SOURCES_FILE) -> list[dict[str, str]]:
    """Load RSS source definitions from a YAML file."""
    with path.open("r", encoding="utf-8") as file:
        data: dict[str, Any] = yaml.safe_load(file) or {}

    rss_sources = data.get("rss", [])
    if not isinstance(rss_sources, list):
        raise ValueError("sources.yaml must contain an 'rss' list")

    return rss_sources


def load_keyword_config(path: Path = KEYWORDS_FILE) -> dict[str, Any]:
    """Load clustered keyword and scoring configuration."""
    with path.open("r", encoding="utf-8") as file:
        data: dict[str, Any] = yaml.safe_load(file) or {}

    return data


def entry_text(entry: Any) -> str:
    """Build keyword matching text from the original entry fields."""
    return " ".join(
        [
            entry.get("title", ""),
            entry.get("summary", ""),
            entry.get("description", ""),
            entry.get("link", ""),
        ]
    ).lower()


def normalize_for_fingerprint(value: str) -> str:
    """Normalize text only for duplicate fingerprints, not keyword matching."""
    return re.sub(r"[^0-9a-z가-힣]+", "", value.lower())


def entry_fingerprint(entry: Any) -> str:
    """Return a stable duplicate fingerprint from link and normalized title."""
    link = entry.get("link", "")
    title = normalize_for_fingerprint(entry.get("title", ""))
    fingerprint_source = f"{link}|{title}"
    return hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()


def match_terms(text: str, terms: list[str]) -> list[str]:
    """Return configured terms that appear in already-lowercased text."""
    return [term for term in terms if str(term).lower() in text]


def has_any(text: str, terms: list[str]) -> bool:
    """Return whether any configured term appears in text."""
    return bool(match_terms(text, terms))


def add_terms(evaluation: Evaluation, group: str, terms: list[str]) -> None:
    """Record matched terms by group."""
    if terms:
        evaluation.matched_terms.setdefault(group, []).extend(terms)


def load_sent_state(path: Path = STATE_FILE) -> dict[str, Any]:
    """Load sent fingerprints for the current UTC date."""
    today = datetime.now(UTC).date().isoformat()
    if not path.exists():
        return {"date": today, "fingerprints": []}

    with path.open("r", encoding="utf-8") as file:
        state: dict[str, Any] = json.load(file)

    if state.get("date") != today:
        return {"date": today, "fingerprints": []}

    fingerprints = state.get("fingerprints", [])
    if not isinstance(fingerprints, list):
        return {"date": today, "fingerprints": []}

    return {"date": today, "fingerprints": fingerprints}


def save_sent_state(state: dict[str, Any], path: Path = STATE_FILE) -> None:
    """Persist sent fingerprints."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")


def match_evidence(text: str, config: dict[str, Any], evaluation: Evaluation) -> int:
    """Score evidence groups once each."""
    score = 0
    for group, group_config in config.get("evidence_context", {}).items():
        terms = match_terms(text, group_config.get("terms", []))
        if not terms:
            continue
        add_terms(evaluation, f"evidence:{group}", terms)
        evaluation.evidence_groups.append(group)
        score += int(group_config.get("score", 0))
    return score


def match_entities(text: str, config: dict[str, Any], evaluation: Evaluation) -> int:
    """Score configured entities when a good context is present."""
    score = 0
    for entity in config.get("entities", []):
        aliases = match_terms(text, entity.get("aliases", []))
        if not aliases:
            continue
        canonical = entity.get("canonical", aliases[0])
        bad_terms = match_terms(text, entity.get("bad_context", []))
        good_terms = match_terms(text, entity.get("good_context", []))
        add_terms(evaluation, f"entity:{canonical}", aliases + good_terms + bad_terms)
        evaluation.matched_entities.append(str(canonical))
        if bad_terms and not good_terms:
            evaluation.noise_groups.append(f"entity_bad_context:{canonical}")
            score -= 5
        elif good_terms:
            score += 6
            evaluation.reasons.append(f"entity context: {canonical}")
    return score


def match_clusters(text: str, config: dict[str, Any], evaluation: Evaluation) -> tuple[int, bool, bool]:
    """Score anchor and industry clusters."""
    score = 0
    has_domain = False
    has_vertical = False
    clusters = config.get("clusters", {})

    for group_name, group_config in clusters.items():
        terms = match_terms(text, group_config.get("terms", []))
        if not terms:
            continue

        if group_name == "vertical_anchor":
            required = group_config.get("required_context_any", [])
            if not has_any(text, required):
                add_terms(evaluation, f"ignored:{group_name}", terms)
                continue
            has_vertical = True

        add_terms(evaluation, group_name, terms)
        max_hits = int(group_config.get("max_hits_per_article", 1))
        group_score = int(group_config.get("score", 0))
        if max_hits > 0 and group_score:
            score += group_score

        if group_name == "domain_anchor":
            has_domain = True
        if group_name == "industry_context":
            evaluation.reasons.append("industry context")

    return score, has_domain, has_vertical


def match_conditional_events(text: str, config: dict[str, Any], evaluation: Evaluation) -> tuple[int, bool]:
    """Score conditional events only when their contexts are satisfied."""
    score = 0
    has_event = False
    evidence_groups = set(evaluation.evidence_groups)

    for event_name, event_config in config.get("conditional_event", {}).items():
        terms = match_terms(text, event_config.get("terms", []))
        if not terms:
            continue

        bad_terms = match_terms(text, event_config.get("bad_context", []))
        if bad_terms and not has_any(text, event_config.get("good_context", [])):
            add_terms(evaluation, f"event_bad:{event_name}", terms + bad_terms)
            evaluation.noise_groups.append(f"event_bad_context:{event_name}")
            continue

        required_context = event_config.get("required_context_any", [])
        if required_context and not has_any(text, required_context):
            add_terms(evaluation, f"event_unqualified:{event_name}", terms)
            continue

        required_evidence = set(event_config.get("required_evidence_any", []))
        if required_evidence and evidence_groups.isdisjoint(required_evidence):
            add_terms(evaluation, f"event_unqualified:{event_name}", terms)
            continue

        good_context = event_config.get("good_context", [])
        if good_context and not has_any(text, good_context):
            add_terms(evaluation, f"event_unqualified:{event_name}", terms)
            continue

        add_terms(evaluation, f"event:{event_name}", terms)
        score += int(event_config.get("score", 0))
        has_event = True
        evaluation.reasons.append(event_name.replace("_", " "))

    return score, has_event


def apply_noise(text: str, config: dict[str, Any], evaluation: Evaluation, strong_evidence: bool) -> int:
    """Apply noise penalties and immediate exclusions."""
    score_delta = 0
    noise_config = config.get("noise", {})

    immediate_terms = match_terms(text, noise_config.get("immediate_exclude", []))
    if immediate_terms:
        add_terms(evaluation, "immediate_exclude", immediate_terms)
        evaluation.excluded = True
        evaluation.exclusion_reason = "immediate excluded phrase matched: how to use it"
        return score_delta

    for group_name, group_config in noise_config.items():
        if group_name == "immediate_exclude":
            continue
        terms = match_terms(text, group_config.get("terms", []))
        if not terms:
            continue
        add_terms(evaluation, f"noise:{group_name}", terms)
        evaluation.noise_groups.append(group_name)
        score_delta += int(group_config.get("penalty", 0))
        if group_config.get("exclude_if_no_strong_evidence", False) and not strong_evidence:
            evaluation.excluded = True
            evaluation.exclusion_reason = f"{group_name} without strong industry evidence"
            break

    return score_delta


def evaluate_text(text: str, config: dict[str, Any]) -> Evaluation:
    """Evaluate already-built searchable text against the K-beauty rules."""
    evaluation = Evaluation()
    score = 0

    score += match_evidence(text, config, evaluation)
    entity_score = match_entities(text, config, evaluation)
    score += entity_score
    cluster_score, has_domain, has_vertical = match_clusters(text, config, evaluation)
    score += cluster_score
    event_score, has_event = match_conditional_events(text, config, evaluation)
    score += event_score

    has_entity = bool(evaluation.matched_entities)
    has_evidence = bool(evaluation.evidence_groups)
    strong_evidence_groups = set(evaluation.evidence_groups) - {"numeric"}
    strong_evidence = bool(strong_evidence_groups) and (has_event or has_domain or has_entity or has_vertical)
    score += apply_noise(text, config, evaluation, strong_evidence)

    if not evaluation.excluded and not (has_domain or has_entity or has_vertical):
        evaluation.excluded = True
        evaluation.exclusion_reason = "missing K-beauty domain anchor, entity, or qualified vertical anchor"

    caps = config.get("score_caps", {})
    if not has_evidence and (has_domain or has_entity or has_vertical):
        score = min(score, int(caps.get("domain_plus_event_without_evidence", 14)))
    if not has_event and not has_evidence and cluster_score > 0:
        score = min(score, int(caps.get("domain_anchor_only", 7)))

    threshold = int(config.get("threshold", DEFAULT_THRESHOLD))
    evaluation.score = score
    evaluation.send = not evaluation.excluded and score >= threshold
    if not evaluation.send and not evaluation.exclusion_reason:
        evaluation.exclusion_reason = f"score below threshold: {score} < {threshold}"

    return evaluation


def evaluate_entry(entry: Any, config: dict[str, Any]) -> Evaluation:
    """Evaluate an RSS entry against the K-beauty rules."""
    return evaluate_text(entry_text(entry), config)


def summarize_terms(values: dict[str, list[str]], limit: int = 8) -> str:
    """Return a compact matched term summary."""
    parts: list[str] = []
    for group, terms in values.items():
        unique_terms = list(dict.fromkeys(terms))[:3]
        parts.append(f"{group}={'; '.join(unique_terms)}")
        if len(parts) >= limit:
            break
    return " | ".join(parts) if parts else "없음"


def build_telegram_message(source_name: str, evaluation: Evaluation, title: str, link: str) -> str:
    """Build a Telegram alert message for a matched RSS entry."""
    evidence = ", ".join(dict.fromkeys(evaluation.evidence_groups)) or "없음"
    noise = ", ".join(dict.fromkeys(evaluation.noise_groups)) or "없음"
    reasons = ", ".join(dict.fromkeys(evaluation.reasons)) or "산업 문맥"
    matched = summarize_terms(evaluation.matched_terms)
    return (
        "[K-뷰티 알림]\n"
        f"점수: {evaluation.score}\n"
        f"출처: {source_name}\n"
        f"근거: {reasons} / evidence={evidence}\n"
        f"잡음: {noise}\n"
        f"일치 항목: {matched}\n"
        f"제목: {title}\n"
        f"링크: {link}"
    )


def process_source(
    source: dict[str, str],
    config: dict[str, Any],
    sent_fingerprints: set[str],
    sends_remaining: int,
    dry_run: bool,
) -> tuple[int, int, int, int, list[str]]:
    """Process one RSS source and return counts plus newly sent fingerprints."""
    name = source.get("name", "Unnamed source")
    url = source.get("url")
    new_fingerprints: list[str] = []

    if not url:
        print(f"\nSource: {name}")
        print("  Error: missing RSS url")
        return 0, 0, 0, 0, new_fingerprints

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
            fingerprint = entry_fingerprint(entry)
            if fingerprint in sent_fingerprints:
                continue

            evaluation = evaluate_entry(entry, config)
            title = entry.get("title", "No title")
            link = entry.get("link", "")

            if not evaluation.send:
                print(f"Excluded: {title}")
                print(f"  Reason: {evaluation.exclusion_reason}")
                print(f"  Score: {evaluation.score}")
                continue

            matched_entries += 1
            print(f"\nSource: {name}")
            print(f"Title: {title}")
            print(f"Link: {link or 'No link'}")
            print(f"Score: {evaluation.score}")
            print(f"Matched: {summarize_terms(evaluation.matched_terms)}")

            if send_successes + send_failures >= sends_remaining:
                print("Telegram send skipped: max send limit reached")
                continue

            message = build_telegram_message(name, evaluation, title, link)
            if dry_run:
                print("Telegram send skipped: dry-run")
                send_successes += 1
            elif send_message(message):
                send_successes += 1
                print("Telegram send: success")
            else:
                send_failures += 1
                print("Telegram send: failed")
                continue

            sent_fingerprints.add(fingerprint)
            new_fingerprints.append(fingerprint)

        return checked_entries, matched_entries, send_successes, send_failures, new_fingerprints
    except Exception as exc:
        print(f"\nSource: {name}")
        print(f"  Error reading RSS source: {exc}")
        return checked_entries, matched_entries, send_successes, send_failures, new_fingerprints


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description="Run the K-beauty news alert bot.")
    parser.add_argument("--dry-run", action="store_true", help="Filter RSS entries without Telegram delivery.")
    parser.add_argument("--sources", type=Path, default=SOURCES_FILE, help="Path to sources.yaml.")
    parser.add_argument("--keywords", type=Path, default=KEYWORDS_FILE, help="Path to keywords.yaml.")
    parser.add_argument("--state", type=Path, default=STATE_FILE, help="Path to sent state JSON.")
    return parser.parse_args()


def main() -> None:
    """Read RSS sources, filter K-beauty industry news, and send alerts."""
    args = parse_args()
    sources = load_sources(args.sources)
    config = load_keyword_config(args.keywords)
    state = load_sent_state(args.state)
    sent_fingerprints = set(state.get("fingerprints", []))
    max_send = int(config.get("max_send_per_run", DEFAULT_MAX_SEND_PER_RUN))

    total_checked_entries = 0
    total_matched_entries = 0
    total_send_successes = 0
    total_send_failures = 0

    for source in sources:
        sends_remaining = max_send - total_send_successes - total_send_failures
        checked_entries, matched_entries, send_successes, send_failures, new_fingerprints = process_source(
            source, config, sent_fingerprints, sends_remaining, args.dry_run
        )
        total_checked_entries += checked_entries
        total_matched_entries += matched_entries
        total_send_successes += send_successes
        total_send_failures += send_failures
        state["fingerprints"].extend(new_fingerprints)

    if not args.dry_run:
        save_sent_state(state, args.state)

    print("\nSummary")
    print(f"RSS sources read: {len(sources)}")
    print(f"Entries checked: {total_checked_entries}")
    print(f"Entries matched: {total_matched_entries}")
    print(f"Telegram send successes: {total_send_successes}")
    print(f"Telegram send failures: {total_send_failures}")


if __name__ == "__main__":
    main()
