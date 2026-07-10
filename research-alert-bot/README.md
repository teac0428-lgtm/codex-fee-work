# research-alert-bot

A Python RSS alert bot that monitors Google News RSS feeds, filters news by research keywords, and sends matched items to Telegram. It can be run locally or from GitHub Actions.

## Current MVP features

- Collects Google News RSS feeds from `sources.yaml`.
- Filters RSS entries using keyword groups in `keywords.yaml`.
- Applies advertisement, market-summary, ticker-only, and CoreWeave context filters before sending.
- Sends matched news alerts to Telegram.
- Supports manual and hourly scheduled runs with GitHub Actions.
- Limits Telegram sends per run to avoid message floods.

## Local setup and run

From the repository root:

```bash
cd /workspaces/codex-fee-work
python -m pip install -r research-alert-bot/requirements.txt
python research-alert-bot/collector.py
```

To send only a Telegram test message:

```bash
python research-alert-bot/send_telegram.py
```

## `.env` setup

Create a local `.env` file in the repository root:

```bash
cp research-alert-bot/.env.example .env
```

Fill it with your Telegram credentials:

```env
TELEGRAM_BOT_TOKEN=123456789:AA_your_bot_token
TELEGRAM_CHAT_ID=123456789
```

Do not commit `.env`.

## Get a Telegram Bot Token

1. Open Telegram and chat with `@BotFather`.
2. Run `/newbot` and follow the prompts.
3. Copy the token that looks like `123456789:AA...`.
4. Use only the token value, not the bot username and not the full API URL.

## Find your Telegram Chat ID

1. Send `/start` to your bot in Telegram.
2. Open this URL in a browser, replacing `<TOKEN>` with your bot token:

```text
https://api.telegram.org/bot<TOKEN>/getUpdates
```

3. Find `message.chat.id` in the JSON response.
4. Use that number as `TELEGRAM_CHAT_ID`.

For group chats, add the bot to the group first. Group chat IDs are often negative or start with `-100`.

## GitHub Secrets setup

In GitHub:

```text
Repository → Settings → Secrets and variables → Actions → New repository secret
```

Add these repository secrets:

| Name | Value |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | BotFather token only, for example `123456789:AA...` |
| `TELEGRAM_CHAT_ID` | Telegram chat ID |

Do not include `TELEGRAM_BOT_TOKEN=` or `TELEGRAM_CHAT_ID=` in the secret value.

## Run with GitHub Actions

Manual run:

1. Open the repository on GitHub.
2. Go to `Actions`.
3. Select `Research Alert Bot`.
4. Click `Run workflow`.

Scheduled run:

- The workflow runs every hour using cron: `0 * * * *`.
- GitHub Actions cron uses UTC time.

## Edit `sources.yaml`

`sources.yaml` contains Google News RSS searches:

```yaml
rss:
  - name: Google News - HBM
    url: "https://news.google.com/rss/search?q=HBM&hl=en-US&gl=US&ceid=US:en"
```

To add a source:

1. Add a new item under `rss`.
2. Set a readable `name`.
3. Use a Google News RSS search URL.
4. Replace spaces in search terms with `+` or URL encoding.

## Edit `keywords.yaml`

`keywords.yaml` has positive keyword groups and noise/context groups:

```yaml
high_priority:
  - HBM
medium_priority:
  - data center
korean:
  - 고대역폭메모리
industry_context:
  - cloud contract
advertisement_noise:
  - sponsored
market_noise:
  - price target
ticker_noise:
  - CRWV stock
```

To add keywords, append them under the appropriate group. Matching is case-insensitive for English keywords. Use `|` to group aliases under one representative keyword, for example `HBM | High Bandwidth Memory`.

## Filtering notes

- Advertisement noise such as `sponsored`, `paid content`, or `promo code` is skipped immediately.
- Ticker-only CoreWeave items such as `CRWV stock` or `CoreWeave shares` are skipped unless an industry context keyword is also present.
- CoreWeave aliases (`CoreWeave`, `$CRWV`, `CRWV stock`, `CoreWeave shares`) are treated as the same entity.
- CoreWeave with strong context such as `cloud contract`, `GPU capacity`, `data center`, `Blackwell`, `backlog`, or `power capacity` can pass, and ticker/market noise penalties are waived for that entry.

Quick local syntax check:

```bash
python -m py_compile research-alert-bot/collector.py
```

## Common errors

### `401 Unauthorized`

The Telegram Bot Token is wrong or revoked.

Fix:

- Reissue the token in `@BotFather`.
- Update `.env` locally or `TELEGRAM_BOT_TOKEN` in GitHub Secrets.

### `chat not found`

The Chat ID is wrong, or the bot has not received `/start` from that chat.

Fix:

- Send `/start` to the bot.
- Run `getUpdates` again.
- Update `TELEGRAM_CHAT_ID`.

### `ModuleNotFoundError`

Dependencies are not installed.

Fix:

```bash
python -m pip install -r research-alert-bot/requirements.txt
```

### YAML syntax error

Usually caused by bad indentation in YAML files, especially `.github/workflows/alert.yml`.

Fix:

- Use spaces, not tabs.
- Keep nested keys aligned.
- Quote cron strings like `"0 * * * *"`.

### Empty result or no matched entries

RSS search returned no useful results, or keywords are too narrow.

Fix:

- Broaden search terms in `sources.yaml`.
- Add broader keywords in `keywords.yaml`.
- Check the Google News RSS URL directly in a browser.
