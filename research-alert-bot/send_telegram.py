"""Send Telegram messages for research alerts."""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

TELEGRAM_API_BASE_URL = "https://api.telegram.org/bot"
TEST_MESSAGE = """[Research Alert Bot Test]
Telegram connection is working."""


def normalize_secret_value(value: str) -> str:
    """Normalize common copy/paste mistakes in secret values."""
    normalized = value.strip().strip('"').strip("'")
    if "=" in normalized and normalized.split("=", 1)[0] in {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    }:
        normalized = normalized.split("=", 1)[1].strip().strip('"').strip("'")

    return normalized


def normalize_bot_token(value: str) -> str:
    """Normalize Telegram bot token secret values."""
    token = normalize_secret_value(value)

    for prefix in (
        "https://api.telegram.org/bot",
        "http://api.telegram.org/bot",
    ):
        if token.startswith(prefix):
            token = token.removeprefix(prefix).strip("/")

    if token.endswith("/sendMessage"):
        token = token.removesuffix("/sendMessage").strip("/")

    if token.startswith("bot") and len(token) > 3 and token[3].isdigit():
        token = token[3:]

    return token


def send_message(text: str) -> bool:
    """Send a text message through the Telegram Bot API."""
    load_dotenv()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if bot_token:
        bot_token = normalize_bot_token(bot_token)
    if chat_id:
        chat_id = normalize_secret_value(chat_id)

    if not bot_token:
        print("Missing required environment variable: TELEGRAM_BOT_TOKEN")
        return False

    if not chat_id:
        print("Missing required environment variable: TELEGRAM_CHAT_ID")
        return False

    url = f"{TELEGRAM_API_BASE_URL}{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
    except requests.RequestException as exc:
        print(f"Telegram sendMessage request failed: {exc}")
        return False

    if response.status_code != requests.codes.ok:
        print(f"Telegram sendMessage failed with status code: {response.status_code}")
        print(f"Response text: {response.text}")
        if response.status_code == requests.codes.not_found:
            print(
                "Telegram returned 404 Not Found. Verify that "
                "TELEGRAM_BOT_TOKEN contains only the BotFather token value."
            )
        return False

    return True


def main() -> None:
    """Send a Telegram test message when executed directly."""
    send_message(TEST_MESSAGE)


if __name__ == "__main__":
    main()
