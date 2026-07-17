# k-beauty-alert-bot

A standalone Python 3.12 Google News RSS alert bot for K-beauty and beauty-care industry news.

## What it monitors

The first implementation focuses on industry signals instead of consumer shopping content:

- K-beauty and Korean cosmetics exports
- Regional retail sales and distribution expansion
- Sephora, Ulta Beauty, Amazon, Costco, and Target channel events
- ODM/OEM capacity, contracts, and production expansion
- MoCRA, FDA, certification, and regulatory changes
- Duty-free channel sales and overseas retail entry
- Beauty-device export, certification, and sales events

## Filtering approach

The bot does not send alerts just because a broad keyword such as `K-beauty`, `skincare`, `beauty device`, `revenue`, or `sales` appears. It uses clustered rules in `keywords.yaml`:

1. Confirm a K-beauty domain anchor, known entity, or qualified beauty-device vertical.
2. Look for an industry event such as export growth, distribution agreement, capacity expansion, regulation, or qualified product launch.
3. Require evidence such as numbers, contracts, performance terms, regulatory context, capacity context, or market expansion terms.
4. Apply advertisement, promotion, consumer-content, and stock-market noise penalties.
5. Immediately exclude any article containing the phrase `how to use it`.

## Local setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env` if you want to send Telegram messages:

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

## Run

Dry-run filtering without Telegram delivery:

```bash
python collector.py --dry-run
```

Live run:

```bash
python collector.py
```

## Tests

```bash
python -m pytest
python -m py_compile collector.py send_telegram.py
```

## State

Sent article fingerprints are stored in `state/k_beauty_sent_today.json` for the current UTC date. The state file is ignored by git.

## GitHub Actions

The included workflow runs on Python 3.12 every hour at minute 0 and can also be triggered manually. If this file set is moved into a fresh repository, keep `.github/workflows/k-beauty-alert.yml` at the repository root.
