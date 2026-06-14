# 🏠 Rental Monitor — Israel

Real-time rental apartment monitor for Israel. Monitors Yad2, Madlan, and public Facebook groups every 15 minutes. Sends Telegram alerts within minutes of a new listing being posted.

Built because listings disappear within hours — native Yad2 alerts are too slow, and Facebook groups have no native alerts at all.

---

## What It Does

- Monitors Yad2 every 15 minutes via their internal JSON API (no browser needed)
- Monitors Madlan every 15 minutes via Playwright (server-side rendered, no public API)
- Monitors public Facebook rental groups every 15 minutes via Playwright
- Uses Claude API to parse unstructured Hebrew text from Facebook posts
- Filters by city, neighborhood, rooms, price, and must-haves (parking, safe room)
- Sends instant Telegram alerts for every new matching listing
- Never alerts twice for the same listing (SQLite deduplication)
- Fully configurable via Telegram bot commands — no code or GitHub changes needed

---

## Architecture
Python Service (Railway)

├── APScheduler — fires every 15 minutes

├── scraper_yad2.py — HTTP requests to Yad2 internal API (gw.yad2.co.il)

├── scraper_madlan.py — Playwright scraper (SSR, no public API)

├── scraper_facebook.py — Playwright scraper (public groups, no login)

├── parser_claude.py — Claude API parses Hebrew free text (Facebook only)

├── notifier_telegram.py — formats and sends Telegram alerts

├── bot_telegram.py — Telegram bot for live configuration

├── config_store.py — SQLite-backed config (cities, filters, groups)

└── seen_store.py — SQLite deduplication store

One service, one language, one Railway deployment.

---

## Source APIs & Scraping

### Yad2
- **Method:** HTTP GET — no browser needed
- **Endpoint:** `https://gw.yad2.co.il/realestate-feed/rent/map`
- **Key parameters:** `city` (numeric ID), `area` (neighborhood ID), `minRooms`, `maxPrice`
- **Example:** `?city=9700&area=54&minRooms=4&maxPrice=13000`
- **City resolution:** Yad2 autocomplete API resolves city names to numeric IDs
- **Bot integration:** `/add_city` command resolves city name → ID automatically

### Madlan
- **Method:** Playwright (headless Chromium)
- **Why no API:** Listings are server-side rendered — no separate XHR/fetch call for listing data
- **URL pattern:** `https://www.madlan.co.il/for-rent/{city-name}-ישראל?filters=_{minPrice}-{maxPrice}_{minRooms}-`
- **Parsing:** Extract listing cards from rendered HTML

### Facebook
- **Method:** Playwright (headless Chromium)
- **Groups:** Configured via `/add_group` Telegram command or config
- **Parsing:** Claude API (claude-sonnet-4-6) parses unstructured Hebrew post text
- **Login wall guard:** Skips group if login prompt detected

---

## Telegram Bot Commands

All configuration is done via Telegram — no code changes, no GitHub pushes needed.

| Command | Description |
|---|---|
| `/status` | Show current config — cities, filters, groups |
| `/add_city הוד השרון` | Add a city to monitor (bot resolves ID automatically) |
| `/remove_city הוד השרון` | Remove a city |
| `/add_neighborhood הוד השרון שכונה 1200` | Add neighborhood filter to a city |
| `/set_price 13000` | Set max price in NIS |
| `/set_rooms 4` | Set minimum rooms |
| `/add_group https://facebook.com/groups/...` | Add Facebook group |
| `/remove_group https://facebook.com/groups/...` | Remove Facebook group |
| `/pause` | Pause monitoring |
| `/resume` | Resume monitoring |
| `/help` | List all commands |

All changes require confirmation — bot asks you to reply `/confirm` or `/cancel`.

---

## Alert Format
🏠 New Rental — הוד השרון, שכונה 1200

📡 Source: Yad2
💰 12,500 ₪/month

🛏 4.5 rooms

🚗 Parking: ✅

🛡 Safe room: ✅
📅 Entry: 01/08/2025
"Spacious 4.5 room apartment in 1200 neighborhood with parking and safe room."
👉 View listing

---

## Stack

| Tool | Role |
|---|---|
| Python + requests | Yad2 API polling (no browser needed) |
| Python + Playwright | Madlan + Facebook scraping (headless Chromium) |
| Claude API (claude-sonnet-4-6) | Hebrew free-text parsing for Facebook posts |
| APScheduler | Runs every 15 minutes inside the Python process |
| python-telegram-bot | Alerts + bot command handling |
| Railway | Hosting (free tier, $5 credit/month) |
| SQLite | Config store + deduplication |

---

## Configuration

Config lives in SQLite — managed entirely via Telegram bot commands. Initial setup:
/add_city הוד השרון

/add_neighborhood הוד השרון שכונה 1200

/set_price 13000

/set_rooms 4

/add_group https://www.facebook.com/share/g/1EWSUWPM7i/

/add_group https://www.facebook.com/share/g/1ExG6YipWn/

/add_group https://www.facebook.com/share/g/1DLdauYUWD/

/add_group https://www.facebook.com/share/g/1DkXixfNZo/

/add_group https://www.facebook.com/share/g/18nvrayqZp/

---

## Environment Variables
ANTHROPIC_API_KEY=

TELEGRAM_BOT_TOKEN=

TELEGRAM_CHAT_ID=

Never commit `.env` — it is in `.gitignore`.

---

## Setup

```bash
cd facebook_scraper
pip install -r requirements.txt
playwright install chromium
cp ../.env.example ../.env
# Fill in .env values
python main.py
```

---

## Project Structure
rental-monitor/

├── .env                      # secrets — never committed

├── .env.example              # template

├── config.json               # legacy — replaced by SQLite config store

├── README.md

└── facebook_scraper/

├── main.py               # scheduler + orchestrator

├── scraper_yad2.py       # Yad2 HTTP API scraper

├── scraper_madlan.py     # Madlan Playwright scraper

├── scraper_facebook.py   # Facebook Playwright scraper

├── parser_claude.py      # Claude API Hebrew parser

├── notifier_telegram.py  # Telegram alert sender

├── bot_telegram.py       # Telegram bot command handler

├── config_store.py       # SQLite config manager

├── seen_store.py         # SQLite deduplication

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
