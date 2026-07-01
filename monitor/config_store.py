"""
Config Store — Supabase backed
All configuration persists in Supabase PostgreSQL.
Survives Railway restarts and redeploys.
"""

import os
import json
import logging
from typing import Optional

log = logging.getLogger(__name__)

_client = None


def get_client():
    global _client
    if _client is None:
        from supabase import create_client
        url = os.environ.get('SUPABASE_URL')
        key = os.environ.get('SUPABASE_KEY')
        if not url or not key:
            raise ValueError('SUPABASE_URL and SUPABASE_KEY must be set')
        _client = create_client(url, key)
    return _client


def init_config_db():
    """No-op — tables created via SQL migration in Supabase."""
    log.info('Supabase config store ready')


# ── Cities ────────────────────────────────────────────────────────────────────

def add_city(name: str, yad2_city_id: str = None, yad2_region_id: str = None,
             madlan_doc_id: str = None, max_price: int = None):
    try:
        get_client().table('cities').upsert({
            'name': name,
            'yad2_city_id': yad2_city_id,
            'yad2_region_id': yad2_region_id,
            'madlan_doc_id': madlan_doc_id,
            'max_price': max_price,
            'active': True
        }, on_conflict='name').execute()
    except Exception as e:
        log.error(f'add_city error: {e}')


def remove_city(name: str):
    try:
        get_client().table('cities').update({'active': False}).eq('name', name).execute()
    except Exception as e:
        log.error(f'remove_city error: {e}')


def get_cities() -> list:
    try:
        result = get_client().table('cities').select('*').eq('active', True).execute()
        return result.data or []
    except Exception as e:
        log.error(f'get_cities error: {e}')
        return []


# ── Neighborhoods ─────────────────────────────────────────────────────────────

def add_neighborhood(city_name: str, name: str, yad2_area_id: str = None,
                     madlan_slug: str = None):
    try:
        get_client().table('neighborhoods').upsert({
            'city_name': city_name,
            'name': name,
            'yad2_area_id': yad2_area_id,
            'madlan_slug': madlan_slug,
            'active': True
        }, on_conflict='city_name,name').execute()
    except Exception as e:
        log.error(f'add_neighborhood error: {e}')


def remove_neighborhood(city_name: str, name: str):
    try:
        get_client().table('neighborhoods').update(
            {'active': False}
        ).eq('city_name', city_name).eq('name', name).execute()
    except Exception as e:
        log.error(f'remove_neighborhood error: {e}')


def get_neighborhoods(city_name: str) -> list:
    try:
        result = get_client().table('neighborhoods').select('*').eq(
            'city_name', city_name).eq('active', True).execute()
        return result.data or []
    except Exception as e:
        log.error(f'get_neighborhoods error: {e}')
        return []


# ── Facebook Groups ───────────────────────────────────────────────────────────

def add_facebook_group(url: str):
    try:
        get_client().table('facebook_groups').upsert({
            'url': url,
            'active': True
        }, on_conflict='url').execute()
    except Exception as e:
        log.error(f'add_facebook_group error: {e}')


def remove_facebook_group(url: str):
    try:
        get_client().table('facebook_groups').update(
            {'active': False}
        ).eq('url', url).execute()
    except Exception as e:
        log.error(f'remove_facebook_group error: {e}')


def get_facebook_groups() -> list:
    try:
        result = get_client().table('facebook_groups').select('url').eq(
            'active', True).execute()
        return [r['url'] for r in (result.data or [])]
    except Exception as e:
        log.error(f'get_facebook_groups error: {e}')
        return []


# ── Filters ───────────────────────────────────────────────────────────────────

def set_filter(key: str, value):
    try:
        get_client().table('filters').upsert({
            'key': key,
            'value': str(value)
        }, on_conflict='key').execute()
    except Exception as e:
        log.error(f'set_filter error: {e}')


def get_filter(key: str, default=None):
    try:
        result = get_client().table('filters').select('value').eq('key', key).execute()
        if result.data:
            return result.data[0]['value']
        return default
    except Exception as e:
        log.error(f'get_filter error: {e}')
        return default


def get_all_filters() -> dict:
    try:
        result = get_client().table('filters').select('*').execute()
        return {r['key']: r['value'] for r in (result.data or [])}
    except Exception as e:
        log.error(f'get_all_filters error: {e}')
        return {}


# ── Monitor State ─────────────────────────────────────────────────────────────

def is_paused() -> bool:
    try:
        result = get_client().table('monitor_state').select('value').eq(
            'key', 'paused').execute()
        return result.data and result.data[0]['value'] == 'true'
    except Exception as e:
        log.error(f'is_paused error: {e}')
        return False


def set_paused(paused: bool):
    try:
        get_client().table('monitor_state').upsert({
            'key': 'paused',
            'value': 'true' if paused else 'false'
        }, on_conflict='key').execute()
    except Exception as e:
        log.error(f'set_paused error: {e}')


# ── Bot conversation state (persisted so Railway restarts don't lose flows) ───

