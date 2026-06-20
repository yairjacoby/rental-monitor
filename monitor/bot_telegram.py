"""
Telegram Bot — Conversational Command Handler
Guides user through configuration with step-by-step questions.
Uses Claude API with web search to discover Facebook groups.
All changes require confirmation before taking effect.
"""

import logging
import os
import json
import anthropic
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from config_store import (
    add_city, remove_city, get_cities,
    add_neighborhood, remove_neighborhood,
    add_facebook_group, remove_facebook_group,
    set_filter, get_filter,
    set_paused, is_paused,
    get_config_summary,
)

log = logging.getLogger(__name__)

YAD2_CITIES = {
    'הוד השרון': {'city_id': '9700', 'region_id': '1'},
    'תל אביב': {'city_id': '5000', 'region_id': '3'},
    'ירושלים': {'city_id': '3000', 'region_id': '6'},
    'חיפה': {'city_id': '4000', 'region_id': '7'},
    'ראשון לציון': {'city_id': '8300', 'region_id': '3'},
    'פתח תקווה': {'city_id': '7900', 'region_id': '1'},
    'נתניה': {'city_id': '7400', 'region_id': '5'},
    'באר שבע': {'city_id': '1200', 'region_id': '2'},
    'רמת גן': {'city_id': '8600', 'region_id': '3'},
    'אשדוד': {'city_id': '70', 'region_id': '2'},
    'חולון': {'city_id': '6100', 'region_id': '3'},
    'בני ברק': {'city_id': '2400', 'region_id': '3'},
    'רחובות': {'city_id': '8400', 'region_id': '3'},
    'כפר סבא': {'city_id': '6900', 'region_id': '1'},
    'הרצליה': {'city_id': '6600', 'region_id': '1'},
    'רעננה': {'city_id': '8700', 'region_id': '1'},
    'מודיעין': {'city_id': '1020', 'region_id': '1'},
    'אשקלון': {'city_id': '300', 'region_id': '2'},
    'עפולה': {'city_id': '7700', 'region_id': '7'},
    'נצרת עילית': {'city_id': '7500', 'region_id': '7'},
    'גבעתיים': {'city_id': '6200', 'region_id': '3'},
}

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Conversation state per chat
_state = {}


def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
            await update.message.reply_text('Unauthorized.')
            return
        return await func(update, context)
    return wrapper


async def reply(update: Update, text: str):
    await update.message.reply_text(text, parse_mode='Markdown')


def get_state(chat_id) -> dict:
    return _state.get(chat_id, {})


def set_state(chat_id, state: dict):
    _state[chat_id] = state


def clear_state(chat_id):
    _state.pop(chat_id, None)


# ── Facebook group discovery ──────────────────────────────────────────────────

FACEBOOK_GROUPS_BY_CITY = {
    'הוד השרון': [
        {'name': 'דירות להשכרה הוד השרון 1', 'url': 'https://www.facebook.com/share/g/1EWSUWPM7i/'},
        {'name': 'דירות להשכרה הוד השרון 2', 'url': 'https://www.facebook.com/share/g/1ExG6YipWn/'},
        {'name': 'דירות להשכרה הוד השרון 3', 'url': 'https://www.facebook.com/share/g/1DLdauYUWD/'},
        {'name': 'דירות להשכרה הוד השרון 4', 'url': 'https://www.facebook.com/share/g/1DkXixfNZo/'},
        {'name': 'דירות להשכרה הוד השרון 5', 'url': 'https://www.facebook.com/share/g/18nvrayqZp/'},
    ],
}


def search_facebook_groups(city_name: str) -> list:
    """Return curated Facebook groups for a city, falling back to Claude web search."""
    curated = FACEBOOK_GROUPS_BY_CITY.get(city_name, [])
    if curated:
        log.info(f'Returning {len(curated)} curated groups for {city_name}')
        return curated

    # Web search fallback
    try:
        response = anthropic_client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=800,
            tools=[{'type': 'web_search_20250305'}],
            messages=[{
                'role': 'user',
                'content': (
                    f'Find public Facebook groups for renting apartments in {city_name}, Israel. '
                    f'Return ONLY a JSON array, no prose, no markdown fences. '
                    f'Format: [{{"name": "...", "url": "https://www.facebook.com/groups/..."}}]. '
                    f'If none found, return [].'
                )
            }]
        )
        for block in response.content:
            text = getattr(block, 'text', '')
            if not text:
                continue
            text = text.strip().lstrip('`').rstrip('`').strip()
            if text.lower().startswith('json'):
                text = text[4:].strip()
            start = text.find('[')
            end = text.rfind(']') + 1
            if start >= 0 and end > start:
                groups = json.loads(text[start:end])
                return [g for g in groups if 'facebook.com' in g.get('url', '')]
    except Exception as e:
        log.error(f'Facebook group search error: {e}')
    return []


