# 🏠 Rental Monitor — Israel

Real-time rental apartment monitor for Israel. Monitors Yad2 and public Facebook groups every 15 minutes. Sends Telegram photo alerts within minutes of a new listing appearing.

Built because listings disappear within hours — native Yad2 alerts are too slow, and Facebook groups have no native alerts at all.

---

## What It Does

- Monitors **Yad2** every 15 minutes via their internal JSON API
- Monitors **public Facebook rental groups** via Playwright
- Sends **photo album alerts** (up to 9 photos per listing) via Telegram
- Shows **rich listing details**: price, rooms, sqm, floor, property condition, detection time
- Shows **amenity icons** for features the apartment has (🚗 parking, 🛡 safe room, 🌿 balcony, 🛗 elevator, ❄️ AC, etc.)
- Filters by city, neighborhood, min rooms, max price, and must-haves
- Supports **multiple cities simultaneously** — each city gets a unique color dot and its own Telegram topic thread
- Sends a **daily digest at 22:00** (Israel time) summarizing all listings found that day per city
- Fully configurable via **Hebrew natural language** in Telegram — no code changes needed
- Bot conversation state and all config **survive Railway restarts** (Supabase-backed)

---

## Alert Format

```
🟡 דירה חדשה להשכרה — תל אביב, גני שרונה
🕐 התגלתה היום ב-14:32

💰 14,000 ₪ לחודש
🛏 4 חדרים
📐 126 מ"ר | 🏢 קומה 26 | במצב טוב
פיצ'רים: 🚗 | 🛡 | 🌿 | 🛗

📍 רחוב אוסוולדו ארניה

👉 לצפייה במודעה
```

Photos (up to 9) are sent as an album above the message.

---

## Architecture

```
Python Service (Railway)
│
├── APScheduler
│   ├── scrape cycle every 15 minutes
│   └── daily digest at 19:00 UTC (22:00 Israel)
│
├── scraper_yad2.py       — Yad2 map API + Playwright detail fetch (amenities)
├── scraper_facebook.py   — Playwright scraper (public groups)
├── parser_claude.py      — Claude API parses Hebrew free text (Facebook)
├── notifier_telegram.py  — formats and sends Telegram alerts + Topics threading
├── bot_telegram.py       — Hebrew NLU bot for live configuration
├── config_store.py       — Supabase-backed config (cities, filters, groups, state)
└── seen_store.py         — SQLite deduplication
```

---

## Source APIs

### Yad2
- **Map API:** `https://gw.yad2.co.il/realestate-feed/rent/map` — returns listings as map markers (no browser needed)
- **Detail page:** `https://www.yad2.co.il/item/{token}` — fetched via Playwright + stealth to bypass Radware; extracts amenity data from `__NEXT_DATA__` JSON
- **City/neighborhood resolution:** Yad2 autocomplete API resolves Hebrew names to numeric IDs automatically

### Facebook
- **Method:** Playwright (headless Chromium)
- **Groups:** Configured via bot — any public Facebook rental group URL
- **Parsing:** Claude API (claude-haiku) parses unstructured Hebrew post text into structured fields

---

## Telegram Bot

All configuration is done by chatting with the bot in Hebrew (or English). No slash commands required — just write naturally.

### Natural language examples
| You write | Bot does |
|---|---|
| `הוסף עיר` | Starts add-city flow |
| `סטטוס` | Shows current config |
| `יכולות` | Shows full feature list |
| `שנה מחיר ל-12000` | Updates max price immediately |
| `עצור` | Pauses monitoring |
| `המשך` | Resumes monitoring |

### Slash commands (also work)
| Command | Description |
|---|---|
| `/status` | Current config — cities, filters, groups |
| `/features` | Full list of bot capabilities |
| `/add_city` | Add a city to monitor |
| `/remove_city` | Remove a city |
| `/remove_neighborhood` | Remove a neighborhood filter |
| `/set_price` | Set max price in NIS |
| `/set_rooms` | Set minimum rooms |
| `/must_have` | Toggle parking / safe room as required |
| `/add_group` | Add Facebook group URL |
| `/remove_group` | Remove Facebook group |
| `/pause` / `/resume` | Pause or resume monitoring |
| `/help` | Command list |

### Add-city flow
When you add a city the bot asks step-by-step:
1. City name (auto-resolved to Yad2 ID)
2. Max price
3. Min rooms
4. Specific neighborhood (optional)
5. Must-haves: parking / safe room / both / neither
6. Facebook groups to monitor for this city

---

## Telegram Topics (multi-city)

Each city gets its own topic thread in a Telegram supergroup — alerts never mix.

**Setup (one-time):**
1. Create a Telegram group → enable **Topics** in group settings
2. Add the bot as admin with **"Manage Topics"** permission
3. Get the group chat ID (forward a group message to [@userinfobot](https://t.me/userinfobot))
4. Set `TELEGRAM_CHAT_ID` in Railway to the negative group ID (e.g. `-1002345678901`)

The bot auto-creates a topic thread for each city on its first alert. New cities added later get their own thread automatically.

---

## Daily Digest

Every day at **22:00 Israel time** the bot sends a summary per city:

```
📋 סיכום יומי — תל אביב
3 מודעות חדשות היום:
• 14,000 ₪ | 4 חד | 126 מ"ר → קישור
• 12,500 ₪ | 4 חד | 98 מ"ר → קישור
• 15,000 ₪ | 5 חד → קישור
```

Sent to each city's own topic thread (if Topics enabled).

---

## Stack

| Tool | Role |
|---|---|
| Python + curl_cffi | Yad2 map API (Chrome impersonation) |
| Playwright + stealth | Yad2 detail pages + Facebook scraping |
| Claude API (Haiku) | Hebrew NLU intent classification + Facebook text parsing |
| APScheduler | 15-min scrape cycle + daily digest |
| python-telegram-bot | Alerts + inline keyboard bot |
| Supabase (PostgreSQL) | Config, bot state, seen listings, city threads |
| SQLite | Local deduplication store |
| Railway | Hosting |

---

## Environment Variables

```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=        # private chat ID or supergroup ID (negative)
ANTHROPIC_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
```

Never commit `.env` — it is in `.gitignore`.

---

## Setup

```bash
cd monitor
pip install -r requirements.txt
playwright install chromium
cp ../.env.example ../.env
# Fill in .env with your credentials
python main.py
```

Requires Python 3.11+.

---

## Project Structure

```
rental-monitor/
├── .env                    # secrets — never committed
├── Dockerfile              # Railway deployment (includes Playwright + Chromium)
├── README.md
└── monitor/
    ├── main.py             # scheduler + orchestrator
    ├── scraper_yad2.py     # Yad2 API + Playwright detail fetch
    ├── scraper_facebook.py # Facebook Playwright scraper
    ├── parser_claude.py    # Claude API Hebrew parser
    ├── notifier_telegram.py# Telegram alert formatter + sender
    ├── bot_telegram.py     # Hebrew NLU Telegram bot
    ├── config_store.py     # Supabase config + state manager
    ├── seen_store.py       # SQLite deduplication
    └── requirements.txt
```

---

## Cost

| Component | Cost |
|---|---|
| Claude API | ~$1–3/month |
| Supabase | Free tier |
| Railway | ~$5/month |
| Everything else | Free |

---

*Personal project. Not affiliated with Yad2 or Facebook.*
