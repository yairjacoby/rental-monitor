"""
Config Store
SQLite-backed configuration manager.
All search parameters live here — managed via Telegram bot commands.
Replaces config.json for runtime configuration.
"""

from typing import Optional
import sqlite3
import json
import os
import logging

log = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), 'seen_listings.db')


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_config_db():
    """Create config tables if they don't exist."""
    conn = get_conn()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS cities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            yad2_city_id TEXT,
            yad2_region_id TEXT,
            madlan_doc_id TEXT,
            max_price INTEGER,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS neighborhoods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city_name TEXT NOT NULL,
            name TEXT NOT NULL,
            yad2_area_id TEXT,
            active INTEGER DEFAULT 1,
            UNIQUE(city_name, name)
        );

        CREATE TABLE IF NOT EXISTS facebook_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS filters (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS monitor_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    ''')

    # Default filters if not set
    defaults = {
        'rooms_min': '4',
        'must_have_parking': 'true',
        'must_have_safe_room': 'true',
    }
    for key, value in defaults.items():
        conn.execute(
            'INSERT OR IGNORE INTO filters (key, value) VALUES (?, ?)',
            (key, value)
        )

    # Default monitor state
    conn.execute(
        'INSERT OR IGNORE INTO monitor_state (key, value) VALUES (?, ?)',
        ('paused', 'false')
    )

    # Migrations — add columns that may be missing from older DBs
    cols = [row[1] for row in conn.execute('PRAGMA table_info(cities)').fetchall()]
    if 'yad2_region_id' not in cols:
        conn.execute('ALTER TABLE cities ADD COLUMN yad2_region_id TEXT')

    # Migration — add madlan_slug to neighborhoods if not exists
    try:
        conn.execute('ALTER TABLE neighborhoods ADD COLUMN madlan_slug TEXT')
        conn.commit()
    except Exception:
        pass  # Column already exists

    conn.commit()
    conn.close()
    log.info('Config DB initialized')


# ── Cities ────────────────────────────────────────────────────────────────────

def add_city(name: str, yad2_city_id: str = None, yad2_region_id: str = None,
             madlan_doc_id: str = None, max_price: int = None):
    conn = get_conn()
    conn.execute('''
        INSERT INTO cities (name, yad2_city_id, yad2_region_id, madlan_doc_id, max_price)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            yad2_city_id = excluded.yad2_city_id,
            yad2_region_id = excluded.yad2_region_id,
            madlan_doc_id = excluded.madlan_doc_id,
            max_price = excluded.max_price,
            active = 1
    ''', (name, yad2_city_id, yad2_region_id, madlan_doc_id, max_price))
    conn.commit()
    conn.close()


def remove_city(name: str):
    conn = get_conn()
    conn.execute('UPDATE cities SET active = 0 WHERE name = ?', (name,))
    conn.commit()
    conn.close()


def get_cities() -> list:
    conn = get_conn()
    rows = conn.execute(
        'SELECT name, yad2_city_id, yad2_region_id, madlan_doc_id, max_price FROM cities WHERE active = 1'
    ).fetchall()
    conn.close()
    return [
        {'name': r[0], 'yad2_city_id': r[1], 'yad2_region_id': r[2], 'madlan_doc_id': r[3], 'max_price': r[4]}
        for r in rows
    ]


# ── Neighborhoods ─────────────────────────────────────────────────────────────

def add_neighborhood(city_name: str, name: str, yad2_area_id: str = None, madlan_slug: str = None):
    conn = get_conn()
    conn.execute('''
        INSERT INTO neighborhoods (city_name, name, yad2_area_id, madlan_slug)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(city_name, name) DO UPDATE SET
            yad2_area_id = excluded.yad2_area_id,
            madlan_slug = excluded.madlan_slug,
            active = 1
    ''', (city_name, name, yad2_area_id, madlan_slug))
    conn.commit()
    conn.close()


def remove_neighborhood(city_name: str, name: str):
    conn = get_conn()
    conn.execute(
        'UPDATE neighborhoods SET active = 0 WHERE city_name = ? AND name = ?',
        (city_name, name)
    )
    conn.commit()
    conn.close()


def get_neighborhoods(city_name: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        'SELECT name, yad2_area_id, madlan_slug FROM neighborhoods WHERE city_name = ? AND active = 1',
        (city_name,)
    ).fetchall()
    conn.close()
    return [{'name': r[0], 'yad2_area_id': r[1], 'madlan_slug': r[2]} for r in rows]


# ── Facebook Groups ───────────────────────────────────────────────────────────

def add_facebook_group(url: str):
    conn = get_conn()
    conn.execute(
        'INSERT OR IGNORE INTO facebook_groups (url) VALUES (?)', (url,)
    )
    conn.execute(
        'UPDATE facebook_groups SET active = 1 WHERE url = ?', (url,)
    )
    conn.commit()
    conn.close()


def remove_facebook_group(url: str):
    conn = get_conn()
    conn.execute(
        'UPDATE facebook_groups SET active = 0 WHERE url = ?', (url,)
    )
    conn.commit()
    conn.close()


def get_facebook_groups() -> list:
    conn = get_conn()
    rows = conn.execute(
        'SELECT url FROM facebook_groups WHERE active = 1'
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


# ── Filters ───────────────────────────────────────────────────────────────────

def set_filter(key: str, value):
    conn = get_conn()
    conn.execute(
        'INSERT OR REPLACE INTO filters (key, value) VALUES (?, ?)',
        (key, str(value))
    )
    conn.commit()
    conn.close()


def get_filter(key: str, default=None):
    conn = get_conn()
    row = conn.execute(
        'SELECT value FROM filters WHERE key = ?', (key,)
    ).fetchone()
    conn.close()
    if row is None:
        return default
    return row[0]


def get_all_filters() -> dict:
    conn = get_conn()
    rows = conn.execute('SELECT key, value FROM filters').fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


# ── Monitor State ─────────────────────────────────────────────────────────────

def is_paused() -> bool:
    conn = get_conn()
    row = conn.execute(
        'SELECT value FROM monitor_state WHERE key = ?', ('paused',)
    ).fetchone()
    conn.close()
    return row and row[0] == 'true'


def set_paused(paused: bool):
    conn = get_conn()
    conn.execute(
        'INSERT OR REPLACE INTO monitor_state (key, value) VALUES (?, ?)',
        ('paused', 'true' if paused else 'false')
    )
    conn.commit()
    conn.close()


# ── Full Config Summary ───────────────────────────────────────────────────────

def get_config_summary() -> str:
    cities = get_cities()
    groups = get_facebook_groups()
    filters = get_all_filters()
    paused = is_paused()

    lines = ['📋 Current config:\n']
    lines.append(f'⏸ Status: {"PAUSED" if paused else "✅ Active"}')
    lines.append(f'🛏 Min rooms: {filters.get("rooms_min", "4")}')
    lines.append(f'🚗 Parking required: {filters.get("must_have_parking", "true")}')
    lines.append(f'🛡 Safe room required: {filters.get("must_have_safe_room", "true")}')

    lines.append('\n🏙 Cities:')
    if not cities:
        lines.append('  None configured')
    for city in cities:
        price = f'{city["max_price"]:,} ₪' if city['max_price'] else 'no limit'
        neighborhoods = get_neighborhoods(city['name'])
        nbhd_str = ', '.join(n['name'] for n in neighborhoods) if neighborhoods else 'all'
        lines.append(f'  • {city["name"]} — max {price} — neighborhoods: {nbhd_str}')

    lines.append('\n👥 Facebook groups:')
    if not groups:
        lines.append('  None configured')
    for i, url in enumerate(groups, 1):
        lines.append(f'  {i}. {url}')

    return '\n'.join(lines)