# ── /help ─────────────────────────────────────────────────────────────────────

@owner_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, """
*Rental Monitor — Commands*

`/add_city` — add a city to monitor (guided)
`/remove_city` — remove a city
`/remove_neighborhood` — remove a neighborhood filter
`/set_price` — change max price
`/set_rooms` — change min rooms
`/add_group` — add a Facebook group URL
`/remove_group` — remove a Facebook group
`/pause` — pause monitoring
`/resume` — resume monitoring
`/status` — show current config
`/cancel` — cancel current action
`/help` — show this message
""")


# ── /status ───────────────────────────────────────────────────────────────────

@owner_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, get_config_summary())


# ── /add_city — guided flow ───────────────────────────────────────────────────

@owner_only
async def cmd_add_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_state(chat_id, {'flow': 'add_city', 'step': 'city_name', 'data': {}})
    await reply(update, '🏙 *Add a city*\n\nWhat city do you want to monitor?')


# ── /remove_city ──────────────────────────────────────────────────────────────

@owner_only
async def cmd_remove_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cities = get_cities()
    if not cities:
        await reply(update, 'No cities configured.')
        return
    chat_id = update.effective_chat.id
    city_list = '\n'.join(f'{i+1}. {c["name"]}' for i, c in enumerate(cities))
    set_state(chat_id, {'flow': 'remove_city', 'step': 'pick', 'cities': cities})
    await reply(update, f'Which city to remove?\n\n{city_list}\n\nReply with the number.')


# ── /remove_neighborhood ──────────────────────────────────────────────────────

@owner_only
async def cmd_remove_neighborhood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from config_store import get_neighborhoods
    cities = get_cities()
    all_neighborhoods = []
    for city in cities:
        for nbhd in get_neighborhoods(city['name']):
            all_neighborhoods.append({'city': city['name'], 'name': nbhd['name']})
    if not all_neighborhoods:
        await reply(update, 'No neighborhoods configured.')
        return
    chat_id = update.effective_chat.id
    listing = '\n'.join(f'{i+1}. {n["name"]} ({n["city"]})' for i, n in enumerate(all_neighborhoods))
    set_state(chat_id, {'flow': 'remove_neighborhood', 'step': 'pick', 'neighborhoods': all_neighborhoods})
    await reply(update, f'Which neighborhood to remove?\n\n{listing}\n\nReply with the number.')


# ── /set_price ────────────────────────────────────────────────────────────────

@owner_only
async def cmd_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_state(chat_id, {'flow': 'set_price', 'step': 'price'})
    current = get_filter('global_max_price', 'not set')
    await reply(update, f'Current max price: *{current}*\n\nEnter new max price in NIS:')


# ── /set_rooms ────────────────────────────────────────────────────────────────

@owner_only
async def cmd_set_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_state(chat_id, {'flow': 'set_rooms', 'step': 'rooms'})
    current = get_filter('rooms_min', '4')
    await reply(update, f'Current min rooms: *{current}*\n\nEnter new minimum rooms (e.g. 4 or 3.5):')


# ── /add_group ────────────────────────────────────────────────────────────────

@owner_only
async def cmd_add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_state(chat_id, {'flow': 'add_group_manual', 'step': 'url'})
    await reply(update, 'Paste the Facebook group URL:')


# ── /remove_group ─────────────────────────────────────────────────────────────

@owner_only
async def cmd_remove_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from config_store import get_facebook_groups
    groups = get_facebook_groups()
    if not groups:
        await reply(update, 'No Facebook groups configured.')
        return
    chat_id = update.effective_chat.id
    group_list = '\n'.join(f'{i+1}. {url}' for i, url in enumerate(groups))
    set_state(chat_id, {'flow': 'remove_group', 'step': 'pick', 'groups': groups})
    await reply(update, f'Which group to remove?\n\n{group_list}\n\nReply with the number.')


