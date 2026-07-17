"""Send Telegram messages for K-beauty research alerts."""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

TELEGRAM_API_BASE_URL = "https://api.telegram.org/bot"
TEST_MESSAGE = """[K-뷰티 알림봇 테스트]
Telegram connection is working."""


def send_message(text: str) -> bool:
    """Send a text message through the Telegram Bot API."""
    load_dotenv()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

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
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
    except requests.RequestException as exc:
        print(f"Telegram sendMessage request failed: {exc}")
        return False

    if response.status_code != requests.codes.ok:
        print(f"Telegram sendMessage failed with status code: {response.status_code}")
        print(f"Response text: {response.text}")
        return False

    return True


def main() -> None:
    """Send a Telegram test message when executed directly."""
    send_message(TEST_MESSAGE)


if __name__ == "__main__":
    main()