def get_bot_state(chat_id: str) -> dict:
    try:
        result = get_client().table('monitor_state').select('value').eq(
            'key', f'bot_state_{chat_id}').execute()
        if result.data:
            return json.loads(result.data[0]['value'])
        return {}
    except Exception as e:
        log.error(f'get_bot_state error: {e}')
        return {}


def set_bot_state(chat_id: str, state: dict):
    try:
        get_client().table('monitor_state').upsert({
            'key': f'bot_state_{chat_id}',
            'value': json.dumps(state, ensure_ascii=False)
        }, on_conflict='key').execute()
    except Exception as e:
        log.error(f'set_bot_state error: {e}')


def clear_bot_state(chat_id: str):
    try:
        get_client().table('monitor_state').delete().eq(
            'key', f'bot_state_{chat_id}').execute()
    except Exception as e:
        log.error(f'clear_bot_state error: {e}')


def get_today_alerts() -> dict:
    try:
        result = get_client().table('monitor_state').select('value').eq(
            'key', 'today_alerts').execute()
        if result.data:
            return json.loads(result.data[0]['value'])
        return {}
    except Exception as e:
        log.error(f'get_today_alerts error: {e}')
        return {}


def save_today_alerts(data: dict):
    try:
        get_client().table('monitor_state').upsert({
            'key': 'today_alerts',
            'value': json.dumps(data, ensure_ascii=False)
        }, on_conflict='key').execute()
    except Exception as e:
        log.error(f'save_today_alerts error: {e}')


def clear_today_alerts():
    try:
        get_client().table('monitor_state').delete().eq(
            'key', 'today_alerts').execute()
    except Exception as e:
        log.error(f'clear_today_alerts error: {e}')


def get_expansion_cooldown(city_name: str):
    """Return the datetime of the last expansion suggestion sent for city_name, or None."""
    import datetime
    try:
        result = get_client().table('monitor_state').select('value').eq(
            'key', f'expansion_cooldown_{city_name}').execute()
        if result.data:
            return datetime.datetime.fromisoformat(result.data[0]['value'])
        return None
    except Exception as e:
        log.error(f'get_expansion_cooldown error: {e}')
        return None


def set_expansion_cooldown(city_name: str, when):
    try:
        get_client().table('monitor_state').upsert({
            'key': f'expansion_cooldown_{city_name}',
            'value': when.isoformat()
        }, on_conflict='key').execute()
    except Exception as e:
        log.error(f'set_expansion_cooldown error: {e}')


def get_city_thread_id(city_name: str):
    try:
        result = get_client().table('monitor_state').select('value').eq(
            'key', f'thread_{city_name}').execute()
        if result.data:
            return result.data[0]['value']
        return None
    except Exception as e:
        log.error(f'get_city_thread_id error: {e}')
        return None


def set_city_thread_id(city_name: str, thread_id: str):
    try:
        get_client().table('monitor_state').upsert({
            'key': f'thread_{city_name}',
            'value': str(thread_id)
        }, on_conflict='key').execute()
    except Exception as e:
        log.error(f'set_city_thread_id error: {e}')


# ── Config Summary ────────────────────────────────────────────────────────────

def get_config_summary() -> str:
    _CITY_COLORS = ['🔴', '🟠', '🟡', '🟢', '🔵', '🟣', '🟤', '⚫']

    def _color(name):
        return _CITY_COLORS[hash(name) % len(_CITY_COLORS)]

    cities = get_cities()
    groups = get_facebook_groups()
    filters = get_all_filters()
    paused = is_paused()

    parking_on = filters.get('must_have_parking') == 'true'
    safe_room_on = filters.get('must_have_safe_room') == 'true'

    lines = ['*📋 סטטוס ניטור דירות*\n']
    lines.append('*⚙️ הגדרות כלליות*')
    lines.append(f'▫️ מצב: {"⏸ מושהה" if paused else "✅ פעיל"}')
    lines.append(f'▫️ מינ\' חדרים: {filters.get("rooms_min", "4")}')
    lines.append(f'▫️ חניה חובה: {"✅" if parking_on else "❌"}')
    lines.append(f'▫️ ממ"ד חובה: {"✅" if safe_room_on else "❌"}')

    lines.append('\n*🏙 ערים במעקב*')
    if not cities:
        lines.append('אין ערים מוגדרות')
    for city in cities:
        color = _color(city['name'])
        price = f'עד {city["max_price"]:,} ₪' if city.get('max_price') else 'ללא הגבלה'
        neighborhoods = get_neighborhoods(city['name'])
        nbhd_str = ', '.join(n['name'] for n in neighborhoods) if neighborhoods else 'כל העיר'
        lines.append(f'{color} *{city["name"]}*')
        lines.append(f'   💰 {price}')
        lines.append(f'   📍 {nbhd_str}')

    lines.append('\n*👥 קבוצות פייסבוק*')
    if not groups:
        lines.append('אין קבוצות מוגדרות')
    for i, url in enumerate(groups, 1):
        label = url.replace('https://www.facebook.com/', 'fb/')
        lines.append(f'{i}\\. {label}')

    return '\n'.join(lines)
