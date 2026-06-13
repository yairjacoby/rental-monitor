# 🏠 Rental Monitor — Israel

Real-time rental apartment monitor for Israel. Sends Telegram alerts within minutes of a new listing being posted in target neighborhoods.

Built because native Yad2 alerts are too slow — high-demand listings disappear within hours.

---

## What It Does

- Monitors Yad2 and Madlan every 15 minutes via n8n
- Monitors public Facebook rental groups every 15 minutes via Python + Playwright
- Uses Claude API to parse unstructured Hebrew text from Facebook posts
- Filters by city, neighborhood, rooms, price, and must-haves (parking, safe room)
- Sends instant Telegram alerts for every new matching listing
- Never alerts twice for the same listing (SQLite deduplication)

---

## Architecture
n8n (Railway)                        Python / Railway
├── Yad2 HTTP polling                ├── Playwright → Facebook groups
├── Madlan HTTP polling              ├── Claude API → Hebrew text parsing
├── Filter by config                 ├── Filter by config
├── Deduplication (n8n data store)   ├── Deduplication (SQLite)
└── Telegram alert                   └── Telegram alert

Two services, one repo. n8n handles structured API sources with no code. Python handles Facebook which requires real browser automation.

---

## Stack

| Tool | Role |
|---|---|
| n8n | Yad2 + Madlan polling, filtering, deduplication, Telegram |
| Python + Playwright | Facebook group scraping (headless Chromium) |
| Claude API (Sonnet) | Hebrew free-text parsing — extracts price, rooms, location, broker flag |
| Telegram Bot | Real-time alerts |
| Railway | Hosting for both n8n and Python service |
| SQLite | Deduplication store for Facebook scraper |

---

## Configuration

All search parameters live in `config.json` — no code changes needed.

```json
{
  "searches": [
    {
      "city": "הוד השרון",
      "neighborhoods": ["שכונה 1200"],
      "max_price": 13000
    }
  ],
  "filters": {
    "rooms_min": 4,
    "must_have": {
      "parking": ["חניה", "חנייה"],
      "safe_room": ["ממד", "ממ״ד", "מרחב מוגן"]
    }
  },
  "facebook_groups": [
    "https://www.facebook.com/groups/..."
  ]
}
```

To add a city, neighborhood, or Facebook group: edit `config.json`, commit, push. Railway redeploys automatically.

---

## Setup

### Prerequisites
- Python 3.10+
- n8n instance (Railway)
- Telegram bot token ([create here](https://t.me/BotFather))
- Anthropic API key ([platform.claude.com](https://platform.claude.com))

### Python service

```bash
cd facebook_scraper
pip install -r requirements.txt
playwright install chromium
cp ../.env.example ../.env
# Fill in .env values
python main.py
```

### Environment variables
ANTHROPIC_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

### n8n workflow
Import `n8n/workflow.json` into your n8n instance. Set environment variables in Railway.

---

## Project Structure
rental-monitor/
├── config.json              # search parameters — edit freely
├── .env                     # secrets — never committed
├── n8n/
│   └── workflow.json        # n8n workflow export
└── facebook_scraper/
├── main.py              # scheduler + orchestrator
├── scraper_facebook.py  # Playwright Facebook scraper
├── parser_claude.py     # Claude API Hebrew parser
├── notifier_telegram.py # Telegram sender
├── seen_store.py        # SQLite deduplication
├── config_loader.py     # config.json loader
└── requirements.txt

---

## Cost

| Component | Cost |
|---|---|
| Claude API | ~$1-3/month |
| Railway | Free tier ($5 credit/month) |
| Everything else | Free |

---

*Personal project. Not affiliated with Yad2, Madlan, or Facebook.*