# ── /pause and /resume ────────────────────────────────────────────────────────

@owner_only
async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_state(chat_id, {'flow': 'pause', 'step': 'confirm'})
    await reply(update, 'Pause monitoring? Reply /confirm or /cancel')


@owner_only
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_state(chat_id, {'flow': 'resume', 'step': 'confirm'})
    await reply(update, 'Resume monitoring? Reply /confirm or /cancel')


# ── /cancel ───────────────────────────────────────────────────────────────────

@owner_only
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_state(update.effective_chat.id)
    await reply(update, 'Cancelled.')


# ── /confirm ──────────────────────────────────────────────────────────────────

@owner_only
async def cmd_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    if not state or state.get('step') != 'confirm':
        await reply(update, 'Nothing to confirm.')
        return
    await handle_confirmation(update, state)


async def handle_confirmation(update: Update, state: dict):
    chat_id = update.effective_chat.id
    flow = state.get('flow')
    data = state.get('data', {})

    if flow == 'add_city':
        city_name = data['city_name']
        add_city(
            city_name,
            yad2_city_id=data.get('yad2_city_id'),
            yad2_region_id=data.get('yad2_region_id'),
            max_price=data.get('max_price')
        )
        if data.get('neighborhood'):
            add_neighborhood(city_name, data['neighborhood'])
        # City saved — now offer Facebook group addition as a separate step
        set_state(chat_id, {'flow': 'add_groups', 'step': 'url', 'data': {'city_name': city_name, 'facebook_groups': []}})
        await reply(update, (
            f'✅ *{city_name}* added. Monitoring starts next cycle.\n\n'
            f'Paste Facebook group URLs to monitor (one per message), or /skip to finish.'
        ))

    elif flow == 'remove_city':
        remove_city(data['city_name'])
        clear_state(chat_id)
        await reply(update, f"✅ *{data['city_name']}* removed.")

    elif flow == 'remove_neighborhood':
        remove_neighborhood(data['city_name'], data['name'])
        clear_state(chat_id)
        await reply(update, f"✅ Neighborhood *{data['name']}* removed from {data['city_name']}.")

    elif flow == 'set_price':
        set_filter('global_max_price', str(data['price']))
        clear_state(chat_id)
        await reply(update, f"✅ Max price set to *{data['price']:,} ₪*.")

    elif flow == 'set_rooms':
        set_filter('rooms_min', str(data['rooms']))
        clear_state(chat_id)
        await reply(update, f"✅ Min rooms set to *{data['rooms']}*.")

    elif flow == 'pause':
        set_paused(True)
        clear_state(chat_id)
        await reply(update, '⏸ Monitoring paused.')

    elif flow == 'resume':
        set_paused(False)
        clear_state(chat_id)
        await reply(update, '✅ Monitoring resumed.')

    elif flow == 'add_group_manual':
        url = data.get('url') or state.get('data', {}).get('url', '')
        if url:
            add_facebook_group(url)
            clear_state(chat_id)
            await reply(update, f"✅ Facebook group added.\n{url}")
        else:
            clear_state(chat_id)
            await reply(update, "❌ No URL found — please try /add\\_group again.")


# ── Message handler — routes conversation steps ───────────────────────────────

