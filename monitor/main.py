"""
Main Entry Point
Runs the rental monitor — scrapes all sources every 15 minutes.
Also runs the Telegram bot for live configuration.
"""

import logging
import os
import threading
import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from seen_store import init_db
from config_store import init_config_db, is_paused, get_config_summary
from scraper_yad2 import scrape_yad2
from scraper_facebook import scrape_all_groups
from parser_claude import parse_listings
from notifier_telegram import send_alert
from bot_telegram import build_bot
from config_store import get_facebook_groups

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s — %(message)s'
)
log = logging.getLogger(__name__)

_expansion_cooldown = {}  # city_name -> datetime of last send
_last_alert_sent_at: datetime.datetime = None
_last_heartbeat_sent_at: datetime.datetime = None


def _send_heartbeat():
    import requests as _requests
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        return
    _requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={'chat_id': chat_id,
              'text': '✅ המערכת פעילה — לא נמצאו מודעות חדשות בשעות האחרונות.',
              'parse_mode': 'Markdown'},
        timeout=10
    )
    log.info('Heartbeat notification sent')


def send_expansion_suggestion(city_name: str):
    """Send a Telegram message suggesting to expand search when no listings found."""
    import datetime
    import requests as _requests
    now = datetime.datetime.now()
    last = _expansion_cooldown.get(city_name)
    if last and (now - last).total_seconds() < 6 * 3600:
        log.debug(f'Expansion suggestion for {city_name} suppressed (cooldown)')
        return
    _expansion_cooldown[city_name] = now
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        return
    message = (
        f"🔍 לא נמצאו דירות חדשות בשכונות המוגדרות ב{city_name}.\n"
        f"האם להרחיב את החיפוש לכל {city_name}?\n\n"
        f"השתמש ב /add\\_neighborhood להוספת שכונות נוספות."
    )
    _requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown'},
        timeout=10
    )


def run_cycle():
    """One full scrape cycle across all sources."""
    if is_paused():
        log.info('Monitor is paused — skipping cycle')
        return

    log.info('=== Cycle start ===')
    total_sent = 0

    # ── Yad2 ──────────────────────────────────────────────────────────────────
    try:
        yad2_listings, zero_result_cities = scrape_yad2()
        log.info(f'Yad2: {len(yad2_listings)} new listings')
        for listing in yad2_listings:
            send_alert(listing)
            total_sent += 1
        # Suggest expanding search if no results found
        for city in zero_result_cities:
            send_expansion_suggestion(city)
    except Exception as e:
        log.error(f'Yad2 scraper error: {e}')

    # ── Facebook ──────────────────────────────────────────────────────────────
    try:
        group_urls = get_facebook_groups()
        if group_urls:
            config = {'facebook_groups': group_urls}
            raw_posts = scrape_all_groups(config)
            log.info(f'Facebook: {len(raw_posts)} new posts')
            matched = parse_listings(raw_posts, config)
            log.info(f'Facebook: {len(matched)} matched listings')
            for listing in matched:
                send_alert(listing)
                total_sent += 1
        else:
            log.info('Facebook: no groups configured')
    except Exception as e:
        log.error(f'Facebook scraper error: {e}')

    log.info(f'=== Cycle end — {total_sent} alerts sent ===')

    global _last_alert_sent_at, _last_heartbeat_sent_at
    now = datetime.datetime.now()
    if total_sent > 0:
        _last_alert_sent_at = now
    else:
        reference = _last_alert_sent_at or (now - datetime.timedelta(hours=13))
        hours_since_alert = (now - reference).total_seconds() / 3600
        hours_since_heartbeat = (_last_heartbeat_sent_at and
                                 (now - _last_heartbeat_sent_at).total_seconds() / 3600) or 999
        if hours_since_alert >= 12 and hours_since_heartbeat >= 12:
            _last_heartbeat_sent_at = now
            _send_heartbeat()


def main():
    # Init databases
    init_db()
    init_config_db()
    log.info('Databases initialized')

    # Log current config on startup
    log.info(get_config_summary())

    # Run one cycle immediately on startup
    run_cycle()

    # Schedule cycles every 15 minutes
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_cycle, 'interval', minutes=15)
    scheduler.start()
    log.info('Scheduler started — running every 15 minutes')

    # Start Telegram bot (blocking — runs in main thread)
    log.info('Starting Telegram bot...')
    bot = build_bot()
    bot.run_polling(allowed_updates=['message', 'callback_query'])


if __name__ == '__main__':
    main()
