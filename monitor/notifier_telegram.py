"""
Telegram Notifier
Formats matched rental listings and sends them as Telegram messages.
One message per listing — individual, not aggregated.
Supports Telegram forum topics (one thread per city).
"""

import os
import logging
import requests
from typing import Optional

log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

CITY_COLORS = ['🔴', '🟠', '🟡', '🟢', '🔵', '🟣', '🟤', '⚫']

AMENITY_LABELS = [
    ('parking',   '🚗 חניה'),
    ('safe_room', '🛡 ממ"ד'),
    ('balcony',   '🌿 מרפסת'),
    ('elevator',  '🛗 מעלית'),
    ('ac',        '❄️ מזגן'),
    ('storage',   '📦 מחסן'),
    ('furnished', '🛋 מרוהט'),
    ('boiler',    '☀️ דוד שמש'),
]


def city_color(city_name: str) -> str:
    return CITY_COLORS[hash(city_name) % len(CITY_COLORS)]


def get_or_create_thread(city_name: str) -> Optional[int]:
    """Return the forum topic thread_id for a city, creating it if needed.
    Returns None if the chat is not a supergroup with topics enabled."""
    from config_store import get_city_thread_id, set_city_thread_id
    stored = get_city_thread_id(city_name)
    if stored == '0':
        return None
    if stored:
        return int(stored)
    try:
        color = city_color(city_name)
        resp = requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/createForumTopic',
            json={'chat_id': TELEGRAM_CHAT_ID, 'name': f'{color} {city_name}'},
            timeout=10
        )
        if resp.status_code == 200:
            thread_id = resp.json()['result']['message_thread_id']
            set_city_thread_id(city_name, str(thread_id))
            log.info(f'Created forum topic for {city_name}: thread_id={thread_id}')
            return thread_id
        log.info(f'createForumTopic failed ({resp.status_code}) — Topics not available')
        set_city_thread_id(city_name, '0')
        return None
    except Exception as e:
        log.warning(f'createForumTopic error: {e}')
        set_city_thread_id(city_name, '0')
        return None


def format_message(listing: dict) -> str:
    """Format a matched listing into a Telegram message (Hebrew)."""
    parsed = listing.get('parsed', {})

    price     = listing.get('price') or parsed.get('price')
    rooms     = listing.get('rooms') or parsed.get('rooms')
    sqm       = listing.get('sqm')
    floor     = listing.get('floor')
    condition = listing.get('condition')
    entry_date = listing.get('entry_date') or parsed.get('entry_date')
    summary   = parsed.get('summary', '')
    post_url  = listing.get('post_url', '')

    city         = listing.get('city') or parsed.get('city') or ''
    neighborhood = listing.get('neighborhood') or parsed.get('neighborhood') or ''
    street       = listing.get('street') or parsed.get('street') or ''

    if neighborhood and city:
        location = f"{city}, {neighborhood}"
    elif street and city:
        location = f"{city}, {street}"
    elif city:
        location = city
    elif neighborhood:
        location = neighborhood
    else:
        location = 'מיקום לא ידוע'

    color = city_color(city) if city else '🏠'

    price_line = f"💰 {price:,} ₪ לחודש" if price else "💰 מחיר לא צוין"

    if rooms:
        rooms_display = int(rooms) if rooms == int(rooms) else rooms
        rooms_line = f"🛏 {rooms_display} חדרים"
    else:
        rooms_line = "🛏 מספר חדרים לא צוין"

    meta_parts = []
    if sqm:
        meta_parts.append(f'📐 {sqm} מ"ר')
    if floor is not None:
        meta_parts.append(f'🏢 קומה {floor}')
    if condition:
        meta_parts.append(condition)
    meta_line = ' | '.join(meta_parts)

    amenity_lines = []
    for key, label in AMENITY_LABELS:
        val = listing.get(key)
        if val is True:
            amenity_lines.append(f'{label}: ✅')
        elif val is False:
            amenity_lines.append(f'{label}: ❌')

    lines = [
        f"{color} דירה חדשה להשכרה — {location}",
        "",
        price_line,
        rooms_line,
    ]

    if meta_line:
        lines.append(meta_line)

    lines.extend(amenity_lines)

    if street:
        lines.append(f"📍 {street}")

    if entry_date:
        lines.append(f"📅 כניסה: {entry_date}")

    if summary:
        lines.append("")
        lines.append(f'"{summary}"')

    if post_url:
        lines.append("")
        lines.append(f"👉 [לצפייה במודעה]({post_url})")

    return "\n".join(lines)


def send_alert(listing: dict) -> bool:
    """Send a single listing alert to Telegram. Returns True if successful."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error('Telegram credentials not set — check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env')
        return False

    city = listing.get('city', '')
    thread_id = get_or_create_thread(city) if city else None

    message = format_message(listing)
    image_urls = listing.get('image_urls', [])
    log.info(f'Sending alert for {listing.get("id")} — {len(image_urls)} image(s) thread={thread_id}')

    extra = {'message_thread_id': thread_id} if thread_id else {}

    try:
        if len(image_urls) >= 2:
            media = [{'type': 'photo', 'media': image_urls[0], 'caption': message, 'parse_mode': 'Markdown'}]
            media += [{'type': 'photo', 'media': u} for u in image_urls[1:9]]
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup"
            resp = requests.post(url, json={'chat_id': TELEGRAM_CHAT_ID, 'media': media, **extra}, timeout=15)
            if resp.status_code == 200:
                log.info(f'Telegram album ({len(media)} photos) sent for {listing.get("id")}')
                return True
            log.warning(f'sendMediaGroup failed ({resp.status_code}), falling back')

        if image_urls:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            resp = requests.post(url, json={
                'chat_id': TELEGRAM_CHAT_ID,
                'photo': image_urls[0],
                'caption': message,
                'parse_mode': 'Markdown',
                **extra
            }, timeout=10)
            if resp.status_code == 200:
                log.info(f'Telegram photo alert sent for {listing.get("id")}')
                return True
            log.warning(f'sendPhoto failed ({resp.status_code}), falling back to text')

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': False,
            **extra
        }, timeout=10)
        if resp.status_code == 200:
            log.info(f'Telegram text alert sent for {listing.get("id")}')
            return True
        log.error(f'Telegram API error {resp.status_code}: {resp.text}')
        return False

    except Exception as e:
        log.error(f'Failed to send Telegram alert: {e}')
        return False