@owner_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    text = update.message.text.strip()

    if not state:
        await reply(update, 'Use /help to see available commands.')
        return

    flow = state.get('flow')
    step = state.get('step')
    data = state.setdefault('data', {})

    # ── add_city flow ──────────────────────────────────────────────────────────
    if flow == 'add_city':

        if step == 'city_name':
            data['city_name'] = text
            yad2_info = YAD2_CITIES.get(text, {})
            data['yad2_city_id'] = yad2_info.get('city_id')
            data['yad2_region_id'] = yad2_info.get('region_id')
            state['step'] = 'max_price'
            set_state(chat_id, state)
            await reply(update, f'*{text}* — got it.\n\nMax price in NIS? (or /skip for no limit)')

        elif step == 'max_price':
            if text.isdigit():
                data['max_price'] = int(text)
            state['step'] = 'rooms'
            set_state(chat_id, state)
            await reply(update, 'Min number of rooms? (e.g. 4 or 3.5)')

        elif step == 'rooms':
            try:
                data['rooms'] = float(text)
            except ValueError:
                await reply(update, 'Please enter a number like 4 or 3.5')
                return
            state['step'] = 'neighborhood'
            set_state(chat_id, state)
            await reply(update, 'Specific neighborhood? (or /skip for whole city)')

        elif step == 'neighborhood':
            if text not in ('/skip',):
                data['neighborhood'] = text
            state['step'] = 'must_have'
            set_state(chat_id, state)
            await reply(update, 'Must-haves?\n\n1. Parking\n2. Safe room ממ"ד\n3. Both\n4. Neither')

        elif step == 'must_have':
            if text == '1':
                data['parking'] = True
            elif text == '2':
                data['safe_room'] = True
            elif text == '3':
                data['parking'] = True
                data['safe_room'] = True
            # Build summary and go straight to confirm — Facebook groups added after
            city_name = data.get('city_name', '')
            max_price = data.get('max_price')
            rooms = data.get('rooms', get_filter('rooms_min', '4'))
            nbhd = data.get('neighborhood', 'whole city')
            parking = '✅' if data.get('parking') else '—'
            safe_room = '✅' if data.get('safe_room') else '—'
            price_str = f'{max_price:,} ₪' if max_price else 'no limit'
            state['step'] = 'confirm'
            set_state(chat_id, state)
            await reply(update, (
                f'*Summary — {city_name}*\n\n'
                f'💰 Max price: {price_str}\n'
                f'🛏 Min rooms: {rooms}\n'
                f'📍 Neighborhood: {nbhd}\n'
                f'🚗 Parking: {parking}\n'
                f'🛡 Safe room: {safe_room}\n\n'
                f'/confirm to save or /cancel to abort'
            ))

        elif step == 'confirm':
            pass

    # ── add_groups flow (post-city-confirm Facebook group collection) ──────────
    elif flow == 'add_groups':
        if step == 'url':
            if text.startswith('http') and 'facebook.com' in text:
                add_facebook_group(text)
                data['facebook_groups'].append(text)
                set_state(chat_id, state)
                count = len(data['facebook_groups'])
                await reply(update, f'✅ Group {count} added. Paste another URL or /done to finish.')
            else:
                await reply(update, 'Please paste a valid Facebook group URL, or /done to finish.')

    # ── remove_city flow ───────────────────────────────────────────────────────
    elif flow == 'remove_city':
        if step == 'pick':
            cities = state.get('cities', [])
            try:
                idx = int(text) - 1
                city = cities[idx]
                data['city_name'] = city['name']
                state['step'] = 'confirm'
                set_state(chat_id, state)
                await reply(update, f'Remove *{city["name"]}*? /confirm or /cancel')
            except (ValueError, IndexError):
                await reply(update, 'Please reply with a valid number.')

    # ── remove_neighborhood flow ───────────────────────────────────────────────
    elif flow == 'remove_neighborhood':
        if step == 'pick':
            neighborhoods = state.get('neighborhoods', [])
            try:
                idx = int(text) - 1
                nbhd = neighborhoods[idx]
                data['city_name'] = nbhd['city']
                data['name'] = nbhd['name']
                state['step'] = 'confirm'
                set_state(chat_id, state)
                await reply(update, f'Remove *{nbhd["name"]}* from {nbhd["city"]}? /confirm or /cancel')
            except (ValueError, IndexError):
                await reply(update, 'Please reply with a valid number.')

    # ── set_price flow ─────────────────────────────────────────────────────────
    elif flow == 'set_price':
        if step == 'price':
            if text.isdigit():
                data['price'] = int(text)
                state['step'] = 'confirm'
                set_state(chat_id, state)
                await reply(update, f'Set max price to *{int(text):,} ₪*? /confirm or /cancel')
            else:
                await reply(update, 'Please enter a number like 13000')

    # ── set_rooms flow ─────────────────────────────────────────────────────────
    elif flow == 'set_rooms':
        if step == 'rooms':
            try:
                data['rooms'] = float(text)
                state['step'] = 'confirm'
                set_state(chat_id, state)
                await reply(update, f'Set min rooms to *{float(text)}*? /confirm or /cancel')
            except ValueError:
                await reply(update, 'Please enter a number like 4 or 3.5')

    # ── add_group_manual flow ──────────────────────────────────────────────────
    elif flow == 'add_group_manual':
        if step == 'url':
            if text.startswith('http') and 'facebook.com' in text:
                data['url'] = text
                state['data'] = data
                state['step'] = 'confirm'
                set_state(chat_id, state)
                await reply(update, f'Add group:\n`{text}`?\n/confirm or /cancel')
            else:
                await reply(update, 'Please paste a valid Facebook group URL.')

    # ── remove_group flow ──────────────────────────────────────────────────────
    elif flow == 'remove_group':
        if step == 'pick':
            groups = state.get('groups', [])
            try:
                idx = int(text) - 1
                url = groups[idx]
                data['url'] = url
                state['step'] = 'confirm'
                set_state(chat_id, state)
                await reply(update, f'Remove group:\n`{url}`?\n/confirm or /cancel')
            except (ValueError, IndexError):
                await reply(update, 'Please reply with a valid number.')


