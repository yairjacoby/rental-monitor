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
    cities = get_cities()
    groups = get_facebook_groups()
    filters = get_all_filters()
    paused = is_paused()

    lines = ['📋 Current config:\n']
    lines.append(f'⏸ Status: {"PAUSED" if paused else "✅ Active"}')
    lines.append(f'🛏 Min rooms: {filters.get("rooms_min", "4")}')
    lines.append(f'🚗 Parking required: {filters.get("must_have_parking", "false")}')
    lines.append(f'🛡 Safe room required: {filters.get("must_have_safe_room", "false")}')

    lines.append('\n🏙 Cities:')
    if not cities:
        lines.append('  None configured')
    for city in cities:
        price = f'{city["max_price"]:,} ₪' if city.get('max_price') else 'no limit'
        neighborhoods = get_neighborhoods(city['name'])
        nbhd_str = ', '.join(n['name'] for n in neighborhoods) if neighborhoods else 'all'
        lines.append(f'  • {city["name"]} — max {price} — neighborhoods: {nbhd_str}')

    lines.append('\n👥 Facebook groups:')
    if not groups:
        lines.append('  None configured')
    for i, url in enumerate(groups, 1):
        lines.append(f'  {i}. {url}')

    return '\n'.join(lines)
