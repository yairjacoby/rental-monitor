"""
Telegram Bot — Hebrew UI with inline keyboards and natural language understanding.
"""

import logging
import os
import json
import anthropic
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from config_store import (
    add_city, remove_city, get_cities,
    add_neighborhood, remove_neighborhood,
    add_facebook_group, remove_facebook_group,
    set_filter, get_filter,
    set_paused, is_paused,
    get_config_summary,
    get_neighborhoods, get_facebook_groups,
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

_state = {}


# ── Core helpers ──────────────────────────────────────────────────────────────

def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if str(update.effective_chat.id) != str(TELEGRAM_CHAT_ID):
            await update.message.reply_text('לא מורשה.')
            return
        return await func(update, context)
    return wrapper


def kb(*rows):
    """Build InlineKeyboardMarkup. Each row is a list of (label, callback_data) tuples."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t, callback_data=d) for t, d in row]
        for row in rows
    ])


async def reply(update: Update, text: str, markup=None):
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=markup)


async def qreply(query, text: str, markup=None):
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=markup)


def get_state(chat_id) -> dict:
    return _state.get(chat_id, {})


def set_state(chat_id, state: dict):
    _state[chat_id] = state


def clear_state(chat_id):
    _state.pop(chat_id, None)


# ── NLU — keyword map + Claude Haiku fallback ─────────────────────────────────

KEYWORD_INTENTS = {
    # add_city
    'הוסף עיר': 'add_city', 'הוספת עיר': 'add_city', 'עיר חדשה': 'add_city',
    'להוסיף עיר': 'add_city', 'רוצה להוסיף עיר': 'add_city',
    'אני רוצה להוסיף עיר': 'add_city', 'רוצה לעקוב': 'add_city',
    'עקוב אחרי עיר': 'add_city', 'עקוב אחר עיר': 'add_city',
    'add city': 'add_city', 'add a city': 'add_city', 'new city': 'add_city',
    'monitor city': 'add_city', 'track city': 'add_city', 'watch city': 'add_city',
    # remove_city
    'הסר עיר': 'remove_city', 'הסרת עיר': 'remove_city', 'מחק עיר': 'remove_city',
    'להסיר עיר': 'remove_city', 'רוצה להסיר עיר': 'remove_city',
    'בטל עיר': 'remove_city', 'הפסק לעקוב': 'remove_city',
    'remove city': 'remove_city', 'delete city': 'remove_city', 'stop monitoring': 'remove_city',
    # remove_neighborhood
    'הסר שכונה': 'remove_neighborhood', 'מחק שכונה': 'remove_neighborhood',
    'להסיר שכונה': 'remove_neighborhood', 'רוצה להסיר שכונה': 'remove_neighborhood',
    'remove neighborhood': 'remove_neighborhood', 'delete neighborhood': 'remove_neighborhood',
    # set_price
    'שנה מחיר': 'set_price', 'עדכן מחיר': 'set_price', 'מחיר מקסימאלי': 'set_price',
    'לשנות מחיר': 'set_price', 'רוצה לשנות מחיר': 'set_price', 'לעדכן מחיר': 'set_price',
    'כמה לשלם': 'set_price', 'תקציב': 'set_price',
    'set price': 'set_price', 'max price': 'set_price', 'budget': 'set_price',
    'change price': 'set_price', 'update price': 'set_price', 'price limit': 'set_price',
    # set_rooms
    'שנה חדרים': 'set_rooms', 'עדכן חדרים': 'set_rooms', 'מינימום חדרים': 'set_rooms',
    'לשנות חדרים': 'set_rooms', 'רוצה לשנות חדרים': 'set_rooms', 'לעדכן חדרים': 'set_rooms',
    'כמה חדרים': 'set_rooms',
    'set rooms': 'set_rooms', 'min rooms': 'set_rooms', 'rooms minimum': 'set_rooms',
    'change rooms': 'set_rooms', 'update rooms': 'set_rooms',
    # add_group
    'הוסף קבוצה': 'add_group', 'הוסף קבוצת פייסבוק': 'add_group',
    'להוסיף קבוצה': 'add_group', 'להוסיף קבוצות': 'add_group',
    'קבוצות פייסבוק': 'add_group', 'קבוצת פייסבוק': 'add_group',
    'רוצה להוסיף קבוצה': 'add_group', 'רוצה להוסיף קבוצות': 'add_group',
    'להוסיף קבוצת פייסבוק': 'add_group', 'להוסיף קבוצות פייסבוק': 'add_group',
    'קבוצה חדשה': 'add_group', 'הוסף פייסבוק': 'add_group',
    'add group': 'add_group', 'add facebook group': 'add_group', 'new group': 'add_group',
    'facebook group': 'add_group', 'add fb group': 'add_group',
    # remove_group
    'הסר קבוצה': 'remove_group', 'מחק קבוצה': 'remove_group',
    'להסיר קבוצה': 'remove_group', 'להסיר קבוצות': 'remove_group',
    'רוצה להסיר קבוצה': 'remove_group',
    'remove group': 'remove_group', 'delete group': 'remove_group',
    # pause
    'עצור': 'pause', 'השהה': 'pause', 'הפסק': 'pause', 'עצור ניטור': 'pause',
    'לעצור': 'pause', 'רוצה לעצור': 'pause', 'לעצור ניטור': 'pause',
    'pause': 'pause', 'stop': 'pause', 'disable': 'pause', 'turn off': 'pause',
    # resume
    'המשך': 'resume', 'הפעל': 'resume', 'המשך ניטור': 'resume',
    'להמשיך': 'resume', 'רוצה להמשיך': 'resume', 'להפעיל': 'resume',
    'resume': 'resume', 'enable': 'resume', 'turn on': 'resume',
    # status
    'מה המצב': 'status', 'סטטוס': 'status', 'הגדרות': 'status', 'מה מוגדר': 'status',
    'הצג הגדרות': 'status', 'מה יש': 'status', 'מה קורה': 'status', 'מה הסטטוס': 'status',
    'רוצה לראות סטטוס': 'status',
    'status': 'status', 'settings': 'status', 'show config': 'status',
    'what is set': 'status', 'current config': 'status', 'show settings': 'status',
    # help
    'עזרה': 'help', 'פקודות': 'help', 'מה אפשר': 'help', 'תפריט': 'help',
    'help': 'help', 'commands': 'help', 'what can you do': 'help', 'menu': 'help',
}

INTENT_SYSTEM = (
    'Classify the user message into one intent. Reply ONLY with valid JSON, nothing else.\n'
    'Intents: add_city, remove_city, remove_neighborhood, set_price, set_rooms, '
    'add_group, remove_group, pause, resume, status, help, unknown\n'
    'Include extracted values when present.\n'
    'Examples:\n'
    '"הסר את תל אביב" → {"intent":"remove_city","city_name":"תל אביב"}\n'
    '"שנה מחיר ל-15000" → {"intent":"set_price","price":15000}\n'
    '"what can you do" → {"intent":"help"}'
)


def match_keyword(text: str):
    lower = text.lower().strip()
    for kw, intent in KEYWORD_INTENTS.items():
        if kw in lower:
            return intent
    return None


async def classify_intent(text: str) -> dict:
    try:
        resp = anthropic_client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=80,
            system=INTENT_SYSTEM,
            messages=[{'role': 'user', 'content': text}]
        )
        return json.loads(resp.content[0].text.strip())
    except Exception as e:
        log.warning(f'Intent classification failed: {e}')
        return {'intent': 'unknown'}


MAIN_MENU_MARKUP = kb(
    [('🏙 הוסף עיר', 'nl|add_city'), ('📊 סטטוס', 'nl|status')],
    [('💰 שנה מחיר', 'nl|set_price'), ('🛏 שנה חדרים', 'nl|set_rooms')],
    [('📘 הוסף קבוצת פייסבוק', 'nl|add_group')],
    [('⏸ השהה', 'nl|pause'), ('▶️ המשך', 'nl|resume')],
)


async def _route_intent(update: Update, context, intent: str, intent_data: dict):
    if intent == 'add_city':
        await cmd_add_city(update, context)
    elif intent == 'remove_city':
        await cmd_remove_city(update, context)
    elif intent == 'remove_neighborhood':
        await cmd_remove_neighborhood(update, context)
    elif intent == 'status':
        await cmd_status(update, context)
    elif intent == 'set_price':
        price = intent_data.get('price')
        if price:
            set_filter('global_max_price', str(int(price)))
            await reply(update, f'✅ מחיר מקסימאלי עודכן ל-*{int(price):,} ₪*.')
        else:
            await cmd_set_price(update, context)
    elif intent == 'set_rooms':
        rooms = intent_data.get('rooms')
        if rooms:
            set_filter('rooms_min', str(float(rooms)))
            await reply(update, f'✅ מינימום חדרים עודכן ל-*{float(rooms)}*.')
        else:
            await cmd_set_rooms(update, context)
    elif intent == 'add_group':
        await cmd_add_group(update, context)
    elif intent == 'remove_group':
        await cmd_remove_group(update, context)
    elif intent == 'pause':
        await cmd_pause(update, context)
    elif intent == 'resume':
        await cmd_resume(update, context)
    elif intent == 'help':
        await cmd_help(update, context)


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
    curated = FACEBOOK_GROUPS_BY_CITY.get(city_name, [])
    if curated:
        log.info(f'Returning {len(curated)} curated groups for {city_name}')
        return curated
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


# ── City summary helper ───────────────────────────────────────────────────────

def _build_city_summary(data: dict) -> str:
    city_name = data.get('city_name', '')
    max_price = data.get('max_price')
    rooms = data.get('rooms', get_filter('rooms_min', '4'))
    nbhd = data.get('neighborhood', 'כל העיר')
    parking = '✅' if data.get('parking') else '—'
    safe_room = '✅' if data.get('safe_room') else '—'
    price_str = f'{max_price:,} ₪' if max_price else 'ללא הגבלה'
    return (
        f'*סיכום — {city_name}*\n\n'
        f'💰 מחיר מקסימאלי: {price_str}\n'
        f'🛏 מינימום חדרים: {rooms}\n'
        f'📍 שכונה: {nbhd}\n'
        f'🚗 חניה: {parking}\n'
        f'🛡 ממ"ד: {safe_room}'
    )


# ── Confirmation logic ────────────────────────────────────────────────────────

async def _do_confirmation(query_or_update, chat_id: int, state: dict):
    flow = state.get('flow')
    data = state.get('data', {})
    is_query = hasattr(query_or_update, 'edit_message_text')

    async def edit(text):
        if is_query:
            await query_or_update.edit_message_text(text, parse_mode='Markdown')
        else:
            await query_or_update.message.reply_text(text, parse_mode='Markdown')

    async def send_new(text):
        msg = query_or_update.message
        await msg.reply_text(text, parse_mode='Markdown')

    if flow == 'add_city':
        city_name = data['city_name']
        add_city(city_name, yad2_city_id=data.get('yad2_city_id'),
                 yad2_region_id=data.get('yad2_region_id'), max_price=data.get('max_price'))
        if data.get('neighborhood'):
            add_neighborhood(city_name, data['neighborhood'])
        set_state(chat_id, {'flow': 'add_groups', 'step': 'url',
                             'data': {'city_name': city_name, 'facebook_groups': []}})
        await edit(f'✅ *{city_name}* נוספה. הניטור יתחיל במחזור הבא.')
        await send_new('הדבק כתובות קבוצות פייסבוק (אחת בהודעה), או /done לסיום.')

    elif flow == 'remove_city':
        remove_city(data['city_name'])
        clear_state(chat_id)
        await edit(f"✅ *{data['city_name']}* הוסרה.")

    elif flow == 'remove_neighborhood':
        remove_neighborhood(data['city_name'], data['name'])
        clear_state(chat_id)
        await edit(f"✅ שכונה *{data['name']}* הוסרה מ-{data['city_name']}.")

    elif flow == 'remove_group':
        remove_facebook_group(data['url'])
        clear_state(chat_id)
        await edit('✅ הקבוצה הוסרה.')

    elif flow == 'pause':
        set_paused(True)
        clear_state(chat_id)
        await edit('⏸ הניטור הושהה.')

    elif flow == 'resume':
        set_paused(False)
        clear_state(chat_id)
        await edit('▶️ הניטור חודש.')


# ── Callback handler ──────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if str(query.from_user.id) != str(TELEGRAM_CHAT_ID):
        await query.answer('לא מורשה.')
        return
    await query.answer()

    chat_id = query.message.chat_id
    state = get_state(chat_id)
    action, _, value = query.data.partition('|')

    if action == 'nl':
        await qreply(query, '👍')
        if value == 'add_city':
            set_state(chat_id, {'flow': 'add_city', 'step': 'city_name', 'data': {}})
            await query.message.reply_text('🏙 *הוספת עיר*\n\nאיזו עיר תרצה לעקוב אחריה?',
                                           parse_mode='Markdown')
        elif value == 'status':
            await query.message.reply_text(get_config_summary(), parse_mode='Markdown')
        elif value == 'set_price':
            set_state(chat_id, {'flow': 'set_price', 'step': 'price', 'data': {}})
            current = get_filter('global_max_price', 'לא מוגדר')
            await query.message.reply_text(f'מחיר נוכחי: *{current}*\n\nמחיר מקסימאלי חדש ב-₪?',
                                           parse_mode='Markdown')
        elif value == 'set_rooms':
            set_state(chat_id, {'flow': 'set_rooms', 'step': 'rooms', 'data': {}})
            current = get_filter('rooms_min', '4')
            await query.message.reply_text(f'מינימום נוכחי: *{current}*\n\nמינימום חדרים חדש?',
                                           parse_mode='Markdown')
        elif value == 'add_group':
            set_state(chat_id, {'flow': 'add_group_manual', 'step': 'url', 'data': {}})
            await query.message.reply_text('הדבק כתובת קבוצת הפייסבוק:', parse_mode='Markdown')
        elif value == 'pause':
            set_state(chat_id, {'flow': 'pause', 'step': 'confirm', 'data': {}})
            await query.message.reply_text(
                'להשהות את הניטור?', parse_mode='Markdown',
                reply_markup=kb([('⏸ השהה', 'confirm|yes'), ('❌ ביטול', 'confirm|no')]))
        elif value == 'resume':
            set_state(chat_id, {'flow': 'resume', 'step': 'confirm', 'data': {}})
            await query.message.reply_text(
                'להמשיך את הניטור?', parse_mode='Markdown',
                reply_markup=kb([('▶️ המשך', 'confirm|yes'), ('❌ ביטול', 'confirm|no')]))

    elif action == 'skip':
        data = state.setdefault('data', {})
        if value == 'max_price':
            state['step'] = 'rooms'
            set_state(chat_id, state)
            await qreply(query, '⏩ דולג\n\nמינימום חדרים? (לדוגמה: 4 או 3.5)')
        elif value == 'neighborhood':
            state['step'] = 'must_have'
            set_state(chat_id, state)
            await qreply(query, '⏩ דולג\n\nדרישות חובה?',
                         kb([('🚗 חניה', 'must_have|parking'), ('🛡 ממ"ד', 'must_have|safe_room')],
                            [('✅ שניהם', 'must_have|both'), ('➡️ ללא', 'must_have|neither')]))

    elif action == 'pick':
        idx = int(value)
        flow = state.get('flow')
        data = state.setdefault('data', {})

        if flow == 'remove_city':
            cities = state.get('cities', [])
            if idx >= len(cities):
                await qreply(query, '❌ בחירה לא תקינה.')
                return
            city = cities[idx]
            data['city_name'] = city['name']
            state['step'] = 'confirm'
            set_state(chat_id, state)
            await qreply(query, f'להסיר את *{city["name"]}*?',
                         kb([('✅ כן, הסר', 'confirm|yes'), ('❌ ביטול', 'confirm|no')]))

        elif flow == 'remove_neighborhood':
            neighborhoods = state.get('neighborhoods', [])
            if idx >= len(neighborhoods):
                await qreply(query, '❌ בחירה לא תקינה.')
                return
            nbhd = neighborhoods[idx]
            data['city_name'] = nbhd['city']
            data['name'] = nbhd['name']
            state['step'] = 'confirm'
            set_state(chat_id, state)
            await qreply(query, f'להסיר את *{nbhd["name"]}* מ-{nbhd["city"]}?',
                         kb([('✅ כן, הסר', 'confirm|yes'), ('❌ ביטול', 'confirm|no')]))

        elif flow == 'remove_group':
            groups = state.get('groups', [])
            if idx >= len(groups):
                await qreply(query, '❌ בחירה לא תקינה.')
                return
            url = groups[idx]
            data['url'] = url
            state['step'] = 'confirm'
            set_state(chat_id, state)
            short = url[:50] + '…' if len(url) > 50 else url
            await qreply(query, f'להסיר קבוצה?\n`{short}`',
                         kb([('✅ כן, הסר', 'confirm|yes'), ('❌ ביטול', 'confirm|no')]))

    elif action == 'must_have':
        data = state.setdefault('data', {})
        if value == 'parking':
            data['parking'] = True
        elif value == 'safe_room':
            data['safe_room'] = True
        elif value == 'both':
            data['parking'] = True
            data['safe_room'] = True
        summary = _build_city_summary(data)
        state['step'] = 'confirm'
        set_state(chat_id, state)
        await qreply(query, summary,
                     kb([('✅ שמור', 'confirm|yes'), ('❌ בטל', 'confirm|no')]))

    elif action == 'confirm':
        if value == 'no':
            clear_state(chat_id)
            await qreply(query, '❌ בוטל.')
        else:
            await _do_confirmation(query, chat_id, state)


# ── /help ─────────────────────────────────────────────────────────────────────

@owner_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, (
        '*ניטור דירות — פקודות*\n\n'
        '/add\\_city — הוספת עיר לניטור\n'
        '/remove\\_city — הסרת עיר\n'
        '/remove\\_neighborhood — הסרת שכונה\n'
        '/set\\_price — שינוי מחיר מקסימאלי\n'
        '/set\\_rooms — שינוי מינימום חדרים\n'
        '/add\\_group — הוספת קבוצת פייסבוק\n'
        '/remove\\_group — הסרת קבוצת פייסבוק\n'
        '/pause — השהיית הניטור\n'
        '/resume — המשך הניטור\n'
        '/status — הגדרות נוכחיות\n'
        '/cancel — ביטול פעולה\n'
        '/help — הודעה זו\n\n'
        '💡 *אפשר גם לכתוב בשפה חופשית בעברית או אנגלית*'
    ))


# ── /status ───────────────────────────────────────────────────────────────────

@owner_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply(update, get_config_summary())


# ── /add_city ─────────────────────────────────────────────────────────────────

@owner_only
async def cmd_add_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_state(chat_id, {'flow': 'add_city', 'step': 'city_name', 'data': {}})
    await reply(update, '🏙 *הוספת עיר*\n\nאיזו עיר תרצה לעקוב אחריה?')


# ── /remove_city ──────────────────────────────────────────────────────────────

@owner_only
async def cmd_remove_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cities = get_cities()
    if not cities:
        await reply(update, 'אין ערים מוגדרות.')
        return
    chat_id = update.effective_chat.id
    buttons = [[(city['name'], f'pick|{i}')] for i, city in enumerate(cities)]
    buttons.append([('❌ ביטול', 'confirm|no')])
    set_state(chat_id, {'flow': 'remove_city', 'step': 'pick', 'cities': cities})
    await reply(update, 'איזו עיר להסיר?', markup=kb(*buttons))


# ── /remove_neighborhood ──────────────────────────────────────────────────────

@owner_only
async def cmd_remove_neighborhood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cities = get_cities()
    all_neighborhoods = []
    for city in cities:
        for nbhd in get_neighborhoods(city['name']):
            all_neighborhoods.append({'city': city['name'], 'name': nbhd['name']})
    if not all_neighborhoods:
        await reply(update, 'אין שכונות מוגדרות.')
        return
    chat_id = update.effective_chat.id
    buttons = [[(f'{n["name"]} ({n["city"]})', f'pick|{i}')] for i, n in enumerate(all_neighborhoods)]
    buttons.append([('❌ ביטול', 'confirm|no')])
    set_state(chat_id, {'flow': 'remove_neighborhood', 'step': 'pick', 'neighborhoods': all_neighborhoods})
    await reply(update, 'איזו שכונה להסיר?', markup=kb(*buttons))


# ── /set_price ────────────────────────────────────────────────────────────────

@owner_only
async def cmd_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_state(chat_id, {'flow': 'set_price', 'step': 'price', 'data': {}})
    current = get_filter('global_max_price', 'לא מוגדר')
    await reply(update, f'מחיר נוכחי: *{current}*\n\nמחיר מקסימאלי חדש ב-₪?')


# ── /set_rooms ────────────────────────────────────────────────────────────────

@owner_only
async def cmd_set_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_state(chat_id, {'flow': 'set_rooms', 'step': 'rooms', 'data': {}})
    current = get_filter('rooms_min', '4')
    await reply(update, f'מינימום נוכחי: *{current}*\n\nמינימום חדרים חדש?')


# ── /add_group ────────────────────────────────────────────────────────────────

@owner_only
async def cmd_add_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_state(chat_id, {'flow': 'add_group_manual', 'step': 'url', 'data': {}})
    await reply(update, 'הדבק כתובת קבוצת הפייסבוק:')


# ── /remove_group ─────────────────────────────────────────────────────────────

@owner_only
async def cmd_remove_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    groups = get_facebook_groups()
    if not groups:
        await reply(update, 'אין קבוצות פייסבוק מוגדרות.')
        return
    chat_id = update.effective_chat.id
    buttons = []
    for i, url in enumerate(groups):
        label = url.replace('https://www.facebook.com/', 'fb/')[:45]
        buttons.append([(label, f'pick|{i}')])
    buttons.append([('❌ ביטול', 'confirm|no')])
    set_state(chat_id, {'flow': 'remove_group', 'step': 'pick', 'groups': groups})
    await reply(update, 'איזו קבוצה להסיר?', markup=kb(*buttons))


# ── /pause and /resume ────────────────────────────────────────────────────────

@owner_only
async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_state(chat_id, {'flow': 'pause', 'step': 'confirm', 'data': {}})
    await reply(update, 'להשהות את הניטור?',
                markup=kb([('⏸ השהה', 'confirm|yes'), ('❌ ביטול', 'confirm|no')]))


@owner_only
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_state(chat_id, {'flow': 'resume', 'step': 'confirm', 'data': {}})
    await reply(update, 'להמשיך את הניטור?',
                markup=kb([('▶️ המשך', 'confirm|yes'), ('❌ ביטול', 'confirm|no')]))


# ── /cancel ───────────────────────────────────────────────────────────────────

@owner_only
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_state(update.effective_chat.id)
    await reply(update, '❌ בוטל.')


# ── /confirm (text fallback) ──────────────────────────────────────────────────

@owner_only
async def cmd_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    if not state or state.get('step') != 'confirm':
        await reply(update, 'אין מה לאשר.')
        return
    await _do_confirmation(update, chat_id, state)


# ── Message handler ───────────────────────────────────────────────────────────

@owner_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    text = update.message.text.strip()

    if not state:
        intent = match_keyword(text)
        if intent is None:
            intent_data = await classify_intent(text)
            intent = intent_data.get('intent', 'unknown')
        else:
            intent_data = {}

        if intent == 'unknown':
            await update.message.reply_text(
                '👋 שלום! אני ניטור הדירות שלך.\nמה תרצה לעשות?',
                reply_markup=MAIN_MENU_MARKUP
            )
        else:
            await _route_intent(update, context, intent, intent_data)
        return

    flow = state.get('flow')
    step = state.get('step')
    data = state.setdefault('data', {})

    # ── add_city ──────────────────────────────────────────────────────────────
    if flow == 'add_city':

        if step == 'city_name':
            data['city_name'] = text
            yad2_info = YAD2_CITIES.get(text, {})
            data['yad2_city_id'] = yad2_info.get('city_id')
            data['yad2_region_id'] = yad2_info.get('region_id')
            state['step'] = 'max_price'
            set_state(chat_id, state)
            await reply(update, f'*{text}* — בסדר!\n\nמחיר מקסימאלי ב-₪?',
                        markup=kb([('⏩ דלג', 'skip|max_price')]))

        elif step == 'max_price':
            if text.isdigit():
                data['max_price'] = int(text)
            state['step'] = 'rooms'
            set_state(chat_id, state)
            await reply(update, 'מינימום חדרים? (לדוגמה: 4 או 3.5)')

        elif step == 'rooms':
            try:
                data['rooms'] = float(text)
            except ValueError:
                await reply(update, 'אנא הכנס מספר כמו 4 או 3.5')
                return
            state['step'] = 'neighborhood'
            set_state(chat_id, state)
            await reply(update, 'שכונה ספציפית?',
                        markup=kb([('⏩ דלג (כל העיר)', 'skip|neighborhood')]))

        elif step == 'neighborhood':
            data['neighborhood'] = text
            state['step'] = 'must_have'
            set_state(chat_id, state)
            await reply(update, 'דרישות חובה?',
                        markup=kb(
                            [('🚗 חניה', 'must_have|parking'), ('🛡 ממ"ד', 'must_have|safe_room')],
                            [('✅ שניהם', 'must_have|both'), ('➡️ ללא', 'must_have|neither')]
                        ))

        elif step == 'confirm':
            pass  # handled by /confirm or inline button

    # ── add_groups ────────────────────────────────────────────────────────────
    elif flow == 'add_groups':
        if step == 'url':
            if text.startswith('http') and 'facebook.com' in text:
                add_facebook_group(text)
                data.setdefault('facebook_groups', []).append(text)
                set_state(chat_id, state)
                count = len(data['facebook_groups'])
                await reply(update, f'✅ קבוצה {count} נוספה. הדבק עוד כתובת או /done לסיום.')
            else:
                await reply(update, 'אנא הדבק כתובת קבוצת פייסבוק תקינה, או /done לסיום.')

    # ── remove_city ───────────────────────────────────────────────────────────
    elif flow == 'remove_city':
        if step == 'pick':
            await reply(update, 'אנא בחר עיר מהרשימה למעלה.')

    # ── remove_neighborhood ───────────────────────────────────────────────────
    elif flow == 'remove_neighborhood':
        if step == 'pick':
            await reply(update, 'אנא בחר שכונה מהרשימה למעלה.')

    # ── set_price (apply immediately, no confirm) ─────────────────────────────
    elif flow == 'set_price':
        if step == 'price':
            if text.isdigit():
                set_filter('global_max_price', text)
                clear_state(chat_id)
                await reply(update, f'✅ מחיר מקסימאלי עודכן ל-*{int(text):,} ₪*.')
            else:
                await reply(update, 'אנא הכנס מספר כמו 13000')

    # ── set_rooms (apply immediately, no confirm) ─────────────────────────────
    elif flow == 'set_rooms':
        if step == 'rooms':
            try:
                rooms = float(text)
                set_filter('rooms_min', str(rooms))
                clear_state(chat_id)
                await reply(update, f'✅ מינימום חדרים עודכן ל-*{rooms}*.')
            except ValueError:
                await reply(update, 'אנא הכנס מספר כמו 4 או 3.5')

    # ── add_group_manual (apply immediately, no confirm) ──────────────────────
    elif flow == 'add_group_manual':
        if step == 'url':
            if text.startswith('http') and 'facebook.com' in text:
                add_facebook_group(text)
                clear_state(chat_id)
                await reply(update, '✅ הקבוצה נוספה.')
            else:
                await reply(update, 'אנא הדבק כתובת קבוצת פייסבוק תקינה.')

    # ── remove_group ──────────────────────────────────────────────────────────
    elif flow == 'remove_group':
        if step == 'pick':
            await reply(update, 'אנא בחר קבוצה מהרשימה למעלה.')


# ── /done ─────────────────────────────────────────────────────────────────────

@owner_only
async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    if not state:
        await reply(update, 'אין פעולה פעילה.')
        return

    flow = state.get('flow')
    data = state.get('data', {})

    if flow == 'add_groups':
        count = len(data.get('facebook_groups', []))
        clear_state(chat_id)
        if count:
            suffix = 'ות' if count != 1 else 'ה'
            verb = 'נוספו' if count != 1 else 'נוספה'
            await reply(update, f'✅ סיום — {count} קבוצ{suffix} {verb}.')
        else:
            await reply(update, '✅ סיום. השתמש ב /add\\_group להוספת קבוצות מאוחר יותר.')
    else:
        await reply(update, 'השתמש ב /cancel לביטול.')


# ── /skip ─────────────────────────────────────────────────────────────────────

@owner_only
async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    if not state:
        await reply(update, 'אין פעולה פעילה.')
        return

    flow = state.get('flow')
    step = state.get('step')

    if flow == 'add_city':
        if step == 'max_price':
            state['step'] = 'rooms'
            set_state(chat_id, state)
            await reply(update, 'מינימום חדרים? (לדוגמה: 4 או 3.5)')
        elif step == 'neighborhood':
            state['step'] = 'must_have'
            set_state(chat_id, state)
            await reply(update, 'דרישות חובה?',
                        markup=kb(
                            [('🚗 חניה', 'must_have|parking'), ('🛡 ממ"ד', 'must_have|safe_room')],
                            [('✅ שניהם', 'must_have|both'), ('➡️ ללא', 'must_have|neither')]
                        ))
        else:
            await reply(update, 'אין מה לדלג כאן.')
    elif flow == 'add_groups':
        clear_state(chat_id)
        await reply(update, '✅ סיום. השתמש ב /add\\_group להוספת קבוצות מאוחר יותר.')
    else:
        await reply(update, 'אין מה לדלג.')


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
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