# ── /done — ends manual URL entry and shows summary ──────────────────────────

@owner_only
async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    if not state:
        await reply(update, 'Nothing in progress.')
        return

    flow = state.get('flow')
    data = state.get('data', {})

    if flow == 'add_groups':
        count = len(data.get('facebook_groups', []))
        clear_state(chat_id)
        if count:
            await reply(update, f'✅ Done — {count} Facebook group{"s" if count != 1 else ""} added.')
        else:
            await reply(update, '✅ Done. Use /add\\_group to add groups later.')
    else:
        await reply(update, 'Use /cancel to exit.')


# ── /skip handler ─────────────────────────────────────────────────────────────

@owner_only
async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    if not state:
        await reply(update, 'Nothing in progress.')
        return

    flow = state.get('flow')
    step = state.get('step')
    data = state.setdefault('data', {})

    if flow == 'add_city':
        if step == 'max_price':
            state['step'] = 'rooms'
            set_state(chat_id, state)
            await reply(update, 'Min number of rooms? (e.g. 4 or 3.5)')

        elif step == 'neighborhood':
            state['step'] = 'must_have'
            set_state(chat_id, state)
            await reply(update, 'Must-haves?\n\n1. Parking\n2. Safe room ממ"ד\n3. Both\n4. Neither')

        else:
            await reply(update, 'Nothing to skip here.')
    elif flow == 'add_groups':
        clear_state(chat_id)
        await reply(update, '✅ Done. Use /add\\_group to add groups later.')
    else:
        await reply(update, 'Nothing to skip.')


@owner_only
async def cmd_search_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    if state and state.get('flow') == 'add_city':
        # Manually trigger the search_groups step
        state['step'] = 'facebook_search'
        set_state(chat_id, state)
        # Create a fake update text and call handle_message
        class FakeMessage:
            text = '/search_groups'
            async def reply_text(self, *args, **kwargs):
                await update.message.reply_text(*args, **kwargs)
        class FakeUpdate:
            message = FakeMessage()
            effective_chat = update.effective_chat
        await handle_message(FakeUpdate(), context)
    else:
        await reply(update, 'Use /add\\_city first to set up a city, then search for groups.')


# ── Bot startup ───────────────────────────────────────────────────────────────

def build_bot() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler('help', cmd_help))
    app.add_handler(CommandHandler('status', cmd_status))
    app.add_handler(CommandHandler('add_city', cmd_add_city))
    app.add_handler(CommandHandler('remove_city', cmd_remove_city))
    app.add_handler(CommandHandler('remove_neighborhood', cmd_remove_neighborhood))
    app.add_handler(CommandHandler('set_price', cmd_set_price))
    app.add_handler(CommandHandler('set_rooms', cmd_set_rooms))
    app.add_handler(CommandHandler('add_group', cmd_add_group))
    app.add_handler(CommandHandler('remove_group', cmd_remove_group))
    app.add_handler(CommandHandler('pause', cmd_pause))
    app.add_handler(CommandHandler('resume', cmd_resume))
    app.add_handler(CommandHandler('confirm', cmd_confirm))
    app.add_handler(CommandHandler('cancel', cmd_cancel))
    app.add_handler(CommandHandler('done', cmd_done))
    app.add_handler(CommandHandler('skip', cmd_skip))
    app.add_handler(CommandHandler('search_groups', cmd_search_groups))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
