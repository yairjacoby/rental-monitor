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
    """Format a matched listing into a Telegram message."""
    parsed = listing.get('parsed', {})
    source = listing.get('source', 'unknown').capitalize()

    # Location line
    city = parsed.get('city') or ''
    neighborhood = parsed.get('neighborhood') or ''
    if city and neighborhood:
        location = f"{city}, {neighborhood}"
    elif city:
        location = city
    elif neighborhood:
        location = neighborhood
    else:
        location = 'Location not specified'

    # Price
    price = parsed.get('price')
    price_line = f"💰 {price:,} ₪/month" if price else "💰 Price not specified"

    # Rooms
    rooms = parsed.get('rooms')
    rooms_line = f"🛏 {rooms} rooms" if rooms else "🛏 Rooms not specified"

    # Parking
    parking = parsed.get('parking')
    if parking is True:
        parking_line = "🚗 Parking: ✅"
    elif parking is False:
        parking_line = "🚗 Parking: ❌"
    else:
        parking_line = "🚗 Parking: not specified"

    # Safe room
    safe_room = parsed.get('safe_room')
    if safe_room is True:
        safe_room_line = "🛡 Safe room: ✅"
    elif safe_room is False:
        safe_room_line = "🛡 Safe room: ❌"
    else:
        safe_room_line = "🛡 Safe room: not specified"

    # Entry date
    entry_date = parsed.get('entry_date')
    entry_line = f"📅 Entry: {entry_date}" if entry_date else ""

    # Summary
    summary = parsed.get('summary', '')
    summary_line = f'"{summary}"' if summary else ""

    # Post link
    post_url = listing.get('post_url', '')
    link_line = f"👉 [View post]({post_url})" if post_url else ""

    # Assemble message
    lines = [
        f"🏠 New Rental — {location}",
        f"📡 Source: {source}",
        "",
        price_line,
        rooms_line,
        parking_line,
        safe_room_line,
    ]

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

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        response = requests.post(url, json={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': False,
        }, timeout=10)

        if response.status_code == 200:
            log.info(f'Telegram alert sent for listing {listing.get("id")}')
            return True
        else:
            log.error(f'Telegram API error {response.status_code}: {response.text}')
            return False

    except Exception as e:
        log.error(f'Failed to send Telegram alert: {e}')
        return False
