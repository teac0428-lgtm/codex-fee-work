# research-alert-bot

A minimal Python automation project skeleton for a GitHub Actions-based news/RSS keyword alert bot.

## Purpose

This project will monitor configured news/RSS sources, match articles against research keywords, and send alerts through Telegram.

## Next steps

1. Define RSS/news sources in `sources.yaml`.
2. Define alert keywords and matching rules in `keywords.yaml`.
3. Implement collection and filtering logic in `collector.py`.
4. Implement Telegram notification logic in `send_telegram.py`.
5. Complete the GitHub Actions workflow schedule and execution commands.
