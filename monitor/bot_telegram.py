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


# ── Facebook group discovery via Claude API ───────────────────────────────────

def search_facebook_groups(city_name: str) -> list[dict]:
    """Use Claude API with web search to find public Facebook rental groups."""
    try:
        response = anthropic_client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=1000,
            tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
            messages=[{
                'role': 'user',
                'content': (
                    f'Find public Facebook groups for renting apartments in {city_name}, Israel. '
                    f'Search for: קבוצות פייסבוק דירות להשכרה {city_name} '
                    f'Return a JSON array of objects with fields: name, url, members (estimated). '
                    f'Only include actual Facebook group URLs (facebook.com/groups/). '
                    f'Return ONLY valid JSON array, no explanation. '
                    f'Example: [{{"name": "דירות הוד השרון", "url": "https://www.facebook.com/groups/123", "members": "12000"}}]'
                )
            }]
        )

        # Extract text from response
        text = ''
        for block in response.content:
            if hasattr(block, 'text'):
                text += block.text

        # Parse JSON from response
        text = text.strip()
        start = text.find('[')
        end = text.rfind(']') + 1
        if start >= 0 and end > start:
            groups = json.loads(text[start:end])
            return [g for g in groups if 'facebook.com' in g.get('url', '')]
        return []

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
        add_city(
            data['city_name'],
            max_price=data.get('max_price')
        )
        if data.get('neighborhood'):
            add_neighborhood(data['city_name'], data['neighborhood'])
        for url in data.get('facebook_groups', []):
            add_facebook_group(url)
        clear_state(chat_id)
        await reply(update, f"✅ *{data['city_name']}* added. Monitoring starts next cycle.")

    elif flow == 'remove_city':
        remove_city(data['city_name'])
        clear_state(chat_id)
        await reply(update, f"✅ *{data['city_name']}* removed.")

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
            state['step'] = 'facebook_search'
            state['data']['facebook_groups'] = []
            set_state(chat_id, state)
            await reply(update,
                f'Want me to search for public Facebook rental groups in *{data["city_name"]}*?\n\n'
                f'Reply /search\\_groups or /skip'
            )

        elif step == 'facebook_search':
            if text in ('/skip', 'skip'):
                state['step'] = 'confirm'
                set_state(chat_id, state)
                await cmd_done(update, context)
                return
            if text == '/search_groups':
                await reply(update, f'Searching for Facebook groups in {data["city_name"]}...')
                groups = search_facebook_groups(data['city_name'])
                if groups:
                    state['found_groups'] = groups
                    group_list = '\n'.join(
                        f'{i+1}. {g["name"]} ({g.get("members", "?")} members)\n   {g["url"]}'
                        for i, g in enumerate(groups)
                    )
                    state['step'] = 'facebook_pick'
                    set_state(chat_id, state)
                    await reply(update,
                        f'Found these groups:\n\n{group_list}\n\n'
                        f'Reply with numbers (e.g. `1 2`), `all`, or /skip'
                    )
                else:
                    state['step'] = 'facebook_manual'
                    set_state(chat_id, state)
                    await reply(update,
                        'Could not find groups automatically.\n\n'
                        'Paste any Facebook group URLs you want to add (one per message), or /skip'
                    )
            else:
                state['step'] = 'facebook_manual'
                set_state(chat_id, state)
                await reply(update,
                    'Paste any Facebook group URLs you want to add (one per message), or /skip'
                )

        elif step == 'facebook_pick':
            groups = state.get('found_groups', [])
            if text.lower() == 'all':
                selected = groups
            else:
                try:
                    indices = [int(x) - 1 for x in text.split()]
                    selected = [groups[i] for i in indices if 0 <= i < len(groups)]
                except ValueError:
                    await reply(update, 'Please reply with numbers like `1 2` or `all`')
                    return
            for g in selected:
                data['facebook_groups'].append(g['url'])
            state['step'] = 'facebook_manual'
            set_state(chat_id, state)
            count = len(selected)
            await reply(update,
                f'✅ {count} group{"s" if count != 1 else ""} selected.\n\n'
                f'Any additional group URLs to add? Paste one per message, or /done'
            )

        elif step == 'facebook_manual':
            if text.startswith('http') and 'facebook.com' in text:
                data['facebook_groups'].append(text)
                await reply(update, '✅ Added. Paste another URL or /done')
            else:
                await reply(update, 'Please paste a valid Facebook URL or /done')

        elif step == 'confirm':
            pass

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

    if flow == 'add_city' and state.get('step') in ('facebook_manual', 'facebook_pick'):
        # Show summary and ask for confirmation
        city_name = data.get('city_name', '')
        max_price = data.get('max_price')
        rooms = data.get('rooms', get_filter('rooms_min', '4'))
        neighborhood = data.get('neighborhood', 'whole city')
        parking = '✅' if data.get('parking') else '—'
        safe_room = '✅' if data.get('safe_room') else '—'
        groups = data.get('facebook_groups', [])

        price_str = f'{max_price:,} ₪' if max_price else 'no limit'
        groups_str = f'{len(groups)} group{"s" if len(groups) != 1 else ""}' if groups else 'none'

        state['step'] = 'confirm'
        set_state(chat_id, state)

        await reply(update, f"""
*Summary — {city_name}*

💰 Max price: {price_str}
🛏 Min rooms: {rooms}
📍 Neighborhood: {neighborhood}
🚗 Parking: {parking}
🛡 Safe room: {safe_room}
👥 Facebook groups: {groups_str}

/confirm to save or /cancel to abort
""")
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

        elif step in ('facebook_search', 'facebook_pick', 'facebook_manual'):
            data['facebook_groups'] = data.get('facebook_groups', [])
            state['step'] = 'facebook_manual'
            set_state(chat_id, state)
            await cmd_done(update, context)

        else:
            await reply(update, 'Nothing to skip here.')
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
