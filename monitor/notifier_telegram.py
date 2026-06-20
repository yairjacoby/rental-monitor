"""
Telegram Notifier
Formats matched rental listings and sends them as Telegram messages.
One message per listing — individual, not aggregated.
"""

import os
import logging
import requests

log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')


def format_message(listing: dict) -> str:
    """Format a matched listing into a Telegram message (Hebrew)."""
    parsed = listing.get('parsed', {})

    price = listing.get('price') or parsed.get('price')
    rooms = listing.get('rooms') or parsed.get('rooms')
    parking = listing.get('parking') if listing.get('parking') is not None else parsed.get('parking')
    safe_room = listing.get('safe_room') if listing.get('safe_room') is not None else parsed.get('safe_room')
    entry_date = listing.get('entry_date') or parsed.get('entry_date')
    summary = parsed.get('summary', '')
    post_url = listing.get('post_url', '')

    city = listing.get('city') or parsed.get('city') or ''
    neighborhood = listing.get('neighborhood') or parsed.get('neighborhood') or ''
    street = listing.get('street') or parsed.get('street') or ''

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

    price_line = f"💰 {price:,} ₪ לחודש" if price else "💰 מחיר לא צוין"

    if rooms:
        rooms_display = int(rooms) if rooms == int(rooms) else rooms
        rooms_line = f"🛏 {rooms_display} חדרים"
    else:
        rooms_line = "🛏 מספר חדרים לא צוין"

    if parking is True:
        parking_line = "🚗 חניה: ✅"
    elif parking is False:
        parking_line = "🚗 חניה: ❌"
    else:
        parking_line = "🚗 חניה: לא צוין"

    if safe_room is True:
        safe_room_line = '🛡 ממ"ד: ✅'
    elif safe_room is False:
        safe_room_line = '🛡 ממ"ד: ❌'
    else:
        safe_room_line = '🛡 ממ"ד: לא צוין'

    street_line = f"📍 {street}" if street else ""
    entry_line = f"📅 כניסה: {entry_date}" if entry_date else ""
    summary_line = f'"{summary}"' if summary else ""
    link_line = f"👉 [לצפייה במודעה]({post_url})" if post_url else ""

    lines = [
        f"🏠 דירה חדשה להשכרה — {location}",
        "",
        price_line,
        rooms_line,
        parking_line,
        safe_room_line,
    ]

    if street_line:
        lines.append(street_line)

    if entry_line:
        lines.append(entry_line)

    if summary_line:
        lines.append("")
        lines.append(summary_line)

    if link_line:
        lines.append("")
        lines.append(link_line)

    return "\n".join(lines)


def send_alert(listing: dict) -> bool:
    """Send a single listing alert to Telegram. Returns True if successful."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error('Telegram credentials not set — check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env')
        return False

    message = format_message(listing)
    image_urls = listing.get('image_urls', [])

    try:
        if len(image_urls) >= 2:
            media = [{'type': 'photo', 'media': image_urls[0], 'caption': message, 'parse_mode': 'Markdown'}]
            media += [{'type': 'photo', 'media': u} for u in image_urls[1:9]]
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup"
            resp = requests.post(url, json={'chat_id': TELEGRAM_CHAT_ID, 'media': media}, timeout=15)
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
        }, timeout=10)
        if resp.status_code == 200:
            log.info(f'Telegram text alert sent for {listing.get("id")}')
            return True
        log.error(f'Telegram API error {resp.status_code}: {resp.text}')
        return False

    except Exception as e:
        log.error(f'Failed to send Telegram alert: {e}')
        return False
